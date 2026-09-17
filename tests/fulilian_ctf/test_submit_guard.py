"""提交闸门测试（submit_guard + 声明式接线）。

覆盖：
- ``SubmitGuard`` 纯逻辑：只防「已确认 flag 重提」、key 隔离、开关
- ``submit_state`` 三态判定与重试策略（见 ``test_submit_state.py``）
- 声明式接线：``tools.ctf_solve._submit_flag_impl``（monkeypatch verify_flag）

平台（CTFd）MCP 接线相关测试已随平台对接整体移除（2026-09-17）。
"""

from __future__ import annotations

import pytest

import fulilian_ctf.submit_guard as sg
from fulilian_ctf.submit_guard import SubmitGuard, reset_default_guard


@pytest.fixture(autouse=True)
def _clean_guard(monkeypatch):
    """每个测试：重置单例 + 确保开关不在禁用位。"""
    monkeypatch.delenv(sg.ENV_SUBMIT_GUARD, raising=False)
    reset_default_guard()
    yield
    reset_default_guard()


# ── SubmitGuard 纯逻辑 ──────────────────────────────────────────────────


def test_fresh_flag_allowed():
    guard = SubmitGuard()
    assert guard.check("k1", "flag{aaa}") == (True, "")


def test_confirmed_flag_returns_already_solved():
    guard = SubmitGuard()
    guard.mark_confirmed("k", "flag{good}")
    ok, reason = guard.check("k", "flag{good}")
    assert not ok and "ALREADY_SOLVED" in reason


def test_flag_normalized_before_check():
    guard = SubmitGuard()
    guard.mark_confirmed("k", "flag{good}\n")
    ok, reason = guard.check("k", "  flag{good}  ")
    assert not ok and "ALREADY_SOLVED" in reason


def test_wrong_flag_is_not_remembered():
    """移除 DUPLICATE 后：答错的 flag 不再被本地短路，可再次提交。"""
    guard = SubmitGuard()
    # 没有任何"记录错答"的入口了 —— check 对未确认 flag 恒放行
    for _ in range(5):
        assert guard.check("k", "flag{wrong}") == (True, "")


def test_keys_are_isolated():
    guard = SubmitGuard()
    guard.mark_confirmed("workdir-A", "flag{dup}")
    assert guard.check("workdir-B", "flag{dup}") == (True, "")


def test_kill_switch_disables_guard(monkeypatch):
    guard = SubmitGuard()
    guard.mark_confirmed("k", "flag{dup}")
    monkeypatch.setenv(sg.ENV_SUBMIT_GUARD, "0")
    assert guard.check("k", "flag{dup}") == (True, "")


def test_empty_flag_never_matched():
    guard = SubmitGuard()
    guard.mark_confirmed("k", "")
    assert guard.check("k", "") == (True, "")


def test_stats_snapshot_and_reset():
    guard = SubmitGuard()
    guard.mark_confirmed("k", "flag{a}")
    guard.mark_confirmed("k", "flag{b}")
    assert guard.stats("k") == {"confirmed": 2}
    assert guard.stats("missing") == {"confirmed": 0}
    guard.reset()
    assert guard.stats("k") == {"confirmed": 0}


# ── 声明式接线：tools.ctf_solve._submit_flag_impl ────────────────────────


@pytest.fixture()
def work_dir(tmp_path):
    wd = tmp_path / "challenge"
    wd.mkdir()
    return wd


def _write_flag(work_dir, content: str) -> None:
    (work_dir / "FLAG").write_text(content, encoding="utf-8")


def test_declarative_confirmed_then_already_solved(monkeypatch, work_dir):
    import tools.ctf_solve as ctf_solve
    from fulilian_ctf.verify import VerificationResult

    monkeypatch.setattr(
        "fulilian_ctf.verify.verify_flag",
        lambda *a, **kw: VerificationResult.CONFIRMED,
    )
    _write_flag(work_dir, "flag{real_one}\n")
    out1 = ctf_solve._submit_flag_impl(work_dir=str(work_dir))
    assert "Flag submitted" in out1
    # 同一内容再次提交 → ALREADY_SOLVED（不再重复走门）
    _write_flag(work_dir, "flag{real_one}")
    out2 = ctf_solve._submit_flag_impl(work_dir=str(work_dir))
    assert "ALREADY_SOLVED" in out2


def test_declarative_rejected_can_retry(monkeypatch, work_dir):
    """移除 DUPLICATE 后：本地门拒绝的候选可以再次提交（会重新过门）。"""
    import tools.ctf_solve as ctf_solve
    from fulilian_ctf.verify import VerificationResult

    calls = []

    def _fake_verify(*a, **kw):
        calls.append(1)
        return VerificationResult.REJECTED

    monkeypatch.setattr("fulilian_ctf.verify.verify_flag", _fake_verify)
    _write_flag(work_dir, "flag{bad_guess}")
    for _ in range(3):
        out = ctf_solve._submit_flag_impl(work_dir=str(work_dir))
        assert "rejected by verification gate" in out
    assert len(calls) == 3  # 每次都真的重新过门，不再被短路


def test_declarative_guard_separate_workdirs(monkeypatch, tmp_path):
    import tools.ctf_solve as ctf_solve
    from fulilian_ctf.verify import VerificationResult

    monkeypatch.setattr(
        "fulilian_ctf.verify.verify_flag",
        lambda *a, **kw: VerificationResult.CONFIRMED,
    )
    wd1 = tmp_path / "c1"
    wd2 = tmp_path / "c2"
    wd1.mkdir()
    wd2.mkdir()
    for wd in (wd1, wd2):
        _write_flag(wd, "flag{same_content}")
        assert "Flag submitted" in ctf_solve._submit_flag_impl(work_dir=str(wd))
