"""Plain text out of HTML snippets, trimmed for an excerpt."""

from __future__ import annotations

from html.parser import HTMLParser

EXCERPT_LIMIT = 300


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Paragraph breaks in HN post text: keep the words apart.
        if tag in ("p", "br"):
            self.parts.append(" ")


def plain_text(html: str) -> str:
    """The text of an HTML snippet, whitespace collapsed."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return squash("".join(parser.parts))


def squash(text: str) -> str:
    return " ".join(text.split())


def excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """text cut at a word boundary to at most limit characters, with an ellipsis when cut."""
    text = squash(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-") + "…"
