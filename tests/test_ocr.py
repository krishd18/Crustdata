"""OCR for PDF pages without a usable text layer (no network: the OCR engine is faked)."""
import io

import pytest

from app import ingest, ocr

SCANNED = open("samples/stockarea_scanned.pdf", "rb").read()   # one image-only page
TEXT_PDF = open("samples/stockarea_teaser.pdf", "rb").read()   # a real text layer


@pytest.fixture
def fake_ocr(monkeypatch):
    seen = []

    def engine(jpeg):
        assert jpeg[:2] == b"\xff\xd8"  # a rendered JPEG page is what gets sent
        seen.append(len(jpeg))
        return "A lean team of 60 employees runs operations across India.", {"prompt_tokens": 2000, "completion_tokens": 20}

    monkeypatch.setattr(ocr, "provider", lambda: "mantle")
    monkeypatch.setattr(ocr, "describe", lambda: "fake vision model")
    monkeypatch.setattr(ocr, "_mantle", engine)
    return seen


def test_scanned_pdf_is_read_by_ocr(fake_ocr):
    p = ingest.parse_bytes(SCANNED, "scan.pdf")
    assert "[page 1, OCR]" in p.text and "60 employees" in p.text
    assert p.ocr["pages"] == [1] and p.ocr["input_tokens"] == 2000
    assert any("read by OCR" in w for w in p.warnings)
    assert len(fake_ocr) == 1


def test_pages_with_a_text_layer_are_not_ocrd(fake_ocr):
    p = ingest.parse_bytes(TEXT_PDF, "teaser.pdf")
    assert fake_ocr == [] and p.ocr is None and "[page 1]" in p.text


def test_ocr_can_be_skipped_for_public_documents(fake_ocr):
    p = ingest.parse_pdf(SCANNED, "doc.pdf", ocr=False)
    assert fake_ocr == [] and p.text == ""


def test_without_an_ocr_engine_the_page_says_so(monkeypatch):
    monkeypatch.setattr(ocr, "provider", lambda: "off")
    p = ingest.parse_bytes(SCANNED, "scan.pdf")
    assert p.text == "" and any("OCR is off" in w for w in p.warnings)


def test_a_failing_page_is_reported_not_fatal(monkeypatch):
    monkeypatch.setattr(ocr, "provider", lambda: "mantle")

    def boom(jpeg):
        raise RuntimeError("OCR model HTTP 500")
    monkeypatch.setattr(ocr, "_mantle", boom)
    p = ingest.parse_bytes(SCANNED, "scan.pdf")
    assert any("OCR failed" in w for w in p.warnings)


def test_needs_ocr_spots_empty_title_only_and_glyph_soup_pages():
    assert ocr.needs_ocr("") and ocr.needs_ocr("Advisors")
    assert ocr.needs_ocr("A c c u r a c y > r o b u s t n e s s R e s e a r c h f r i e n d l y U i P o r t a b i l i t y")
    assert not ocr.needs_ocr("Stockarea is a Chennai-registered warehousing and fulfilment network, est. 2019. "
                             "A lean team of 60 employees runs operations across India.")
