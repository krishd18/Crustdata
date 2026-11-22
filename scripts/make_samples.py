"""Build demo inputs from samples/stockarea.json: a PDF teaser, a PPTX deck and a JSON request.

    python scripts/make_samples.py
"""
import json
from pathlib import Path

from pptx import Presentation
from pptx.util import Pt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
S = json.loads((ROOT / "samples" / "stockarea.json").read_text(encoding="utf-8"))
lines = [ln.strip() for ln in S["teaser"].splitlines() if ln.strip()]
claims = [ln.lstrip("- ").strip() for ln in lines if ln.startswith("- ") and not ln.endswith("?")]
questions = [ln.lstrip("- ").strip() for ln in lines if ln.endswith("?")]
intro = next(ln for ln in lines if ln.startswith("Stockarea is"))

# PDF: two pages, like a short teaser
styles = getSampleStyleSheet()
doc = SimpleDocTemplate(str(ROOT / "samples" / "stockarea_teaser.pdf"), pagesize=A4, title="Stockarea teaser (synthetic)")
story = [Paragraph("Stockarea: confidential teaser", styles["Title"]),
         Paragraph("<i>Synthetic test document. Not issued by the company.</i>", styles["Normal"]), Spacer(1, 12),
         Paragraph(intro, styles["BodyText"]), Spacer(1, 12)]
story += [Paragraph("• " + c, styles["BodyText"]) for c in claims[:5]]
story += [Spacer(1, 400)] + [Paragraph("• " + c, styles["BodyText"]) for c in claims[5:]]
doc.build(story)

# PPTX: title slide, a bullet slide, a table slide; analyst question in the notes
prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[0])
s.shapes.title.text = "Stockarea"
s.placeholders[1].text = "Synthetic test deck. Not issued by the company.\n" + intro
s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "At a glance"
tf = s.placeholders[1].text_frame
tf.text = claims[0]
for c in claims[1:5]:
    tf.add_paragraph().text = c
for p in tf.paragraphs:
    p.font.size = Pt(18)
s = prs.slides.add_slide(prs.slide_layouts[5])
s.shapes.title.text = "Backers, customers and roadmap"
from pptx.util import Inches  # noqa: E402
t = s.shapes.add_table(len(claims) - 5, 1, Inches(0.5), Inches(1.6), Inches(9), Inches(3)).table
for i, c in enumerate(claims[5:]):
    t.cell(i, 0).text = c
s.notes_slide.notes_text_frame.text = " ".join(questions)
prs.save(ROOT / "samples" / "stockarea_deck.pptx")

# JSON request in the shape the adapter expects (until the kickoff kit's format is known)
(ROOT / "samples" / "request_example.json").write_text(json.dumps({
    "id": "demo-1",
    "company": {"name": S["name"], "domain": S["domain"], "city": S["city"]},
    "document": {"text": S["teaser"]},
}, indent=2), encoding="utf-8")
# An image-only copy of the teaser (no text layer), to show OCR at work.
import pypdfium2 as pdfium  # noqa: E402

_page = pdfium.PdfDocument(str(ROOT / "samples" / "stockarea_teaser.pdf"))[0]
_page.render(scale=2).to_pil().convert("RGB").save(ROOT / "samples" / "stockarea_scanned.pdf", "PDF", resolution=144)

print("wrote samples/stockarea_teaser.pdf, samples/stockarea_scanned.pdf, samples/stockarea_deck.pptx,"
      " samples/request_example.json")
