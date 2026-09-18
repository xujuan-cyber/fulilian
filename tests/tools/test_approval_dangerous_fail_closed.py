"""C4-4: the opt-in fail-closed knob for the dangerous-command gate."""

from tools import approval


def _cfg(value):
    return {"approvals": {"dangerous_command_fail_closed": value}}


def test_helper_defaults_true(monkeypatch):
    """C4-4 default-closed (user decision 2026-09-19): unset config = BLOCK."""
    import fulilian_cli.config as cfgmod

    monkeypatch.setattr(cfgmod, "load_config_readonly", lambda: {})
    assert approval._dangerous_command_fail_closed() is True


def test_helper_reads_config_false(monkeypatch):
    import fulilian_cli.config as cfgmod

    monkeypatch.setattr(cfgmod, "load_config_readonly", lambda: _cfg(False))
    assert approval._dangerous_command_fail_closed() is False


def test_helper_tolerates_config_failure_fail_closed(monkeypatch):
    import fulilian_cli.config as cfgmod

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(cfgmod, "load_config_readonly", _boom)
    assert approval._dangerous_command_fail_closed() is True
