"""Read the target's material, whatever shape it arrives in.

    request JSON / text   -> parse_request()   (the kickoff-kit format; see REQUEST_KEYS)
    PDF deck / teaser     -> pypdf, then pdfplumber if pypdf finds little text, then OCR
                             (app/ocr.py) for pages with no usable text layer
    PowerPoint deck       -> python-pptx (slide text, tables, speaker notes)
    company website URL   -> Crustdata /web/enrich/live, HTML -> text
    pasted text           -> used as is

Everything returns a Parsed(text, kind, ...) so the rest of the pipeline
never cares where the words came from.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field

from .htmltext import to_text

log = logging.getLogger("secondlook.ingest")


@dataclass
class Parsed:
    text: str
    kind: str                      # pdf | pptx | url | text | json
    name: str | None = None        # file name or URL
    pages: int | None = None       # pages or slides
    warnings: list[str] = field(default_factory=list)
    ocr: dict | None = None        # pages read by OCR, engine, seconds, tokens

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chars"] = len(self.text)
        d.pop("text")
        return d


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def parse_bytes(data: bytes, filename: str = "", content_type: str = "", *, ocr: bool = True, stop=None) -> Parsed:
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-" or "pdf" in content_type:
        return parse_pdf(data, filename, ocr=ocr, stop=stop)
    if name.endswith(".pptx") or "presentationml" in content_type or (data[:2] == b"PK" and b"ppt/" in data[:4000]):
        return parse_pptx(data, filename)
    if name.endswith(".ppt"):
        return Parsed("", "pptx", filename, warnings=["Old binary .ppt is not supported; save it as .pptx or PDF."])
    text = _decode(data)
    if name.endswith(".json") or text.lstrip().startswith(("{", "[")):
        try:
            obj = json.loads(text)
            req = parse_request(obj)
            return Parsed(req.document or "", "json", filename, warnings=req.warnings)
        except ValueError:
            pass
    if name.endswith((".html", ".htm")):
        return Parsed(to_text(text), "text", filename)
    return Parsed(text.strip(), "text", filename)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def parse_pdf(data: bytes, filename: str = "", *, ocr: bool = True, stop=None) -> Parsed:
    warnings: list[str] = []
    pages: list[str] = []
    n = None
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return Parsed("", "pdf", filename, warnings=["The PDF is password-protected."])
        n = len(reader.pages)
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:
        warnings.append(f"pypdf could not read it ({type(e).__name__}); trying pdfplumber.")

    # pypdf can return glyph soup or nothing on designed decks; pdfplumber's
    # layout-aware extraction often does better there.
    if sum(len(p.strip()) for p in pages) < 40 * max(1, len(pages)):
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                n = len(pdf.pages)
                alt = [(p.extract_text() or "") for p in pdf.pages]
            if sum(len(p) for p in alt) > sum(len(p) for p in pages):
                pages = alt
        except Exception as e:
            warnings.append(f"pdfplumber failed too ({type(e).__name__}).")

    # OCR: pages with no text layer, only a title, or glyph soup (scans, image-only slides)
    from . import ocr as _ocr

    if n is None:
        try:
            import pypdfium2 as pdfium
            n = len(pdfium.PdfDocument(data))
        except Exception:
            n = None
    if n and len(pages) < n:
        pages += [""] * (n - len(pages))
    todo = [i for i, t in enumerate(pages, 1) if _ocr.needs_ocr(t)]
    ocr_meta, labels = None, {}
    if todo and ocr and _ocr.provider() != "off":
        try:
            got, ocr_meta = _ocr.ocr_pages(data, todo, stop=stop)
        except Exception as e:
            if type(e).__name__ == "Cancelled":
                raise
            got, ocr_meta = {}, {"engine": _ocr.describe(), "pages": [], "failed": [str(e)[:160]]}
        for i, t in got.items():
            if len(t.strip()) > len(pages[i - 1].strip()):  # OCR keeps the title too, so it replaces the page
                pages[i - 1], labels[i] = t, ", OCR"
        if ocr_meta.get("pages"):
            warnings.append(f"{len(ocr_meta['pages'])} of {n} pages had no usable text layer and were read by OCR "
                            f"({ocr_meta['engine']}, {ocr_meta['seconds']}s).")
        if ocr_meta.get("failed"):
            warnings.append(f"OCR failed on {len(ocr_meta['failed'])} page(s): {ocr_meta['failed'][0]}")
        if ocr_meta.get("skipped"):
            warnings.append(f"{len(ocr_meta['skipped'])} more pages need OCR but are over the OCR_MAX_PAGES limit.")
    elif todo and ocr:
        warnings.append(f"{len(todo)} page(s) have no usable text layer and OCR is off "
                        "(set AWS_BEARER_TOKEN_BEDROCK + BEDROCK_MANTLE_URL, or install Tesseract).")

    text = "\n\n".join(f"[page {i}{labels.get(i, '')}]\n{t.strip()}" for i, t in enumerate(pages, 1) if t.strip())
    if not text:
        warnings.append("No text found, even with OCR." if ocr and _ocr.provider() != "off"
                        else "No text layer found. This looks like a scanned/image PDF and OCR is off.")
    return Parsed(_clean(text), "pdf", filename, pages=n, warnings=warnings, ocr=ocr_meta)


def parse_pptx(data: bytes, filename: str = "") -> Parsed:
    from pptx import Presentation

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        return Parsed("", "pptx", filename, warnings=[f"Could not open the deck ({type(e).__name__})."])
    out = []
    for i, slide in enumerate(prs.slides, 1):
        lines: list[str] = []
        for shape in _walk(slide.shapes):
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(r.text for r in para.runs).strip()
                    if t:
                        lines.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        lines.append(" | ".join(cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            if notes:
                lines.append(f"(speaker notes) {notes}")
        if lines:
            out.append(f"[slide {i}]\n" + "\n".join(lines))
    text = "\n\n".join(out)
    warnings = [] if text else ["The deck has no text (images only?); OCR is not enabled."]
    return Parsed(_clean(text), "pptx", filename, pages=len(prs.slides), warnings=warnings)


def _walk(shapes):
    for s in shapes:
        yield s
        if s.shape_type == 6 and hasattr(s, "shapes"):  # group shape
            yield from _walk(s.shapes)


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
def parse_url(url: str, crust) -> Parsed:
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    if re.search(r"\.(pdf|pptx)(\?|$)", url, re.I):  # a link straight to a deck file
        import httpx

        r = httpx.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        return parse_bytes(r.content, url.split("?")[0].rsplit("/", 1)[-1], r.headers.get("content-type", ""))
    pages, _ = crust.web_fetch([url])
    if not pages:
        return Parsed("", "url", url, warnings=["The page could not be fetched."])
    return Parsed(to_text(pages[0].get("content") or ""), "url", url, pages=1)


# ---------------------------------------------------------------------------
# The kickoff kit's request format
# ---------------------------------------------------------------------------
# The exact schema wasn't available when this was written, so the adapter
# accepts the common spellings. Once the real format is known, add its keys
# here (first match wins) and the rest of the app needs no change.
REQUEST_KEYS = {
    "name": ["company_name", "company", "name", "target", "target_company", "counterparty", "organization"],
    "domain": ["domain", "company_domain", "website", "company_website", "url", "homepage"],
    "city": ["city", "location", "hq", "headquarters", "hq_city"],
    "document": ["teaser", "deck", "deck_text", "document", "document_text", "text", "content", "input",
                 "pitch", "capability_statement", "memo", "body"],
    "document_url": ["document_url", "deck_url", "teaser_url", "file_url", "pdf_url"],
    "file_b64": ["file_base64", "document_base64", "deck_base64", "content_base64", "data"],
    "file_name": ["file_name", "filename", "document_name", "deck_name"],
    "claims": ["claims", "statements", "assertions"],
    "questions": ["questions", "analyst_questions", "queries", "premises"],
}


@dataclass
class Request:
    name: str | None = None
    domain: str | None = None
    city: str | None = None
    document: str | None = None
    document_url: str | None = None
    file_b64: str | None = None
    file_name: str | None = None
    id: str | None = None
    warnings: list[str] = field(default_factory=list)


def _get(obj: dict, keys: list[str]):
    low = {str(k).lower(): v for k, v in obj.items()}
    for k in keys:
        if k in low and low[k] not in (None, "", [], {}):
            return low[k]
    return None


def parse_request(obj) -> Request:
    """Normalise one request (dict or JSON string or plain text) to a Request."""
    if isinstance(obj, (bytes, str)):
        s = obj.decode() if isinstance(obj, bytes) else obj
        try:
            obj = json.loads(s)
        except ValueError:
            return Request(document=s)
    if isinstance(obj, list):
        raise ValueError("expected one request; use parse_requests() for a list")
    if not isinstance(obj, dict):
        raise ValueError("request must be a JSON object")

    # Unwrap common envelopes: {"request": {...}}, {"input": {...}}, {"data": {...}}
    for wrap in ("request", "input", "payload", "data", "task"):
        inner = obj.get(wrap)
        if isinstance(inner, dict) and len(obj) <= 3:
            obj = {**{k: v for k, v in obj.items() if k != wrap}, **inner}

    r = Request(id=str(obj.get("id") or obj.get("request_id") or "") or None)
    company = _get(obj, REQUEST_KEYS["name"])
    if isinstance(company, dict):  # {"company": {"name": .., "domain": ..}}
        r.name = _get(company, ["name", "company_name", "legal_name"])
        r.domain = _get(company, REQUEST_KEYS["domain"])
        r.city = _get(company, REQUEST_KEYS["city"])
    else:
        r.name = company
    r.domain = r.domain or _get(obj, REQUEST_KEYS["domain"])
    r.city = r.city or _get(obj, REQUEST_KEYS["city"])
    if isinstance(r.city, dict):
        r.city = r.city.get("city") or r.city.get("name")

    doc = _get(obj, REQUEST_KEYS["document"])
    if isinstance(doc, dict):  # {"document": {"text": ..} | {"url": ..} | {"base64": ..}}
        r.document_url = _get(doc, ["url", "href", "link"])
        r.file_b64 = _get(doc, ["base64", "content_base64", "data"])
        r.file_name = _get(doc, ["name", "filename", "file_name"])
        doc = _get(doc, ["text", "content", "body"])
    if isinstance(doc, list):
        doc = "\n".join(str(x) for x in doc)
    claims = _get(obj, REQUEST_KEYS["claims"])
    if isinstance(claims, list):
        claims = "\n".join(c if isinstance(c, str) else str(_get(c, ["text", "claim", "statement"]) or "") for c in claims)
    questions = _get(obj, REQUEST_KEYS["questions"])
    if isinstance(questions, list):
        questions = "\n".join(q if str(q).rstrip().endswith("?") else f"{q}?" for q in map(str, questions))
    r.document = "\n\n".join(x for x in [doc, claims, questions] if x) or None
    r.document_url = r.document_url or _get(obj, REQUEST_KEYS["document_url"])
    r.file_b64 = r.file_b64 or _get(obj, REQUEST_KEYS["file_b64"])
    r.file_name = r.file_name or _get(obj, REQUEST_KEYS["file_name"])

    if r.domain:
        r.domain = re.sub(r"^https?://(www\.)?", "", str(r.domain)).split("/")[0].lower()
    if not r.name and r.domain:
        r.name = r.domain.split(".")[0].title()
    if not r.name:
        r.warnings.append("No company name found in the request.")
    if not (r.document or r.document_url or r.file_b64):
        r.warnings.append("No document in the request; the company's own pages will be checked.")
    return r


def parse_requests(obj) -> list[Request]:
    if isinstance(obj, (bytes, str)):
        obj = json.loads(obj)
    if isinstance(obj, dict):
        for k in ("requests", "items", "cases", "tasks", "companies"):
            if isinstance(obj.get(k), list):
                return [parse_request(x) for x in obj[k]]
        return [parse_request(obj)]
    return [parse_request(x) for x in obj]


def resolve_document(req: Request, crust=None) -> Parsed:
    """Turn whatever the request carried into text."""
    parts, warnings, kind, name, pages, ocr = [], list(req.warnings), "text", None, None, None
    if req.file_b64:
        try:
            p = parse_bytes(base64.b64decode(req.file_b64), req.file_name or "", stop=getattr(crust, "cancel", None))
            parts.append(p.text)
            warnings += p.warnings
            kind, name, pages, ocr = p.kind, p.name, p.pages, p.ocr
        except Exception as e:
            warnings.append(f"Could not decode the attached file ({type(e).__name__}).")
    if req.document_url and crust is not None:
        try:
            p = parse_url(req.document_url, crust)
            parts.append(p.text)
            warnings += p.warnings
            kind, name, pages = p.kind, p.name, p.pages
        except Exception as e:
            warnings.append(f"Could not fetch {req.document_url} ({type(e).__name__}).")
    if req.document:
        parts.append(req.document)
    return Parsed("\n\n".join(p for p in parts if p).strip(), kind, name, pages, warnings, ocr)
