"""Tests for the Claude-Code-style response grammar in the CLI transcript.

Covers the ``●`` bullet + two-space hanging indent used by
``_emit_stream_text`` / ``_flush_stream``, including the code-fence exemption
that keeps code blocks flush-left (leading whitespace would otherwise pollute
copy/paste — the same class of bug the flush-left Panel padding fixed).
"""

import importlib
import re
import sys
from unittest.mock import MagicMock, patch

_cli_mod = None
_UNSET = object()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text):
    """Strip SGR sequences so assertions read the visible text.

    The bullet is emitted as ``{accent}●{reset} `` — the escape sits between
    the marker and its trailing space — so substring checks must run on the
    stripped form.
    """
    return _ANSI_RE.sub("", str(text))


def _make_cli(tool_progress="all", display_extra=None, verbose=_UNSET):
    """Create a FulilianCLI instance with minimal mocking."""
    global _cli_mod
    _display = {"compact": False, "tool_progress": tool_progress}
    _display.update(display_extra or {})
    _clean_config = {
        "model": {
            "default": "anthropic/claude-opus-4.6",
            "base_url": "https://openrouter.ai/api/v1",
            "provider": "auto",
        },
        "display": _display,
        "agent": {},
        "terminal": {"env_type": "local"},
    }
    clean_env = {"LLM_MODEL": "", "FULILIAN_MAX_ITERATIONS": ""}
    prompt_toolkit_stubs = {
        "prompt_toolkit": MagicMock(),
        "prompt_toolkit.history": MagicMock(),
        "prompt_toolkit.styles": MagicMock(),
        "prompt_toolkit.patch_stdout": MagicMock(),
        "prompt_toolkit.application": MagicMock(),
        "prompt_toolkit.layout": MagicMock(),
        "prompt_toolkit.layout.processors": MagicMock(),
        "prompt_toolkit.filters": MagicMock(),
        "prompt_toolkit.layout.dimension": MagicMock(),
        "prompt_toolkit.layout.menus": MagicMock(),
        "prompt_toolkit.widgets": MagicMock(),
        "prompt_toolkit.key_binding": MagicMock(),
        "prompt_toolkit.completion": MagicMock(),
        "prompt_toolkit.formatted_text": MagicMock(),
        "prompt_toolkit.auto_suggest": MagicMock(),
    }
    with patch.dict(sys.modules, prompt_toolkit_stubs), \
         patch.dict("os.environ", clean_env, clear=False):
        import cli as mod
        mod = importlib.reload(mod)
        _cli_mod = mod
        with patch.object(mod, "get_tool_definitions", return_value=[]), \
             patch.dict(mod.__dict__, {"CLI_CONFIG": _clean_config}):
            if verbose is _UNSET:
                return mod.FulilianCLI()
            return mod.FulilianCLI(verbose=verbose)


def _emitted(mock_print):
    """Plain stdout lines captured from a patched _cprint."""
    return [_plain(c.args[0]) for c in mock_print.call_args_list]


class TestUserMessageGrammar:
    def test_user_message_uses_chevron_not_bullet(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print, \
             patch.object(_cli_mod, "ChatConsole") as mock_console:
            cli._print_user_message_preview("hello world")
        printed = " ".join(
            str(c.args[0]) for c in mock_console.return_value.print.call_args_list
        )
        assert "❯" in printed
        assert "hello world" in printed
        # The old ● marker is gone from the user line.
        assert "●[/] [bold]hello world" not in printed


class TestStreamBulletGrammar:
    def test_first_line_carries_bullet_and_no_box(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("Hello there.\n")
        lines = _emitted(mock_print)
        assert any("● " in ln and "Hello there." in ln for ln in lines)
        joined = "".join(lines)
        assert "╭" not in joined and "╰" not in joined

    def test_continuation_lines_get_hanging_indent(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("first\nsecond\n")
        lines = [ln for ln in _emitted(mock_print) if ln.strip()]
        body = [ln for ln in lines if "second" in ln]
        assert body and body[0].startswith("  ")

    def test_bullet_emitted_once_per_turn(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("para one\n")
            cli._emit_stream_text("para two\n")
        bullets = [ln for ln in _emitted(mock_print) if "● " in ln]
        assert len(bullets) == 1

    def test_reset_stream_state_restores_bullet(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("one\n")
            cli._reset_stream_state()
            cli._emit_stream_text("two\n")
        bullets = [ln for ln in _emitted(mock_print) if "● " in ln]
        assert len(bullets) == 2

    def test_fenced_code_is_exempt_from_indent(self):
        """Default config is markdown=strip, which deletes the ``` markers —
        fence state must therefore be read from the raw line."""
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("intro\n```\ncode_one\ncode_two\n```\noutro\n")
        lines = _emitted(mock_print)
        code = [ln for ln in lines if "code_one" in ln or "code_two" in ln]
        assert len(code) == 2
        for ln in code:
            assert not ln.startswith("  "), f"code line was indented: {ln!r}"
        outro = [ln for ln in lines if "outro" in ln]
        assert outro and outro[0].startswith("  ")

    def test_render_mode_streams_nothing_final_render_takes_over(self):
        """With ``final_response_markdown: render`` the stream is silent —
        no scrollback lines are committed while tokens arrive, so the fully
        rendered response appears exactly once at end of turn (via the
        unskipped final grid). The stream tail still feeds the spinner."""
        cli = _make_cli(display_extra={"final_response_markdown": "render"})
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("intro\n```python\ncode_one\n```\n")
        # Nothing committed to the scrollback — not even the prose intro.
        assert _emitted(mock_print) == []
        assert cli._stream_box_opened is False
        # The tail buffer kept the last words for the spinner preview.
        assert "code_one" in getattr(cli, "_stream_tail_buf", "")

    def test_flush_stream_does_not_close_a_box(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("content\n")
            cli._flush_stream()
        joined = "".join(_emitted(mock_print))
        assert "╰" not in joined and "╭" not in joined

    def test_table_rows_are_exempt_from_indent(self):
        cli = _make_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._emit_stream_text("intro\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\nafter\n")
            cli._flush_stream()
        lines = [ln for ln in _emitted(mock_print) if "| 1 |" in ln or "1" in ln and "|" in ln]
        assert lines
        for ln in lines:
            assert not ln.startswith("  "), f"table row was indented: {ln!r}"


class TestReasoningLiveRegion:
    """Reasoning streams into the live region and folds to one committed line.

    The live region is the bottom chrome (never the scrollback), so a long
    thinking block cannot bury the transcript; closing it commits exactly one
    line unless display.reasoning_full opts into the whole trace.
    """

    def _reasoning_cli(self, **display_extra):
        cli = _make_cli(display_extra=display_extra)
        cli.show_reasoning = True
        cli._reset_stream_state()
        return cli

    def test_in_flight_reasoning_is_not_committed_to_scrollback(self):
        cli = self._reasoning_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._stream_reasoning_delta("step one\n")
            cli._stream_reasoning_delta("step two\n")
        assert _emitted(mock_print) == []

    def test_live_region_shows_the_tail(self):
        cli = self._reasoning_cli()
        cli._stream_reasoning_delta("one\ntwo\nthree\nfour\nfive\n")
        assert cli._render_reasoning_live_lines() == ["three", "four", "five"]

    def test_live_region_empty_when_inactive(self):
        cli = self._reasoning_cli()
        assert cli._render_reasoning_live_lines() == []
        assert cli._reasoning_widget_height() == 0

    def test_widget_height_is_fixed_while_in_flight(self):
        cli = self._reasoning_cli()
        cli._stream_reasoning_delta("one line\n")
        assert cli._reasoning_widget_height() == 3
        cli._stream_reasoning_delta("two\nthree\nfour\nfive\nsix\n")
        assert cli._reasoning_widget_height() == 3

    def test_close_folds_into_a_single_line(self):
        cli = self._reasoning_cli()
        cli._stream_reasoning_delta("thinking hard\nabout things\n")
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._close_reasoning_box()
        lines = [ln for ln in _emitted(mock_print) if ln.strip()]
        assert len(lines) == 1
        assert re.search(r"● Thought for \d+s", lines[0])
        assert "/reasoning full" in lines[0]
        # The live region collapses once closed.
        assert cli._render_reasoning_live_lines() == []

    def test_close_is_idempotent_when_nothing_in_flight(self):
        cli = self._reasoning_cli()
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._close_reasoning_box()
            cli._close_reasoning_box()
        assert _emitted(mock_print) == []

    def test_reasoning_full_dumps_the_whole_trace(self):
        cli = self._reasoning_cli(reasoning_full=True)
        cli._stream_reasoning_delta("alpha\nbeta\n")
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._close_reasoning_box()
        plain = _emitted(mock_print)
        assert any(re.search(r"● Thinking for \d+s", ln) for ln in plain)
        assert any("alpha" in ln for ln in plain)
        assert any("beta" in ln for ln in plain)
        assert not any("/reasoning full" in ln for ln in plain)

    def test_late_reasoning_after_response_started_is_dropped(self):
        cli = self._reasoning_cli()
        cli._stream_box_opened = True
        with patch.object(_cli_mod, "_cprint") as mock_print:
            cli._stream_reasoning_delta("should not render")
            cli._close_reasoning_box()
        assert _emitted(mock_print) == []
        assert cli._render_reasoning_live_lines() == []


class TestNonStreamingResponseGrammar:
    """The default (non-streaming) response path must use the same ● bullet."""

    def test_final_response_grid_uses_bullet_not_panel_border(self):
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.table import Table
        from rich.text import Text

        # Reproduce the renderable the CLI builds and confirm the shape.
        grid = Table.grid(padding=0)
        grid.add_column(width=2)
        grid.add_column()
        grid.add_row(Text("● "), Markdown("Hello **there**."))
        console = Console(width=60, force_terminal=False, record=True)
        console.print(grid)
        out = console.export_text(styles=False)
        assert "● Hello there." in out
        assert "☿" not in out
