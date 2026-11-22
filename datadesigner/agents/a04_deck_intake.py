"""A4 Deck Intake & Claim Extractor (ARCHITECTURE §8): PDF (PyMuPDF) / PPTX / XLSX / text → pages (doc_id, page,
sha256) → Claude (reason) extracts typed claims with exact spans; every span is re-checked against the page text
and claims without a valid span are dropped. Injection text is logged and ignored. Packs may also carry
pre-extracted claims (fixtures), which go through the same span check."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.claude import find_injections, load_prompt, wrap_untrusted
from ..core.errors import ParseFailed, SecretMissing
from ..core.ids import sha256
from ..core.quote_lock import lock
from ..core.types import Claim, Span
from .base import BaseAgent, cli

CRITICAL_DEFAULT = ["incorporation_date", "revenue", "headcount", "fleet_size", "locations", "warehouse_area", "customer",
                    "contract_win", "contract_renewal", "gst_status", "funding", "ebitda", "arr", "certification"]


class Pack(BaseModel):
    files: list[str] = Field(default_factory=list)
    pages: list[dict] = Field(default_factory=list)       # [{doc_id, page, text, slide?}]
    claims: list[dict] = Field(default_factory=list)      # optional pre-extracted (fixtures)
    purpose: str = "acquisition_target"
    critical_claims: list[str] = Field(default_factory=lambda: list(CRITICAL_DEFAULT))
    use_llm: bool = True


class ClaimSet(BaseModel):
    docs: list[dict] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    dropped: list[dict] = Field(default_factory=list)
    injection_attempts: list[dict] = Field(default_factory=list)


class LLMClaim(BaseModel):
    type: str
    kind: str
    subject: str
    text: str
    value: str | None
    unit: str | None
    as_of: str | None
    critical: bool
    slide: int | None
    span: Span


class LLMClaims(BaseModel):
    claims: list[LLMClaim]
    injection_attempts: list[dict]


def parse_file(path: str) -> list[dict]:
    p = Path(path)
    doc = p.stem
    if p.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(p) as d:
            return [{"doc_id": doc, "page": i + 1, "text": pg.get_text()} for i, pg in enumerate(d)]
    if p.suffix.lower() == ".pptx":
        from pptx import Presentation
        out = []
        for i, s in enumerate(Presentation(str(p)).slides):
            txt = "\n".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame)
            if s.has_notes_slide:
                txt += "\n" + s.notes_slide.notes_text_frame.text
            out.append({"doc_id": doc, "page": i + 1, "slide": i + 1, "text": txt})
        return out
    if p.suffix.lower() == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(p, data_only=True)
        return [{"doc_id": doc, "page": i + 1, "text": "\n".join(" | ".join("" if c is None else str(c) for c in r) for r in ws.iter_rows(values_only=True))}
                for i, ws in enumerate(wb.worksheets)]
    return [{"doc_id": doc, "page": 1, "text": p.read_text(errors="ignore")}]


class DeckIntake(BaseAgent[Pack, ClaimSet]):
    name, input_model, output_model = "a04_deck_intake", Pack, ClaimSet
    deterministic = False

    def run(self, inp: Pack, ctx) -> ClaimSet:
        pages = list(inp.pages)
        for f in inp.files:
            pages += parse_file(f)
        for pg in pages:
            pg["sha256"] = ctx.stores.put_blob(pg["text"], "text/plain")
        out = ClaimSet(docs=[{"doc_id": d, "pages": [{"page": p["page"], "sha256": p["sha256"]} for p in pages if p["doc_id"] == d]}
                             for d in dict.fromkeys(p["doc_id"] for p in pages)])
        for pg in pages:
            for hit in find_injections(pg["text"]):
                out.injection_attempts.append({"doc_id": pg["doc_id"], "page": pg["page"], "text": hit})
                ctx.log.warning("a04.injection_ignored", doc_id=pg["doc_id"], page=pg["page"])
        raw = list(inp.claims)
        if not raw and pages and inp.use_llm:
            user = (f"PURPOSE: {inp.purpose} · CRITICAL CLAIMS: {inp.critical_claims}\nPAGES: "
                    + wrap_untrusted(json.dumps([{k: p[k] for k in ("doc_id", "page", "text")} for p in pages], ensure_ascii=False), "counterparty_pack"))
            try:
                res, _ = ctx.claude.generate_json("reason", load_prompt("claim_extractor"), user, LLMClaims, task="claim_extractor")
                raw = [c.model_dump() for c in res.claims]
            except (ParseFailed, SecretMissing) as e:
                out.dropped.append({"reason": f"claim extraction could not parse: {type(e).__name__}"})
        bypage = {(p["doc_id"], p["page"]): p for p in pages}
        for i, c in enumerate(raw):
            sp = c.get("span") or {}
            pg = bypage.get((sp.get("doc_id"), sp.get("page")))
            if not pg:
                out.dropped.append({"text": c.get("text", "")[:80], "reason": "span page not found"})
                continue
            seg = pg["text"][sp.get("start", 0): sp.get("end", 0)]
            if not seg or lock(c.get("text", ""), seg) is None:
                off = lock(c.get("text", ""), pg["text"])       # LLM offsets drift: re-anchor on the verbatim text
                if off is None:
                    out.dropped.append({"text": c.get("text", "")[:80], "reason": "claim text not verbatim on its page"})
                    continue
                sp = {"doc_id": pg["doc_id"], "page": pg["page"], "start": off, "end": off + len(c["text"])}
            ctype = c.get("type", "other")
            cl = Claim(claim_id=c.get("claim_id") or f"C-{i + 1:03d}", kind=c.get("kind", "business"), type=ctype, subject=c.get("subject", "company"),
                       text=c["text"], value=c.get("value"), unit=c.get("unit"), as_of=c.get("as_of"),
                       critical=bool(c.get("critical", ctype in inp.critical_claims)), span=Span(**sp), slide=c.get("slide") or pg.get("slide") or pg["page"],
                       operational=bool(c.get("operational", ctype in ("locations", "fleet_size", "warehouse_area", "headcount", "certification", "facility"))))
            out.claims.append(cl)
        return out


AGENT = DeckIntake()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
