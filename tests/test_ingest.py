"""Document parser: PDF, PPTX, JSON request, plain text."""
import base64
import io
import json

from app import ingest
from app.extract import _extract_rules

DECK_LINES = ["Acme Warehousing: investor teaser", "A team of 250 employees.", "6 warehouses in Tamil Nadu.",
              "Backed by X Ventures.", "Why did they close Hosur?"]


def make_pdf(lines) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i, ln in enumerate(lines):
        if i == 3:  # put the rest on page 2
            c.showPage()
        c.drawString(72, 800 - 20 * (i % 3), ln)
    c.save()
    return buf.getvalue()


def make_pptx(lines) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = lines[0]
    s1.placeholders[1].text = "\n".join(lines[1:3])
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Investors"
    tbl = s2.shapes.add_table(1, 2, Inches(1), Inches(2), Inches(6), Inches(1)).table
    tbl.cell(0, 0).text, tbl.cell(0, 1).text = "Lead", lines[3]
    s2.notes_slide.notes_text_frame.text = lines[4]
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def types_in(text):
    return {c["type"] for c in _extract_rules(text)}


def test_pdf_text_across_pages():
    p = ingest.parse_bytes(make_pdf(DECK_LINES), "teaser.pdf")
    assert p.kind == "pdf" and p.pages == 2 and "[page 2]" in p.text
    assert {"workforce", "footprint", "investors", "premise"} <= types_in(p.text)


def test_pptx_text_tables_and_notes():
    p = ingest.parse_bytes(make_pptx(DECK_LINES), "deck.pptx")
    assert p.kind == "pptx" and p.pages == 2
    assert "X Ventures" in p.text and "(speaker notes)" in p.text
    assert {"workforce", "footprint", "investors"} <= types_in(p.text)


def test_detects_type_from_bytes_without_extension():
    assert ingest.parse_bytes(make_pdf(DECK_LINES), "upload").kind == "pdf"
    assert ingest.parse_bytes(make_pptx(DECK_LINES), "upload").kind == "pptx"


def test_image_only_pdf_warns_instead_of_failing():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(10, 10, 100, 100)
    c.save()
    p = ingest.parse_bytes(buf.getvalue(), "scan.pdf")
    assert p.text == "" and any("scanned" in w for w in p.warnings)


def test_request_flat_and_nested_shapes():
    r = ingest.parse_request({"company_name": "Stockarea", "website": "https://www.stockarea.io/about",
                              "teaser": "250 employees", "questions": ["Why did they exit Bengaluru"]})
    assert (r.name, r.domain) == ("Stockarea", "stockarea.io")
    assert "250 employees" in r.document and "Why did they exit Bengaluru?" in r.document

    r = ingest.parse_request({"request": {"company": {"name": "Acme", "domain": "acme.in", "city": "Chennai"},
                                          "document": {"text": "6 warehouses in TN"}}})
    assert (r.name, r.domain, r.city, r.document) == ("Acme", "acme.in", "Chennai", "6 warehouses in TN")

    r = ingest.parse_request({"target": "Acme", "claims": [{"text": "250 employees"}, "Backed by Sequoia"]})
    assert "Backed by Sequoia" in r.document and "250 employees" in r.document


def test_request_with_attached_pdf_and_batch():
    b64 = base64.b64encode(make_pdf(DECK_LINES)).decode()
    reqs = ingest.parse_requests({"requests": [{"company": "Acme", "file_base64": b64, "file_name": "t.pdf"},
                                               {"company": "Beta", "deck": "40% YoY"}]})
    assert [r.name for r in reqs] == ["Acme", "Beta"]
    doc = ingest.resolve_document(reqs[0])
    assert doc.kind == "pdf" and "250 employees" in doc.text


def test_request_file_upload_and_plain_text():
    p = ingest.parse_bytes(json.dumps({"company": "Acme", "teaser": "Backed by X Ventures."}).encode(), "req.json")
    assert p.kind == "json" and "X Ventures" in p.text
    assert ingest.parse_request("just pasted text").document == "just pasted text"
    assert ingest.parse_bytes("pasted ₹100 Cr by 2028".encode("utf-8"), "t.txt").text.startswith("pasted")
