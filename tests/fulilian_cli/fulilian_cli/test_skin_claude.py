"""The ``claude`` skin: Claude Code's behavioral grammar as pure skin data.

Behavior contracts for the built-in ``claude`` entry in ``_BUILTIN_SKINS`` —
the palette is inherited from ``default`` (2026-10-07 user revert: FuLiLian
blues everywhere, no color overrides of its own), the FuLiLian identity it
must NOT overwrite, and the claude-only behavioral tokens (single ✻ spinner
face, bare tool names, ⎿ result slot) that downstream consumers read.
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

    def test_claude_ships_no_color_overrides(self):
        """2026-10-07 user revert: the claude skin keeps Claude Code's
        behavioral grammar (✻ spinner, bare tool names, ⎿ slot) but the
        palette inherits the default FuLiLian blues wholesale — prompt
        symbol and response bullet included."""
        assert "colors" not in _BUILTIN_SKINS["claude"]
        skin, default = claude_skin(), load_skin("default")
        for key in (
            "banner_border",
            "banner_accent",
            "ui_accent",
            "response_border",
            "input_rule",
            "status_bar_bg",
            "status_bar_text",
            "status_bar_strong",
        ):
            assert skin.get_color(key) == default.get_color(key), key

    def test_no_skin_sets_claude_only_color_tokens(self):
        """The diff/mode-chip keys were a claude-only color-layer opt-in and
        went with the revert — no built-in may set them, so _diff_ansi keeps
        its derived fallback path and mode-chip falls back to banner_dim."""
        for name, raw in _BUILTIN_SKINS.items():
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

    def test_tool_emojis_disabled_and_other_skins_keep_them(self):
        """claude shows bare tool names (``Read(file)``); every other skin
        keeps emoji via get_tool_emoji's registry/fallback path."""
        assert claude_skin().tool_emojis_enabled is False
        for name, raw in _BUILTIN_SKINS.items():
            if name == "claude":
                continue
            assert raw.get("tool_emojis_enabled", True) is True, name

    def test_tool_result_body_disabled_and_other_skins_keep_it(self):
        """claude collapses read_file to ``⎿ Read N lines`` (CC keeps file
        bodies out of the transcript); every other skin keeps the numbered
        body block via render_tool_result_summary."""
        assert claude_skin().tool_result_body_enabled is False
        for name, raw in _BUILTIN_SKINS.items():
            if name == "claude":
                continue
            assert raw.get("tool_result_body_enabled", True) is True, name

    def test_claude_collapses_read_body_but_default_keeps_it(self):
        """render_tool_result_summary honors the skin gate: claude returns a
        size-only summary with no body; default renders the numbered body."""
        from agent.display import render_tool_result_summary
        from fulilian_cli.skin_engine import set_active_skin

        content = "\n".join(f"line {i}" for i in range(1, 13))
        try:
            set_active_skin("claude")
            summary, body, _numbered = render_tool_result_summary(
                "read_file", content
            )
            assert summary == "Read 12 lines"
            assert body == []
            set_active_skin("default")
            summary, body, numbered = render_tool_result_summary(
                "read_file", content
            )
            assert summary == "Read 12 lines"
            assert len(body) == 12 and numbered is True
        finally:
            set_active_skin("default")


class TestClaudeSpinner:
    def test_spinner_is_a_single_glitch_free_face(self):
        """Only ✻ — the user pinned one status glyph, no frame variety and
        no emoji; the renderer shows ✻ statically while a turn runs."""
        spinner = claude_skin().spinner
        assert spinner["waiting_faces"] == ["✻"]
        assert spinner["thinking_faces"] == ["✻"]

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
