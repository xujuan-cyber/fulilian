"""Tests for the diff preview embedded in the dangerous-command approval panel."""

import queue
import shutil
import threading
from unittest.mock import MagicMock, patch

from cli import FulilianCLI


def _stub():
    cli = FulilianCLI.__new__(FulilianCLI)
    cli._approval_state = None
    cli._approval_deadline = 0
    cli._approval_lock = threading.Lock()
    cli._invalidate = MagicMock()
    return cli


def _state(**overrides):
    state = {
        "command": "<write to ~/.ssh/config>",
        "description": "Write to SSH client config file(s): ~/.ssh/config.",
        "preview_lines": [],
        "choices": ["once", "session", "always", "deny"],
        "selected": 0,
        "response_queue": queue.Queue(),
    }
    state.update(overrides)
    return state


def _panel_text(cli):
    return "".join(text for _style, text in cli._get_approval_display_fragments())


PREVIEW = [
    "  1 -Host old",
    "  2 -    ProxyCommand ssh -W %h:%p jump",
    "  1 +Host new",
    "  2 +    ProxyCommand ssh -W %h:%p bastion",
]


class TestApprovalDiffPreview:
    def test_preview_rows_and_choices_both_render(self):
        cli = _stub()
        cli._approval_state = _state(preview_lines=PREVIEW)
        text = _panel_text(cli)
        assert "-Host old" in text
        assert "+Host new" in text
        for label in ("Allow once", "Deny"):
            assert label in text

    def test_choices_still_render_without_a_preview(self):
        cli = _stub()
        cli._approval_state = _state()
        text = _panel_text(cli)
        assert "Allow once" in text
        assert "Deny" in text

    def test_selected_choice_keeps_its_highlight(self):
        cli = _stub()
        cli._approval_state = _state(preview_lines=PREVIEW, selected=1)
        frags = cli._get_approval_display_fragments()
        assert any("approval-selected" in style for style, _ in frags)

    def test_short_terminal_keeps_the_choices_visible(self):
        cli = _stub()
        long_preview = [f"  {i} +{('x' * 40)}" for i in range(1, 60)]
        cli._approval_state = _state(preview_lines=long_preview)
        with patch.object(shutil, "get_terminal_size", return_value=shutil.os.terminal_size((64, 18))):
            text = _panel_text(cli)
        # The approve/deny options must survive a tight terminal.
        assert "Allow once" in text
        assert "Deny" in text
        # ...and the preview must yield rather than overflow the panel.
        assert "more diff lines" in text or "+" not in text

    def test_preview_never_exceeds_its_row_cap(self):
        cli = _stub()
        long_preview = [f"  {i} +line {i}" for i in range(1, 200)]
        cli._approval_state = _state(preview_lines=long_preview)
        frags = cli._get_approval_display_fragments()
        preview_rows = [
            text for style, text in frags if "approval-preview" in style
        ]
        assert preview_rows, "expected preview rows"
        assert len(preview_rows) <= 12

    def test_whitespace_only_preview_is_ignored(self):
        cli = _stub()
        cli._approval_state = _state(preview_lines=["", "   ", "\t"])
        frags = cli._get_approval_display_fragments()
        assert not any("approval-preview" in style for style, _ in frags)
        assert "Allow once" in "".join(text for _s, text in frags)
