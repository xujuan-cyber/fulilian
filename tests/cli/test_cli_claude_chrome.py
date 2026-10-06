"""Claude-Code chrome behaviors that only the ``claude`` skin activates.

Covers the composer's rounded rule line, the ``(esc to interrupt)`` spinner
suffix, the YOLO ``bypass permissions on`` mode chip, and the light-mode
remap cases the claude palette added. Every other skin must keep its
existing visuals — each test pins the fallback, not just the claude path.
"""

import pytest

from cli import FulilianCLI, _composer_rule_line, _maybe_remap_for_light_mode
from fulilian_cli.skin_engine import set_active_skin


@pytest.fixture(autouse=True)
def restore_default_skin():
    yield
    set_active_skin("default")


# ── composer rule line ───────────────────────────────────────────────────


class TestComposerRuleLine:
    def test_claude_skin_rounds_the_composer(self):
        set_active_skin("claude")
        top = _composer_rule_line(40)
        bottom = _composer_rule_line(40, bottom=True)
        assert top[0][1].startswith("╭") and top[0][1].endswith("╮")
        assert bottom[0][1].startswith("╰") and bottom[0][1].endswith("╯")
        assert len(top[0][1]) == len(bottom[0][1]) == 40

    def test_claude_rule_uses_the_inherited_input_rule_color(self):
        """The color revert made the claude skin inherit default's palette —
        the rounded composer keeps its shape but takes default's rule blue."""
        set_active_skin("claude")
        top = _composer_rule_line(40)
        assert top[0][0] == "#2E77B9"

    def test_other_skins_keep_the_gradient_rule(self):
        set_active_skin("ares")
        frags = _composer_rule_line(40)
        joined = "".join(t for _, t in frags)
        assert "╭" not in joined and "╰" not in joined
        assert joined == "─" * 40

    def test_degenerate_width_falls_back(self):
        set_active_skin("claude")
        # Width <= 2 has no room for two corner glyphs — must not crash or
        # emit a negative-length bar.
        assert _composer_rule_line(2) == _composer_rule_line(2)
        for w in (0, 1, 2):
            joined = "".join(t for _, t in _composer_rule_line(w))
            assert len(joined) <= 2


# ── spinner interrupt hint ───────────────────────────────────────────────


def _spinner_cli(agent_running: bool) -> FulilianCLI:
    cli = FulilianCLI.__new__(FulilianCLI)
    cli._spinner_text = "running terminal"
    cli._agent_running = agent_running
    cli._tool_start_time = 0
    cli._thinking_start_time = 0
    cli._spinner_phase = "responding"
    cli._spinner_phase_seed = "responding:1"
    cli._spinner_token_flow_enabled = False
    return cli


class TestSpinnerInterruptHint:
    def test_running_turn_shows_esc_hint(self):
        set_active_skin("default")  # hint is skin-independent
        text = FulilianCLI._render_spinner_text(_spinner_cli(True))
        assert "(esc to interrupt)" in text

    def test_idle_spinner_has_no_hint(self):
        set_active_skin("default")
        text = FulilianCLI._render_spinner_text(_spinner_cli(False))
        assert "esc to interrupt" not in text

    def test_claude_spinner_frames_reach_the_renderer(self):
        """The claude skin's single ✻ face must feed the live spinner through
        _active_spinner_frames, not stay in skin data — and stay alone (the
        user pinned ✻ as the only status glyph; no frame variety)."""
        import cli as cli_mod

        set_active_skin("claude")
        frames = cli_mod._active_spinner_frames()
        assert frames == ("✻",)

    def test_default_skin_falls_back_to_braille_frames(self):
        import cli as cli_mod

        set_active_skin("default")
        frames = cli_mod._active_spinner_frames()
        assert "⠋" in frames  # the hardcoded braille set
        assert "✻" not in frames


# ── YOLO mode chip ───────────────────────────────────────────────────────


_SNAPSHOT = {
    "context_length": 128000,
    "context_percent": 12,
    "context_tokens": 15000,
    "session_input_tokens": 1000,
    "session_output_tokens": 500,
    "session_total_tokens": 1500,
    "reasoning_effort": "high",
}


def _meta_cli(yolo: bool) -> FulilianCLI:
    cli = FulilianCLI.__new__(FulilianCLI)
    cli.session_id = None
    cli._get_status_bar_snapshot = lambda: _SNAPSHOT
    cli._get_tui_terminal_width = lambda: 100
    cli._is_session_yolo_active = lambda: yolo
    return cli


class TestYoloModeChip:
    def test_active_bypass_parks_chip_on_meta_line(self):
        set_active_skin("default")  # chip is skin-independent text
        frags = FulilianCLI._get_input_meta_fragments(_meta_cli(True))
        joined = "".join(t for _, t in frags)
        assert "bypass permissions on" in joined

    def test_chip_uses_mode_chip_style_class(self):
        set_active_skin("default")
        frags = FulilianCLI._get_input_meta_fragments(_meta_cli(True))
        assert any("mode-chip" in (s or "") for s, _ in frags)

    def test_no_chip_without_bypass(self):
        set_active_skin("default")
        frags = FulilianCLI._get_input_meta_fragments(_meta_cli(False))
        assert "bypass" not in "".join(t for _, t in frags)

    def test_chip_reserves_its_own_width(self):
        """The right-aligned block must stay inside the terminal width even
        with both the effort badge and the chip present."""
        set_active_skin("default")
        cli = _meta_cli(True)
        cli._get_tui_terminal_width = lambda: 60
        frags = FulilianCLI._get_input_meta_fragments(cli)
        width = FulilianCLI._status_bar_display_width("".join(t for _, t in frags))
        assert width <= 60


# ── light-mode remap additions ───────────────────────────────────────────


class TestClaudeLightModeRemap:
    def test_unlisted_hex_passes_through_in_light_mode(self, monkeypatch):
        """Skins inherit default's palette now — any hex not in the remap
        table must reach the terminal untouched (the old claude-gray
        darkening entry went with the color revert)."""
        import cli as cli_mod

        monkeypatch.setattr(cli_mod, "_detect_light_mode", lambda: True)
        assert _maybe_remap_for_light_mode("#9a9a9a") == "#9a9a9a"

    def test_claude_orange_remaps_for_light(self, monkeypatch):
        import cli as cli_mod

        monkeypatch.setattr(cli_mod, "_detect_light_mode", lambda: True)
        # The remap table is upper-case; compare case-insensitively.
        # (#D77757 is the banner mascot's body orange — pre-claude entry.)
        assert _maybe_remap_for_light_mode("#d77757").upper() == "#B05332"

    def test_remap_is_noop_in_dark_mode(self, monkeypatch):
        import cli as cli_mod

        monkeypatch.setattr(cli_mod, "_detect_light_mode", lambda: False)
        assert _maybe_remap_for_light_mode("#999999") == "#999999"
