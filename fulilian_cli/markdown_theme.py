"""Claude Code visual grammar for Rich Markdown rendering.

The classic CLI renders final assistant responses through Rich's
``Markdown`` renderable (``display.final_response_markdown: render``).
Rich resolves every block style via ``console.get_style("markdown.<name>")``,
so a ``rich.theme.Theme`` is the primary styling mechanism — no rendering
code changes needed. Two things the Theme cannot express are fixed by a
thin ``Markdown`` subclass:

1. Rich centers ``h1`` headings (``Heading.LEVEL_ALIGN``); Claude Code
   keeps every heading flush-left.
2. ``CodeBlock`` renders with ``Syntax(..., padding=1)``, one leading
   column of background — Claude Code renders code blocks flush-left.

Colors use the default FuLiLian blue accents with neutral gray chips —
the Claude Code *structure* (flush-left headings, flush code blocks,
borderless blocks) without the clay-orange palette. The Theme only
registers ``markdown.*`` keys, so non-markdown Rich output is untouched.
"""

from __future__ import annotations

from functools import lru_cache

from rich.markdown import CodeBlock, Heading, Markdown
from rich.syntax import Syntax
from rich.theme import Theme

__all__ = [
    "FulilianMarkdown",
    "active_markdown_theme",
    "claude_markdown_theme",
    "render_claude_markdown",
]

# Accent colors follow the default FuLiLian palette (2026-10-07 user
# revert of the clay-orange layer): #339AF0 on dark, a darker blue on
# light. The neutral grays/chips stay; only the accent hue changed.
_DARK = {
    "accent": "#339AF0",        # FuLiLian blue — headings h1/h2, list bullets
    "accent_shimmer": "#5DB8F5",
    "text": "#ffffff",
    "inactive": "#999999",      # h4-h6, block quotes
    "subtle": "#505050",        # hr, table borders
    "code_bg": "#373737",       # inline code chip background
    "code_block_bg": "#1e1e1e", # fenced block background (borderless)
    "link": "#b1b9f9",
}

_LIGHT = {
    "accent": "#1E7AD4",        # darker blue for white backgrounds
    "accent_shimmer": "#339AF0",
    "text": "#1a1a1a",
    "inactive": "#666666",
    "subtle": "#afafaf",
    "code_bg": "#e8e8e8",
    "code_block_bg": "#f2f2f2",
    "link": "#3b3f8f",
}


class _LeftAlignedHeading(Heading):
    """Heading element with Claude Code's all-flush-left alignment."""

    LEVEL_ALIGN = {**Heading.LEVEL_ALIGN, "h1": "left"}


class _FlushCodeBlock(CodeBlock):
    """Code block without Syntax's 1-column left padding (copy/paste-safe)."""

    def __rich_console__(self, console, options):
        code = str(self.text).rstrip()
        syntax = Syntax(
            code, self.lexer_name, theme=self.theme, word_wrap=True, padding=0
        )
        yield syntax


class FulilianMarkdown(Markdown):
    """``Markdown`` with Claude Code heading alignment and flush code blocks."""

    elements = {
        **Markdown.elements,
        "heading_open": _LeftAlignedHeading,
        "fence": _FlushCodeBlock,
        "code_block": _FlushCodeBlock,
    }


@lru_cache(maxsize=2)
def claude_markdown_theme(light: bool = False) -> Theme:
    """Build the ``markdown.*`` Theme for the Claude Code palette.

    Cached per polarity — the Theme object is immutable once handed to a
    Console, so callers can share one instance.
    """
    p = _LIGHT if light else _DARK
    return Theme({
        "markdown.h1": f"bold {p['accent']}",
        "markdown.h2": f"bold {p['accent']}",
        "markdown.h3": f"bold {p['text']}",
        "markdown.h4": f"bold {p['inactive']}",
        "markdown.h5": p["inactive"],
        "markdown.h6": f"italic {p['inactive']}",
        "markdown.paragraph": p["text"],
        "markdown.strong": "bold",
        "markdown.em": "italic",
        "markdown.s": "strike",
        "markdown.code": f"bold on {p['code_bg']}",
        "markdown.code_block": f"on {p['code_block_bg']}",
        "markdown.block_quote": f"italic {p['inactive']}",
        "markdown.item": p["text"],
        "markdown.item.bullet": f"bold {p['accent']}",
        "markdown.item.number": f"bold {p['accent']}",
        "markdown.hr": p["subtle"],
        "markdown.link": f"{p['link']} underline",
        "markdown.link_url": p["link"],
        "markdown.table.border": p["subtle"],
        "markdown.table.header": f"bold {p['text']}",
    })


def active_markdown_theme(light: bool = False) -> Theme | None:
    """Theme for the active skin's markdown palette, or ``None`` for stock.

    Only the ``claude`` skin ships a markdown palette — every other skin
    keeps Rich's default markdown look, so this returns ``None`` there and
    the Console is constructed unthemed.
    """
    try:
        from fulilian_cli.skin_engine import get_active_skin
        skin = get_active_skin()
    except Exception:
        return None
    if skin is not None and skin.name == "claude":
        return claude_markdown_theme(light)
    return None


def render_claude_markdown(text: str, *, light: bool = False) -> FulilianMarkdown:
    """Render *text* as Claude Code-styled markdown.

    ``code_theme`` follows terminal polarity so Pygments always produces
    ANSI-only colors that inherit the terminal palette (no fixed hex that
    washes out on light backgrounds).
    """
    return FulilianMarkdown(
        text,
        code_theme="ansi_light" if light else "ansi_dark",
    )
