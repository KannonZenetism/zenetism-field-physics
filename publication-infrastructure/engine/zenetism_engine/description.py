"""Read-only extraction of governed description structure from rendered HTML."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _DescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.strong_parts: list[str] = []
        self._strong_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "strong":
            self._strong_depth += 1
        if tag in {"p", "li", "br"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "strong" and self._strong_depth:
            self._strong_depth -= 1
        if tag in {"p", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._strong_depth:
            self.strong_parts.append(data)


def description_text(rendered_html: str | None) -> str | None:
    if not rendered_html:
        return None
    parser = _DescriptionParser()
    parser.feed(rendered_html)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip() or None


def corpus_classification(rendered_html: str | None) -> str | None:
    # The standard fixes this as one paragraph, so preserve the exact class value
    # rather than trying to infer its boundary from flattened prose.
    raw_match = re.search(
        r"<strong>\s*Document class:\s*</strong>\s*(.*?)</p>",
        rendered_html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if raw_match:
        parser = _DescriptionParser()
        parser.feed(raw_match.group(1))
        return re.sub(r"\s+", " ", "".join(parser.parts)).strip().rstrip(".") or None
    return None


def infer_description_form(rendered_html: str | None) -> str | None:
    if not rendered_html:
        return None
    parser = _DescriptionParser()
    parser.feed(rendered_html)
    labels = {re.sub(r"\s+", " ", item).strip() for item in parser.strong_parts}
    if "Contents:" in labels:
        return "Series"
    if labels.intersection({"Supersedes:", "Companion to:", "Part of:"}):
        return "Standard"
    text = description_text(rendered_html) or ""
    word_count = len(re.findall(r"\b[^\W_]+(?:[-'][^\W_]+)*\b", text, flags=re.UNICODE))
    return "Short" if word_count < 120 else "Standard"
