"""Tests for the phased spinner label and metrics in the CLI TUI.

The label is drawn from Claude Code's verb pool (agent/spinner_verbs.py) and
latched per activity phase, so the spinner shows one stable verb while a phase
is in flight and a fresh one when the turn moves on.  The metrics keep
fulilian's existing elapsed / token-flow contract and add Claude Code's
trailing ``· thinking`` marker.
"""

import importlib
import re
import sys
import time
from unittest.mock import MagicMock, patch

_cli_mod = None


def _make_cli(display_extra=None):
    global _cli_mod
    _display = {"compact": False, "tool_progress": "all"}
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
    stubs = {
        k: MagicMock() for k in (
            "prompt_toolkit", "prompt_toolkit.history", "prompt_toolkit.styles",
            "prompt_toolkit.patch_stdout", "prompt_toolkit.application",
            "prompt_toolkit.layout", "prompt_toolkit.layout.processors",
            "prompt_toolkit.filters", "prompt_toolkit.layout.dimension",
            "prompt_toolkit.layout.menus", "prompt_toolkit.widgets",
            "prompt_toolkit.key_binding", "prompt_toolkit.completion",
            "prompt_toolkit.formatted_text", "prompt_toolkit.auto_suggest",
        )
    }
    with patch.dict(sys.modules, stubs), \
         patch.dict("os.environ", {"LLM_MODEL": "", "FULILIAN_MAX_ITERATIONS": ""}, clear=False):
        import cli as mod
        mod = importlib.reload(mod)
        _cli_mod = mod
        with patch.object(mod, "get_tool_definitions", return_value=[]), \
             patch.dict(mod.__dict__, {"CLI_CONFIG": _clean_config}):
            return mod.FulilianCLI()


def _spinner(cli):
    cli._spinner_text = "🔧 read_file"
    return cli._render_spinner_text()


class TestSpinnerVerbLabel:
    def test_label_before_any_phase_is_the_historical_word(self):
        cli = _make_cli()
        assert "Thinking" in _spinner(cli)
        assert "…" not in _spinner(cli)

    def test_label_is_drawn_from_the_pool(self):
        from agent.spinner_verbs import SPINNER_VERBS

        cli = _make_cli()
        cli._set_spinner_phase("thinking")
        word = _spinner(cli).split("·")[0]
        verb = word.strip().split(" ", 1)[-1].rstrip("…")
        assert verb in SPINNER_VERBS

    def test_verb_is_stable_across_repaints_in_one_phase(self):
        cli = _make_cli()
        cli._set_spinner_phase("thinking")
        first = _spinner(cli)
        for _ in range(5):
            assert _spinner(cli) == first

    def test_phase_change_redraws_the_verb(self):
        cli = _make_cli()
        cli._set_spinner_phase("thinking")
        thinking = _spinner(cli)
        cli._set_spinner_phase("tool")
        assert _spinner(cli) != thinking

    def test_repeating_the_same_phase_does_not_redraw(self):
        cli = _make_cli()
        cli._set_spinner_phase("thinking")
        before = cli._spinner_phase_seed
        cli._set_spinner_phase("thinking")
        assert cli._spinner_phase_seed == before

    def test_spinner_verbs_off_restores_the_fixed_label(self):
        cli = _make_cli(display_extra={"spinner_verbs": "off"})
        cli._set_spinner_phase("thinking")
        assert "Thinking" in _spinner(cli)

    def test_reset_forgets_the_latched_phase(self):
        cli = _make_cli()
        cli._set_spinner_phase("thinking")
        assert cli._spinner_phase == "thinking"
        cli._reset_stream_state()
        assert cli._spinner_phase == ""
        assert cli._spinner_phase_seed == ""


class TestSpinnerMetrics:
    def _with_flow(self, cli, tokens=366, elapsed=8.0):
        cli._spinner_token_flow_enabled = True
        cli._agent_running = True
        cli.agent = MagicMock(session_output_tokens=tokens)
        cli._turn_token_baseline = 0
        cli._thinking_start_time = time.monotonic() - elapsed
        return cli

    def test_elapsed_and_token_flow_are_kept(self):
        cli = self._with_flow(_make_cli())
        text = _spinner(cli)
        assert re.search(r"\(\s*\d+\.\d s|\s*8\.0s", text)
        assert "↓ 366 tok" in text

    def test_thinking_marker_appears_only_while_reasoning_streams(self):
        cli = self._with_flow(_make_cli())
        assert "thinking" not in _spinner(cli)
        cli._reasoning_box_opened = True
        # While a turn runs, the CC chrome hint rides the spinner tail after
        # the metrics (and the thinking marker stays the last phase metric).
        assert _spinner(cli).rstrip().endswith("· thinking)  (esc to interrupt)")

    def test_no_metrics_when_nothing_is_known(self):
        cli = _make_cli()
        cli._spinner_token_flow_enabled = False
        cli._thinking_start_time = 0
        cli._tool_start_time = 0
        assert re.search(r"· 🔧 read_file$", _spinner(cli))

    def test_empty_spinner_text_renders_nothing(self):
        cli = _make_cli()
        cli._spinner_text = ""
        assert cli._render_spinner_text() == ""
