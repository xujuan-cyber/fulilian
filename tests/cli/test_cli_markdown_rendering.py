from io import StringIO

from rich.console import Console
from rich.markdown import Markdown

from cli import _render_final_assistant_content


def _render_to_text(renderable) -> str:
    buf = StringIO()
    Console(file=buf, width=80, force_terminal=False, color_system=None).print(renderable)
    return buf.getvalue()


def test_final_assistant_content_uses_markdown_renderable():
    renderable = _render_final_assistant_content("# Title\n\n- one\n- two")

    assert isinstance(renderable, Markdown)
    output = _render_to_text(renderable)
    assert "Title" in output
    assert "one" in output
    assert "two" in output




def test_final_assistant_content_keeps_non_path_markdown_escapes():
    renderable = _render_final_assistant_content(r"1\. Not an ordered list")

    output = _render_to_text(renderable)
    assert "1. Not an ordered list" in output
    assert r"1\." not in output






def test_strip_mode_preserves_lists():
    renderable = _render_final_assistant_content(
        "**Formatting**\n- Ran prettier\n- Files changed\n- Verified clean",
        mode="strip",
    )

    output = _render_to_text(renderable)
    assert "- Ran prettier" in output
    assert "- Files changed" in output
    assert "- Verified clean" in output
    assert "**" not in output




def test_strip_mode_preserves_blockquotes():
    renderable = _render_final_assistant_content(
        "> This is quoted text\n> Another quoted line",
        mode="strip",
    )

    output = _render_to_text(renderable)
    assert "> This is quoted" in output
    assert "> Another quoted" in output






def test_strip_mode_preserves_cron_asterisks_in_plain_text():
    renderable = _render_final_assistant_content("* * * * *", mode="strip")

    output = _render_to_text(renderable)
    assert "* * * * *" in output

    # Still treat the canonical 3-asterisk Markdown horizontal rule as decoration.
    renderable = _render_final_assistant_content("* * *", mode="strip")
    output = _render_to_text(renderable)
    assert "* * *" not in output




def test_strip_mode_preserves_intraword_underscores_in_snake_case_identifiers():
    renderable = _render_final_assistant_content(
        "Let me look at test_case_with_underscores and SOME_CONST "
        "then /tmp/snake_case_dir/file_with_name.py",
        mode="strip",
    )

    output = _render_to_text(renderable)
    assert "test_case_with_underscores" in output
    assert "SOME_CONST" in output
    assert "snake_case_dir" in output
    assert "file_with_name" in output


def test_strip_mode_still_strips_boundary_underscore_emphasis():
    renderable = _render_final_assistant_content(
        "say _hi_ and __bold__ now",
        mode="strip",
    )

    output = _render_to_text(renderable)
    assert "say hi and bold now" in output


# ── claude markdown theme (fulilian_cli/markdown_theme.py) ───────────────


class TestClaudeMarkdownThemeRendering:
    """The claude skin's Rich markdown palette: flush-left h1, flush code
    blocks, and the exact Claude Code palette values reaching the terminal
    as SGR sequences. Rendered through the real Theme + Markdown subclass,
    asserted on visible text and ANSI attributes — not snapshots."""

    def _render(self, md_text: str, light: bool = False) -> str:
        from fulilian_cli.markdown_theme import (
            FulilianMarkdown,
            claude_markdown_theme,
        )

        buf = StringIO()
        console = Console(
            file=buf,
            width=80,
            force_terminal=True,
            color_system="truecolor",
            theme=claude_markdown_theme(light),
        )
        console.print(FulilianMarkdown(md_text))
        return buf.getvalue()

    def test_h1_is_flush_left_not_centered(self):
        out = self._render("# Head One\n\nbody")
        line = next(ln for ln in out.splitlines() if "Head One" in ln)
        # Rich's default h1 centers within the width (~35 leading columns);
        # Claude Code keeps every heading flush-left.
        assert not line.startswith(" " * 8), repr(line)

    def test_h1_uses_accent_blue_bold_and_no_underline(self):
        out = self._render("# Head One")
        line = next(ln for ln in out.splitlines() if "Head One" in ln)
        assert "\x1b[1;38;2;51;154;240m" in line  # bold #339AF0
        assert "4;38" not in line  # no underline

    def test_light_theme_darkens_the_accent(self):
        out = self._render("# Head One", light=True)
        assert "30;122;212" in out  # #1E7AD4 as rgb triple

    def test_inline_code_gets_dark_chip_background(self):
        out = self._render("use `npm run` here")
        assert "48;2;55;55;55" in out  # bg #373737

    def test_code_block_is_flush_left(self):
        out = self._render("```python\nprint('hi')\n```")
        code_line = next(ln for ln in out.splitlines() if "print" in ln)
        assert not code_line.startswith(" "), repr(code_line)

    def test_links_use_cc_link_color(self):
        out = self._render("see [docs](https://example.com)")
        assert "177;185;249" in out  # #b1b9f9 as rgb triple

    def test_theme_covers_the_cc_markdown_roles(self):
        from fulilian_cli.markdown_theme import claude_markdown_theme

        theme = claude_markdown_theme(False)
        for key in (
            "markdown.h1",
            "markdown.h6",
            "markdown.paragraph",
            "markdown.code",
            "markdown.code_block",
            "markdown.block_quote",
            "markdown.item.bullet",
            "markdown.item.number",
            "markdown.hr",
            "markdown.link",
            "markdown.table.header",
            "markdown.table.border",
        ):
            assert key in theme.styles, key

    def test_theme_is_cached_per_polarity(self):
        from fulilian_cli.markdown_theme import claude_markdown_theme

        assert claude_markdown_theme(False) is claude_markdown_theme(False)
        assert claude_markdown_theme(True) is claude_markdown_theme(True)
        assert claude_markdown_theme(False) is not claude_markdown_theme(True)
