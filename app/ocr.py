"""OCR for PDF pages that have no usable text layer (scans, image-only slides).

Pages are rendered with pypdfium2 (already installed with pdfplumber) and read by:
  mantle     the Bedrock Mantle vision model (BEDROCK_MANTLE_MODEL, default
             qwen.qwen3-vl-235b-a22b-instruct), about 5-7 s a page, run 4 at a time;
  tesseract  local Tesseract via pytesseract, if both are installed.
SECONDLOOK_OCR = auto (default: mantle if configured, else tesseract if
installed, else off) | mantle | tesseract | off.  OCR_MAX_PAGES caps pages per document (25).

Which pages: no text, only a title (under 80 characters), or glyph soup where most
"words" are single letters ("A c c u r a c y"), as designed decks often produce.
The model is told to transcribe, not summarise; the text is used like any other
extracted text, so claims from it still go through the quote check.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger("secondlook.ocr")

PROMPT = ("Transcribe all the text on this page exactly as written, line by line, top to bottom, including "
          "text inside charts, tables, logos' captions and labels. Keep numbers and symbols exactly. "
          "Do not describe images, summarise, translate or add anything. If there is no text, reply with nothing.")


def _tesseract_ok() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def provider() -> str:
    want = (os.getenv("SECONDLOOK_OCR") or "auto").lower()
    if want == "off":
        return "off"
    mantle = bool(os.getenv("AWS_BEARER_TOKEN_BEDROCK") and os.getenv("BEDROCK_MANTLE_URL"))
    if want == "mantle":
        return "mantle" if mantle else "off"
    if want == "tesseract":
        return "tesseract" if _tesseract_ok() else "off"
    return "mantle" if mantle else ("tesseract" if _tesseract_ok() else "off")


def describe() -> str:
    p = provider()
    if p == "mantle":
        return f"{os.getenv('BEDROCK_MANTLE_MODEL', 'qwen.qwen3-vl-235b-a22b-instruct')} (Amazon Bedrock Mantle)"
    return {"tesseract": "Tesseract (local)", "off": "off"}[p]


def needs_ocr(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 80:
        return True
    words = re.findall(r"[A-Za-z]+", t)
    return len(words) > 20 and sum(len(w) == 1 for w in words) / len(words) > 0.45  # "A c c u r a c y"


def render(data: bytes, page_numbers: list[int], scale: float = 2.0) -> dict[int, bytes]:
    """Page number (1-based) -> JPEG bytes. pypdfium2 isn't thread-safe, so this runs in one thread."""
    import pypdfium2 as pdfium

    out = {}
    pdf = pdfium.PdfDocument(data)
    try:
        for n in page_numbers:
            img = pdf[n - 1].render(scale=scale).to_pil().convert("RGB")
            if max(img.size) > 2200:
                img.thumbnail((2200, 2200))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=82)
            out[n] = buf.getvalue()
    finally:
        pdf.close()
    return out


def _mantle(jpeg: bytes) -> tuple[str, dict]:
    url = os.environ["BEDROCK_MANTLE_URL"].rstrip("/") + "/chat/completions"
    body = {"model": os.getenv("BEDROCK_MANTLE_MODEL", "qwen.qwen3-vl-235b-a22b-instruct"),
            "temperature": 0, "max_tokens": 4000,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}]}]}
    r = httpx.post(url, json=body, headers={"authorization": f"Bearer {os.environ['AWS_BEARER_TOKEN_BEDROCK']}"},
                   timeout=httpx.Timeout(float(os.getenv("OCR_TIMEOUT") or 90), connect=20))
    if r.status_code != 200:
        raise RuntimeError(f"OCR model HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    text = ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return re.sub(r"^```\w*\n?|```$", "", text.strip()).strip(), j.get("usage") or {}


def _tesseract(jpeg: bytes) -> tuple[str, dict]:
    import pytesseract
    from PIL import Image

    return pytesseract.image_to_string(Image.open(io.BytesIO(jpeg))).strip(), {}


def ocr_pages(data: bytes, page_numbers: list[int], stop=None) -> tuple[dict[int, str], dict]:
    """OCR the given pages. Returns ({page: text}, meta). Never raises for one bad page."""
    from .cancel import check

    p = provider()
    meta = {"engine": describe(), "pages": [], "failed": [], "seconds": 0.0, "input_tokens": 0, "output_tokens": 0}
    if p == "off" or not page_numbers:
        return {}, meta
    cap = int(os.getenv("OCR_MAX_PAGES") or 25)
    if len(page_numbers) > cap:
        meta["skipped"] = page_numbers[cap:]
        page_numbers = page_numbers[:cap]
    t0 = time.time()
    images = render(data, page_numbers)
    fn = _mantle if p == "mantle" else _tesseract
    out: dict[int, str] = {}

    def one(n):
        check(stop)
        return n, fn(images[n])

    with ThreadPoolExecutor(4 if p == "mantle" else 1) as pool:
        futs = [pool.submit(one, n) for n in images]
        for f in futs:
            try:
                n, (text, usage) = f.result()
            except Exception as e:
                if type(e).__name__ == "Cancelled":
                    raise
                log.warning("OCR failed on a page: %s", e)
                meta["failed"].append(str(e)[:120])
                continue
            if text:
                out[n] = text
                meta["pages"].append(n)
            meta["input_tokens"] += int(usage.get("prompt_tokens") or 0)
            meta["output_tokens"] += int(usage.get("completion_tokens") or 0)
    meta["pages"].sort()
    meta["seconds"] = round(time.time() - t0, 1)
    return out, meta
