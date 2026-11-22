"""Render docs/diagrams/*.html to high-resolution JPEGs with headless Chrome or Edge.

    python scripts/render_diagrams.py

Writes docs/technical-architecture.jpg and docs/business-architecture.jpg (2x scale).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = {  # source page -> (output, CSS height of the canvas)
    "technical.html": ("technical-architecture.jpg", 1225),
    "business.html": ("business-architecture.jpg", 1320),
}
CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "msedge",
]


def browser() -> str:
    for c in CANDIDATES:
        if os.path.exists(c) or shutil.which(c):
            return c
    sys.exit("No Chrome/Edge found to render the diagrams.")


def main() -> None:
    exe = browser()
    only = sys.argv[1:]  # optional: render just these sources, e.g. technical.html
    for src, (out, height) in DIAGRAMS.items():
        if only and src not in only:
            continue
        page = (ROOT / "docs" / "diagrams" / src).resolve()
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "shot.png"
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={tmp}", "--force-device-scale-factor=2",
                            f"--window-size=2000,{height}", "--virtual-time-budget=3000",
                            f"--screenshot={png}", page.as_uri()],
                           check=True, capture_output=True, timeout=120)
            img = Image.open(png).convert("RGB")
            img.save(ROOT / "docs" / out, "JPEG", quality=93, optimize=True, progressive=True)
            print(f"docs/{out}: {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
