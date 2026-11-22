"""HTML -> readable text, stdlib only. /web/enrich/live returns raw page HTML."""
from __future__ import annotations

import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "svg", "template", "head", "iframe"}
BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "tr", "td", "th",
         "header", "footer", "ul", "ol", "dd", "dt", "blockquote", "figcaption", "span"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def to_text(content: str) -> str:
    if not content or "<" not in content[:2000]:
        return content or ""
    p = _Text()
    try:
        p.feed(content)
    except Exception:
        return re.sub(r"<[^>]+>", " ", content)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.out).split("\n"))
    # Short fragments stay on their own lines so UI labels never merge into sentences.
    return "\n".join(ln for ln in lines if ln)
