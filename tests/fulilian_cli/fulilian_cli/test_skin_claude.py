"""The ``claude`` skin: Claude Code's visual grammar as pure skin data.

Behavior contracts for the built-in ``claude`` entry in ``_BUILTIN_SKINS`` —
the exact Claude Code v2.1.291 palette values the classic CLI consumes, the
FuLiLian identity it must NOT overwrite (the skin recolors chrome, it does
not rebrand the agent), and the claude-only tokens that downstream consumers
(``agent/display.py::_diff_ansi``, the composer ``mode-chip`` class) read via
``get_color``.
"""

import pytest

from fulilian_cli.skin_engine import (
    _BUILTIN_SKINS,
    _build_skin_config,
    load_skin,
)


def claude_skin():
    """Fresh SkinConfig for the claude skin (no active-skin state needed)."""
    return load_skin("claude")


class TestClaudePalette:
    def test_loads_from_builtin_table(self):
        assert "claude" in _BUILTIN_SKINS
        assert _BUILTIN_SKINS["claude"]["name"] == "claude"

    def test_brand_accent_is_claude_orange(self):
        skin = claude_skin()
        assert skin.get_color("banner_border") == "#d77757"
        assert skin.get_color("ui_accent") == "#d77757"
        assert skin.get_color("banner_accent") == "#eb9f7f"

    def test_chrome_is_gray_not_gold(self):
        """The claude skin must not inherit the default skin's gold chrome."""
        skin = claude_skin()
        assert skin.get_color("banner_dim") == "#999999"
        assert skin.get_color("input_rule") == "#888888"
        assert skin.get_color("status_bar_dim") == "#6e6e6e"

    def test_semantic_triplet(self):
        skin = claude_skin()
        assert skin.get_color("ui_ok") == "#4eba65"
        assert skin.get_color("ui_error") == "#ff6b80"
        assert skin.get_color("ui_warn") == "#ffc107"

    def test_diff_tokens_are_exact_cc_values(self):
        """agent/display.py::_diff_ansi reads these four keys for the CC
        line-background + word-foreground diff rendering; other skins leave
        them unset and keep the derived colors."""
        skin = claude_skin()
        assert skin.get_color("diff_added_bg") == "#225c2b"
        assert skin.get_color("diff_removed_bg") == "#7a2936"
        assert skin.get_color("diff_added_word") == "#38a660"
        assert skin.get_color("diff_removed_word") == "#b3596b"

    def test_mode_chip_token_present(self):
        assert claude_skin().get_color("mode_chip") == "#af87ff"

    def test_status_bar_pairs_stay_paired(self):
        """The status-bar grays are authored against their own background and
        deliberately excluded from the light-mode foreground remap; if they
        ever change, tests/cli/test_cli_light_mode.py's passthrough cases must
        change with them."""
        skin = claude_skin()
        assert skin.get_color("status_bar_bg") == "#1f1f1f"
        assert skin.get_color("status_bar_text") == "#9a9a9a"
        assert skin.get_color("status_bar_dim") == "#6e6e6e"

    def test_other_skins_have_no_diff_or_chip_tokens(self):
        """The diff/mode-chip keys are claude-only opt-ins — every other
        built-in skin must keep the derived fallback path in _diff_ansi."""
        for name, raw in _BUILTIN_SKINS.items():
            if name == "claude":
                continue
            colors = raw.get("colors", {})
            for key in (
                "diff_added_bg",
                "diff_removed_bg",
                "diff_added_word",
                "diff_removed_word",
                "mode_chip",
            ):
                assert key not in colors, f"{name} unexpectedly sets {key}"


class TestClaudeIdentity:
    def test_branding_inherits_fulilian_identity(self):
        """``branding: {}`` means inherit-from-default — the skin recolors
        chrome but must NOT rebrand the agent."""
        skin = claude_skin()
        default = load_skin("default")
        assert skin.branding.get("agent_name") == default.branding["agent_name"]
        assert skin.branding.get("response_label") == default.branding["response_label"]
        assert skin.branding.get("prompt_symbol") == default.branding["prompt_symbol"]
        assert skin.branding["agent_name"] == "FuLiLian"

    def test_tool_prefix_is_result_slot_glyph(self):
        assert claude_skin().tool_prefix == "⎿"


class TestClaudeSpinner:
    def test_spinner_faces_are_the_cc_glyph_family(self):
        spinner = claude_skin().spinner
        faces = spinner["waiting_faces"]
        assert faces and faces[-1] == "✻"
        # Every face must be a single codepoint — the renderer iterates them
        # one per frame with no width handling.
        for face in faces:
            assert len(face) == 1, face

    def test_thinking_verbs_present(self):
        verbs = claude_skin().spinner["thinking_verbs"]
        assert "thinking" in verbs
        assert all(v and " " not in v for v in verbs)

    def test_no_wings(self):
        """CC has no wing pairs; get_spinner_wings must yield none."""
        assert claude_skin().get_spinner_wings() == []

    def test_default_skin_keeps_its_own_faces(self):
        """The claude faces are a claude-only override — the default skin's
        spinner block is empty (faces are hardcoded in display.py)."""
        assert "waiting_faces" not in load_skin("default").spinner
        assert "waiting_faces" in claude_skin().spinner


class TestUnknownTokensFallBack:
    def test_get_color_accepts_unknown_keys_with_fallback(self):
        skin = claude_skin()
        assert skin.get_color("not_a_token", "#123456") == "#123456"

    def test_paired_polarity_blocks_stay_empty(self):
        """No hand-tuned light/dark overlays — cross-polarity is handled by
        the runtime adaptation shim, and a generated overlay is explicitly
        not wanted (see test_skin_palettes.py)."""
        skin = _build_skin_config(_BUILTIN_SKINS["claude"])
        assert skin.light_colors == {}
        assert skin.dark_colors == {}
