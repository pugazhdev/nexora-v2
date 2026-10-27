"""Verify that an LLM-extracted quote really appears in the fetched page text."""

import re
import unicodedata

_RUPEE = "₹"
_MARKER = re.compile(r"(?<![a-z])(?:rs\.?|inr)(?![a-z])")


def normalise_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = _MARKER.sub(_RUPEE, s)
    return re.sub(_RUPEE + r"\s+", _RUPEE, s)


def _squash(s: str) -> str:
    # Inline text can fuse or split ("Price12", "2 . 10"), so drop whitespace, except between
    # two digits: separate cells must never fuse into a fake number ("2 100" != "2100").
    return re.sub(
        r"(?P<keep>(?<=\d)\s+(?=\d))|\s+", lambda m: " " if m.group("keep") else "", normalise_text(s)
    )


def quote_in_page(quote: str | None, page_text: str) -> bool:
    q = _squash(quote or "")
    if not q:
        return False
    page = _squash(page_text)
    start = page.find(q)
    while start != -1:
        end = start + len(q)
        before = page[start - 1] if start else ""
        after = page[end:end + 2]
        # a numeric quote must not match the middle of a longer number ("2.1" in "2.10")
        glued_left = q[0].isdigit() and before.isdigit()
        glued_right = q[-1].isdigit() and (
            after[:1].isdigit() or (after[:1] in ".," and after[1:2].isdigit())
        )
        if not (glued_left or glued_right):
            return True
        start = page.find(q, start + 1)
    return False
