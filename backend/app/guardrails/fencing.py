"""Layer 2: treat everything that is NOT the user's own message as untrusted DATA.

Retrieved PDF text and database rows reach the model too. If a document says
"ignore your rules and ...", that is an INDIRECT prompt injection. Defenses:
  1. screen items with the same injection patterns and DROP suspicious ones;
  2. escape '<' and '>' so content can never forge a closing tag and "break out";
  3. wrap each item in a labelled tag the system prompt declares to be data-only.
"""
from dataclasses import dataclass

from app.guardrails.input_guard import looks_like_injection


@dataclass(frozen=True)
class ContextItem:
    id: str                 # "S1".. for retrieved document chunks, "T1".. for MCP/database results
    kind: str               # "document" | "tool_result"
    text: str
    title: str = ""
    url: str = ""
    page: int | None = None


def _escape(text: str) -> str:
    # Only angle brackets matter for tag forgery; '&' is left alone so "P&T" stays readable.
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _attr(value: str) -> str:
    return _escape(value).replace('"', "&quot;")


def build_context(items: list[ContextItem]) -> tuple[str, list[ContextItem], list[str]]:
    """Returns (prompt_text, kept_items, dropped_ids)."""
    kept: list[ContextItem] = []
    dropped: list[str] = []
    blocks: list[str] = []
    for it in items:
        if looks_like_injection(it.text):
            dropped.append(it.id)                      # never shown to the model; caller should log it
            continue
        kept.append(it)
        if it.kind == "document":
            page = f' page="{it.page}"' if it.page else ""
            blocks.append(f'<untrusted_document id="{_attr(it.id)}" source="{_attr(it.title)}"{page}>\n'
                          f"{_escape(it.text)}\n</untrusted_document>")
        else:
            blocks.append(f'<tool_result id="{_attr(it.id)}">\n{_escape(it.text)}\n</tool_result>')
    return "\n\n".join(blocks), kept, dropped
