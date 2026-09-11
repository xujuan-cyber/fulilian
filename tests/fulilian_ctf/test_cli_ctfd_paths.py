"""P2 回归锁：``fulilian ctfd sync`` 的输出目录必须先 expanduser。

预修复基线（``git checkout HEAD -- fulilian_ctf/cli.py`` 后跑本文件，
再按 md5 恢复）::

    1 failed, 1 passed
    FAILED test_ctfd_sync_expands_user_in_out_dir

背景：``fulilian ctfd sync <url> "~/ctfd"`` —— shell 在引号内不展开 ``~``，
CLI 若原样收下就会建出一个名为 ``~`` 的目录；而下游 ``solve-all`` 走的是
``_resolve_project`` / ``_prepare_work_dir``，那里都先 expanduser ——
于是「同步到 A、去 B 里找」，静默扑空。本文件同时锁住 poll 分支已正确的
行为，避免将来有人「统一」成两边都不展开。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fulilian_ctf import cli


class _FakeAdapter:
    """占位 adapter —— sync_challenges 被 monkeypatch 掉，不会用到它。"""

    def __init__(self, *a, **kw):
        pass


@pytest.fixture
def _patched(monkeypatch):
    """替换 adapter 与 sync_challenges，只观察传给 sync 的路径。"""
    monkeypatch.setattr("fulilian_ctf.ctfd_adapter.CTFdAdapter", _FakeAdapter)
    calls: dict = {}

    def fake_sync(adapter, out_dir):
        calls["out_dir"] = Path(out_dir)
        return []

    monkeypatch.setattr("fulilian_ctf.ctfd_adapter.sync_challenges", fake_sync)
    return calls


def _args(**kw):
    class _A:
        pass

    a = _A()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_ctfd_sync_expands_user_in_out_dir(_patched):
    args = _args(ctfd_action="sync", base_url="http://x", api_key=None,
                 out_dir="~/ctfd-sync-test")
    with pytest.raises(SystemExit) as ei:
        cli.handle_ctfd_command(args)
    assert ei.value.code == 0
    got = _patched["out_dir"]
    assert "~" not in str(got), f"~ 未被展开: {got}"
    assert got == Path("~/ctfd-sync-test").expanduser()


def test_ctfd_poll_expands_user_in_platform_dir(_patched, monkeypatch):
    """poll 分支本来就先 expanduser —— 锁住，别被「统一」改坏。"""
    seen: dict = {}

    def fake_poll(adapter, state_file):
        seen["state"] = Path(state_file)
        return []

    monkeypatch.setattr("fulilian_ctf.ctfd_adapter.poll_new_challenges", fake_poll)
    args = _args(ctfd_action="poll", base_url="http://x", api_key=None,
                 platform_dir="~/ctfd-poll-test")
    with pytest.raises(SystemExit) as ei:
        cli.handle_ctfd_command(args)
    assert ei.value.code == 0
    assert "~" not in str(seen["state"])
    assert seen["state"] == Path("~/ctfd-poll-test").expanduser() / "poll-state.json"
