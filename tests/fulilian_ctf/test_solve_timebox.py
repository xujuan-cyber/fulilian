"""单题墙钟保险（FULILIAN_CTF_SOLVE_TIMEOUT）回归锁。

不变量：
1. 时钟未标记（solve-all worker 场景）→ 不干预，交给 dispatcher 的 Timebox。
2. 超预算 → block，且只放行收尾类工具（否则连候选 flag 都写不进 FLAG 文件）。
3. 显式 0 → 关闭；未设 → 用 Tier[-1] 兜底。
"""

from __future__ import annotations

import os
import time

import pytest

from fulilian_ctf import hooks
from fulilian_ctf.env_overrides import ENV_SOLVE_TIMEOUT, OVERRIDE_REGISTRY
from fulilian_ctf.timebox import TIER_THRESHOLDS


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV_SOLVE_TIMEOUT, raising=False)
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)


def _mark_start(work_dir, elapsed_s: int) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / ".solve_start").write_text(str(int(time.time()) - elapsed_s), encoding="utf-8")


def test_no_clock_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(tmp_path))
    assert hooks._check_solve_timebox("terminal") is None


def test_zero_disables(tmp_path, monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(tmp_path))
    monkeypatch.setenv(ENV_SOLVE_TIMEOUT, "0")
    _mark_start(tmp_path, TIER_THRESHOLDS[-1] + 10)
    assert hooks._check_solve_timebox("terminal") is None


def test_default_budget_is_last_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(tmp_path))
    assert hooks._solve_timeout_seconds() == TIER_THRESHOLDS[-1]
    _mark_start(tmp_path, TIER_THRESHOLDS[-1] - 5)
    assert hooks._check_solve_timebox("terminal") is None


def test_over_budget_blocks_but_allows_wrapup(tmp_path, monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(tmp_path))
    monkeypatch.setenv(ENV_SOLVE_TIMEOUT, "10")
    _mark_start(tmp_path, 60)

    verdict = hooks._check_solve_timebox("terminal")
    assert verdict is not None and verdict[0] == "block"
    assert "timebox" in verdict[1]
    for tool in ("write_file", "read_file", "record_fact", "submit_flag", "verify_flag"):
        assert hooks._check_solve_timebox(tool) is None, tool


def test_registry_lists_knob():
    assert any(e.env == ENV_SOLVE_TIMEOUT for e in OVERRIDE_REGISTRY)
