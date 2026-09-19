"""Tests for the ``preview_lines`` pass-through in tools/approval.py.

The keyword is display-only and must not break callbacks registered before it
existed (the legacy-signature contract documented on
``prompt_dangerous_approval``).
"""

import tools.approval as approval_mod
from tools.approval import prompt_dangerous_approval
from unittest.mock import patch


def _legacy_callback(command, description, **kwargs):
    """Pre-preview_lines signature: takes only the documented keywords."""
    return kwargs.setdefault("_legacy", "once")


LEGACY_SEEN = {}


def _strict_legacy_callback(command, description, *, allow_permanent=True,
                            allow_session=True, smart_denied=False):
    LEGACY_SEEN["kwargs"] = {
        "allow_permanent": allow_permanent,
        "allow_session": allow_session,
        "smart_denied": smart_denied,
    }
    return "once"


def test_legacy_callback_without_preview_lines_still_works():
    LEGACY_SEEN.clear()
    choice = prompt_dangerous_approval(
        "cmd", "desc",
        approval_callback=_strict_legacy_callback,
        preview_lines=["  1 +new"],
    )
    assert choice == "once"
    assert "preview_lines" not in LEGACY_SEEN["kwargs"]


def test_callback_with_kwargs_receives_the_preview():
    captured = {}

    def _cb(command, description, **kwargs):
        captured.update(kwargs)
        return "once"

    prompt_dangerous_approval(
        "cmd", "desc",
        approval_callback=_cb,
        preview_lines=["  1 +new"],
    )
    assert captured.get("preview_lines") == ["  1 +new"]


def test_callback_without_preview_when_none_supplied():
    captured = {}

    def _cb(command, description, **kwargs):
        captured.update(kwargs)
        return "once"

    prompt_dangerous_approval("cmd", "desc", approval_callback=_cb)
    assert "preview_lines" not in captured


def test_preview_lines_are_redacted_before_display():
    """A diff can carry secrets (SSH config, keys), so it gets the same pass."""
    captured = {}
    seen = []

    def _cb(command, description, **kwargs):
        captured.update(kwargs)
        return "once"

    import agent.redact as redact_mod

    def _spy(text):
        seen.append(text)
        return f"<redacted>{text}"

    with patch.object(redact_mod, "redact_sensitive_text", side_effect=_spy):
        prompt_dangerous_approval(
            "cmd", "desc",
            approval_callback=_cb,
            preview_lines=["  1 +api_key=SECRETVALUE", "  2 -old"],
        )

    # Every preview line went through the redaction pass...
    assert "  1 +api_key=SECRETVALUE" in seen
    assert "  2 -old" in seen
    # ...and the callback received the redacted form, not the raw lines.
    assert captured["preview_lines"] == [
        "<redacted>  1 +api_key=SECRETVALUE",
        "<redacted>  2 -old",
    ]


def test_introspection_failure_is_treated_as_unsupported():
    """A callback whose signature cannot be read must not receive the keyword."""
    with patch.object(approval_mod.inspect, "signature", side_effect=ValueError("no sig")):
        assert approval_mod._callback_accepts(lambda *a, **k: "once", "preview_lines") is False


def test_var_keyword_callback_is_detected():
    def _cb(command, description, **kwargs):
        return "once"

    assert approval_mod._callback_accepts(_cb, "preview_lines") is True


def test_explicit_keyword_is_detected():
    def _cb(command, description, *, preview_lines=None):
        return "once"

    assert approval_mod._callback_accepts(_cb, "preview_lines") is True


class TestWriteGateEndToEnd:
    """The real plumbing: write_file_tool → gate → approval → callback.

    ``~/.ssh/config`` is the approval-required path, and the path set is
    derived from ``$HOME``, so pointing HOME at a temp dir exercises the live
    gate without touching the developer's real SSH config.
    """

    def test_ssh_config_write_passes_a_diff_to_the_callback(self, tmp_path, monkeypatch):
        home = tmp_path.resolve()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("FULILIAN_INTERACTIVE", "1")

        ssh_dir = home / ".ssh"
        ssh_dir.mkdir()
        target = ssh_dir / "config"
        target.write_text("Host old\n    ProxyCommand ssh -W %h:%p jump\n")

        from agent.file_safety import is_write_approval_required
        assert is_write_approval_required(str(target)), "gate did not match the temp HOME"

        captured = {}

        def _cb(command, description, **kwargs):
            captured["command"] = command
            captured.update(kwargs)
            return "once"

        from tools.terminal_tool import set_approval_callback
        from tools.file_tools import write_file_tool

        set_approval_callback(_cb)
        try:
            result = write_file_tool(
                str(target), "Host new\n    ProxyCommand ssh -W %h:%p bastion\n"
            )
        finally:
            set_approval_callback(None)

        assert "bytes_written" in str(result), f"write did not proceed: {result}"
        preview = captured.get("preview_lines") or []
        joined = "\n".join(preview)
        # The old block is shown as removals, the new block as additions.
        assert "-Host old" in joined
        assert "+Host new" in joined
        assert str(target) in joined, "preview should name the target file"

