"""HTML to visible text (stdlib only). Output is untrusted data."""

import re
from html.parser import HTMLParser

MAX_JSONLD = 15_000
SKIP = {"script", "style", "nav", "footer", "noscript", "template", "svg"}
BLOCK = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol",
    "section", "article", "header", "dt", "dd", "title", "td", "th",
}  # fmt: skip


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.jsonld: list[str] = []
        self._skip = 0
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self._in_jsonld = True
        if tag in SKIP:
            self._skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_jsonld = False
        if tag in SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_jsonld:
            if data.strip():
                self.jsonld.append(data.strip())
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Extractor()
    p.feed(html)
    p.close()
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).split("\n"))
    # JSON-LD first (capped) so a later total-length cap trims visible text, not structured data
    ld = [chr(10).join(p.jsonld)[:MAX_JSONLD]] if p.jsonld else []
    return chr(10).join(ld + [ln for ln in lines if ln])
