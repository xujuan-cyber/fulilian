"""止损治理器（F2-004 四维 + F2-011 临门不弃）单元测试。

对应实施指南 07-P2-止损与续接.md 7.1 验证方式：
- 预算超限时止损器正确终止
- 连续 N 轮无新 Fact 时切换方向或终止
- 探针返回 INFRA_BLOCKED 时标记跳过
- 同一攻击类 3 次变体失败后强制切换
- 多 flag 链中，已拿到至少一个 flag 时放大预算（临门不弃）
"""

from __future__ import annotations

from pathlib import Path

from fulilian_ctf.blackboard import Blackboard, Fact, Intent
from fulilian_ctf.stopper import (
    PARTIAL_FLAG_BUDGET_MULTIPLIER,
    Stopper,
    count_variant_failures,
    estimate_tokens_from_log,
)


def test_continues_when_none_hit():
    s = Stopper()
    assert (
        s.check(
            project_tokens=100,
            rounds_without_new_fact=1,
            variant_failures=0,
            is_infra_blocked=False,
            has_partial_flag=False,
        )
        is None
    )


# ── 维度 1：预算超限 ─────────────────────────────────────────────────────

def test_budget_exceeded_at_threshold():
    s = Stopper(max_tokens=500_000)
    assert (
        s.check(500_000, 0, 0, False, False) == "BUDGET_EXCEEDED"
    )


def test_budget_below_threshold_ok():
    s = Stopper(max_tokens=500_000)
    assert s.check(499_999, 0, 0, False, False) is None


def test_budget_exceeded_priority_over_infra():
    """预算超限优先于 INFRA_BLOCKED（命中一个即返回）。"""
    s = Stopper(max_tokens=10)
    assert s.check(99, 0, 0, True, False) == "BUDGET_EXCEEDED"


# ── 维度 3：不可达目标 ───────────────────────────────────────────────────

def test_infra_blocked_marks_skip():
    s = Stopper()
    assert s.check(0, 0, 0, True, False) == "INFRA_BLOCKED"


# ── 维度 2：无产出 ───────────────────────────────────────────────────────

def test_no_output_after_n_rounds():
    s = Stopper(max_no_output_rounds=5)
    assert s.check(0, 4, 0, False, False) is None
    assert s.check(0, 5, 0, False, False) == "NO_OUTPUT"


# ── 维度 4：假设空间重复 ─────────────────────────────────────────────────

def test_hypothesis_repeated_after_3_variants():
    s = Stopper(max_variant_failures=3)
    assert s.check(0, 0, 2, False, False) is None
    assert s.check(0, 0, 3, False, False) == "HYPOTHESIS_REPEATED"


# ── 临门不弃（F2-011）───────────────────────────────────────────────────

def test_partial_flag_doubles_budget():
    """已拿到至少一个 flag → 预算放大 2 倍（500K → 1000K）。"""
    s = Stopper(max_tokens=500_000)
    # 无 flag：750K 超限
    assert s.check(750_000, 0, 0, False, False) == "BUDGET_EXCEEDED"
    # 有 flag：750K 在放大后的预算内 → 继续
    assert s.check(750_000, 0, 0, False, True) is None
    # 放大后仍超限 → 终止
    assert (
        s.check(500_000 * PARTIAL_FLAG_BUDGET_MULTIPLIER, 0, 0, False, True)
        == "BUDGET_EXCEEDED"
    )


def test_partial_flag_exempts_no_output():
    """临门不弃：已有 flag 的题豁免无产出维度（多 flag 链不因无产出截断）。"""
    s = Stopper(max_no_output_rounds=5)
    assert s.check(0, 5, 0, False, True) is None  # 有 flag：豁免
    assert s.check(0, 5, 0, False, False) == "NO_OUTPUT"


def test_partial_flag_does_not_exempt_hypothesis():
    """临门不弃不豁免假设空间重复（变体失败仍强制切换攻击类）。"""
    s = Stopper(max_variant_failures=3)
    assert s.check(0, 0, 3, False, True) == "HYPOTHESIS_REPEATED"


# ── 辅助函数 ─────────────────────────────────────────────────────────────

def test_estimate_tokens_from_log(tmp_path):
    work = Path(tmp_path)
    assert estimate_tokens_from_log(work) == 0  # 无日志
    log = work / "solver.log"
    log.write_text("x" * 4000, encoding="utf-8")
    assert estimate_tokens_from_log(work) == 1000  # 4 字符 ≈ 1 token


def test_count_variant_failures_from_board():
    board = Blackboard(challenge_id="p")
    assert count_variant_failures(board) == 0
    assert count_variant_failures(None) == 0
    board.add_intent(Intent(goal="a", approach="x", variant_count=2))
    board.add_intent(Intent(goal="b", approach="y", variant_count=4))
    assert count_variant_failures(board) == 4  # 取最高值（任一攻击类超限即触发）


def test_describe_reason():
    s = Stopper()
    assert "预算超限" in s.describe("BUDGET_EXCEEDED")
    assert s.describe("UNKNOWN") == "UNKNOWN"


def test_custom_thresholds():
    s = Stopper(max_tokens=100, max_no_output_rounds=1, max_variant_failures=1)
    assert s.check(100, 0, 0, False, False) == "BUDGET_EXCEEDED"
    assert s.check(0, 1, 0, False, False) == "NO_OUTPUT"
    assert s.check(0, 0, 1, False, False) == "HYPOTHESIS_REPEATED"
