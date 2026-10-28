"""Grounded or rejected (ADR-0002): every extracted value must be found on the page.

For PDFs with a text layer the quote (or else the value) is searched in that page's words:
found as consecutive words -> "exact" with a box to highlight; found inside the page text ->
"fuzzy"; not found -> the value is cleared and flagged. Scans and photos have no text layer,
so values are kept as "model_only" and must still pass the math checks.
"""

from typing import Any

from rapidfuzz import fuzz

from .normalize import compact

FUZZY_MIN = 92


def _locate(words: list[dict], needle: str) -> list[float] | None:
    target = compact(needle)
    if not target:
        return None
    tokens = [compact(w["t"]) for w in words]
    for start in range(len(words)):
        joined = ""
        for end in range(start, min(start + 12, len(words))):
            joined += tokens[end]
            if joined == target:
                boxes = [w["b"] for w in words[start : end + 1]]
                return [
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                ]
            if not target.startswith(joined):
                break
    return None


def ground(value: Any, page: int | None, quote: str | None, pages: list[list[dict]]) -> dict:
    """Evidence for one value. ``pages`` holds each page's words (empty list = no text layer)."""
    if value in (None, ""):
        return {"value": None, "grounding": "absent"}
    has_text = any(pages)
    if not has_text:
        return {"value": value, "page": page, "quote": quote, "grounding": "model_only"}
    order = [page - 1] if page and 0 < page <= len(pages) else []
    order += [i for i in range(len(pages)) if i not in order]
    for needle in [n for n in (quote, str(value)) if n]:
        for index in order:
            box = _locate(pages[index], needle)
            if box:
                return {
                    "value": value,
                    "page": index + 1,
                    "quote": needle,
                    "box": box,
                    "grounding": "exact",
                }
    for index in order:
        text = compact("".join(w["t"] for w in pages[index]))
        for needle in [n for n in (quote, str(value)) if n]:
            if len(compact(needle)) >= 4 and fuzz.partial_ratio(compact(needle), text) >= FUZZY_MIN:
                return {"value": value, "page": index + 1, "quote": needle, "grounding": "fuzzy"}
    return {"value": None, "rejected": value, "quote": quote, "grounding": "none"}
