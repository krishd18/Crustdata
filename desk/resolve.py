"""Decide which company a question means -- or refuse to decide.

The failure this module exists to prevent: a question says "Mahindra", the
resolver takes the highest-ranked match, and every fact after that is about
the wrong entity while looking perfectly well sourced. The hidden test set
contains a lookalike case precisely to catch that.

So the resolver has three outcomes, not two:

    resolved    one entity, and we can say why it and not the others
    ambiguous   several readings; the question cannot be answered as asked
    unknown     the name matches nothing we can find

``ambiguous`` is a result, not an error. Returning it is the system working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .crustdata import CrustdataClient, CrustdataError
from .models import EntityCandidate
from .rivals import Match, RivalRegistry, _norm


@dataclass
class Resolution:
    query: str
    status: str                       # resolved | ambiguous | unknown
    entity: EntityCandidate | None = None
    candidates: list[EntityCandidate] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    why: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class EntityResolver:
    def __init__(
        self,
        registry: RivalRegistry,
        client: CrustdataClient | None = None,
    ) -> None:
        self.registry = registry
        self.client = client

    def resolve(self, name: str) -> Resolution:
        matches = self.registry.lookup(name)

        if not matches:
            return self._resolve_unlisted(name)

        # More than one rival answers to this string. That is ambiguity even
        # before we ask the API anything.
        if len(matches) > 1:
            return Resolution(
                query=name,
                status="ambiguous",
                candidates=[self._candidate(m) for m in matches],
                why=f"{len(matches)} rivals in the registry answer to this name",
            )

        match = matches[0]
        rival = match.rival
        cautions = [match.caution] if match.caution else []

        # A partial match means the asker gave less than the full name --
        # "Mahindra" rather than "Mahindra Logistics". The group and the arm
        # are different companies, and guessing between them is the trap.
        confusables = self.registry.ambiguity(name)
        asked_for_full_name = _norm(name) == _norm(rival.display_name) or any(
            _norm(name) == _norm(a) for a in rival.aliases
        )

        if match.how == "partial" or (confusables and not asked_for_full_name):
            candidates = [self._candidate(match)]
            candidates += [
                EntityCandidate(
                    display_name=c,
                    reason="a different entity that this name could mean",
                    relationship=(
                        "parent group" if c == rival.parent_group else "related entity"
                    ),
                )
                for c in confusables
            ]
            return Resolution(
                query=name,
                status="ambiguous",
                candidates=candidates,
                cautions=cautions,
                why=(
                    f"'{name}' could mean {rival.display_name} or "
                    f"{len(confusables)} related entit"
                    f"{'y' if len(confusables) == 1 else 'ies'}; "
                    "the question does not say which"
                ),
            )

        entity = self._candidate(match)
        entity = self._confirm_against_api(entity, rival.domain)

        return Resolution(
            query=name,
            status="resolved",
            entity=entity,
            search_terms=rival.search_terms(),
            cautions=cautions,
            why=f"matched {rival.display_name} on its {match.how.replace('_', ' ')}",
        )

    # ------------------------------------------------------------------

    def _candidate(self, match: Match) -> EntityCandidate:
        r = match.rival
        return EntityCandidate(
            display_name=r.display_name,
            reason=f"registry {match.how.replace('_', ' ')}: {match.matched_on}",
            domain=r.domain,
            relationship=("logistics arm" if r.parent_group else None),
        )

    def _confirm_against_api(
        self, entity: EntityCandidate, domain: str | None
    ) -> EntityCandidate:
        """Attach a Crustdata id when we can. Never changes the decision.

        The registry decided which entity is meant; the API only supplies the
        handle to look it up. If identify disagrees, we keep the registry's
        name and say nothing we cannot support.
        """
        if not self.client or not domain:
            return entity
        try:
            matches = self.client.identify_company(domain)
        except CrustdataError:
            return entity
        if not matches:
            return entity
        top: dict[str, Any] = matches[0]
        data = top.get("company_data") or top
        entity.crustdata_company_id = str(
            data.get("company_id") or data.get("crustdata_company_id") or ""
        ) or None
        return entity

    def _resolve_unlisted(self, name: str) -> Resolution:
        """A name not in the registry. Ask the API, and refuse if it is unsure."""
        if not self.client:
            return Resolution(
                query=name,
                status="unknown",
                why="not a listed rival, and no live lookup available",
            )
        try:
            matches = self.client.identify_company(name)
        except CrustdataError as exc:
            return Resolution(
                query=name, status="unknown", why=f"lookup failed: {exc}"
            )

        if not matches:
            return Resolution(
                query=name, status="unknown", why="no company matched this name"
            )

        candidates = []
        for m in matches[:5]:
            data = m.get("company_data") or m
            candidates.append(
                EntityCandidate(
                    display_name=str(
                        data.get("name")
                        or (data.get("basic_info") or {}).get("name")
                        or name
                    ),
                    reason=f"company/identify match, confidence "
                    f"{m.get('confidence_score', 'unknown')}",
                    crustdata_company_id=str(
                        data.get("company_id") or data.get("crustdata_company_id") or ""
                    )
                    or None,
                    domain=str(
                        data.get("domain")
                        or (data.get("basic_info") or {}).get("primary_domain")
                        or ""
                    )
                    or None,
                )
            )

        if len(candidates) > 1:
            return Resolution(
                query=name,
                status="ambiguous",
                candidates=candidates,
                why=f"{len(candidates)} companies match this name",
            )

        return Resolution(
            query=name,
            status="resolved",
            entity=candidates[0],
            search_terms=[name],
            why="single match from company/identify",
        )
