"""AgentContext factory (docs/AGENTS.md §1): clients, stores, budget, clock, run id — injected, never built in an agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .budget import Budget
from .claude import ClaudeClient
from .clock import Clock
from .config_loader import Config, get_config
from .crustdata import CrustdataClient
from .gateway import Gateway
from .ids import short
from .logging import get_logger
from .settings import Settings, get_settings
from .stores import Stores
from .types import Evidence

_STORES: dict[str, Stores] = {}


def get_stores(path: str | None = None) -> Stores:
    p = path or str(get_settings().db_path)
    if p not in _STORES:
        _STORES[p] = Stores(p)
    return _STORES[p]


@dataclass
class AgentContext:
    run_id: str
    clock: Clock
    config: Config
    stores: Stores
    settings: Settings
    budget: Budget
    gateway: Gateway
    crustdata: CrustdataClient
    claude: ClaudeClient
    log: Any
    mail: Any = None
    notes: list[str] = field(default_factory=list)

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds") if not self.clock.frozen else self.clock.now().isoformat()

    def evidence(self, *, source: str, url_or_endpoint: str, passage_or_field: str, value: Any, record_date: str | None,
                 content_sha256: str, tier: str, media_tier: str | None = None, relation: str = "supports",
                 kind: str = "field", claim_id: str = "", offset: int | None = None,
                 attributed_to_company_quote: bool = False) -> Evidence:
        """Build an Evidence row and persist it in the ledger. Callers must have quote-locked it first (A6)."""
        eid = short("E", self.run_id, source, url_or_endpoint, passage_or_field, str(value), claim_id)
        ev = Evidence(evidence_id=eid, source=source, url_or_endpoint=url_or_endpoint, passage_or_field=passage_or_field,
                      value=value, record_date=record_date, retrieved_at=self.clock.now().isoformat(timespec="seconds"),
                      content_sha256=content_sha256, tier=tier, media_tier=media_tier, relation=relation, kind=kind,
                      offset=offset, attributed_to_company_quote=attributed_to_company_quote)
        self.stores.x("INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, self.run_id, claim_id, source, url_or_endpoint, passage_or_field, str(value)[:2000], record_date,
                       ev.retrieved_at, content_sha256, tier, media_tier, offset))
        return ev


def make_context(run_id: str = "-", family: str = "FIND_LIST", mode: str | None = None, frozen_now: str | None = None,
                 limits: dict | None = None, stores: Stores | None = None, transport=None, sdk_client=None,
                 cassette: str | None = None, sleep=None) -> AgentContext:
    cfg, s = get_config(), get_settings()
    st = stores or get_stores()
    budget = Budget.for_family(cfg["limits"], family, limits)
    kw = {"sleep": sleep} if sleep else {}
    gw = Gateway(st, cfg["sources"], budget, run_id, mode=mode, transport=transport, cassette=cassette, **kw)
    cc = ClaudeClient(st, cfg["llm"], s, run_id, budget, sdk_client=sdk_client, mode=mode or gw.mode, cassette=cassette, **kw)
    return AgentContext(run_id=run_id, clock=Clock(frozen_now), config=cfg, stores=st, settings=s, budget=budget,
                        gateway=gw, crustdata=CrustdataClient(gw, s, cfg["sources"]), claude=cc, log=get_logger(f"run.{run_id}"))
