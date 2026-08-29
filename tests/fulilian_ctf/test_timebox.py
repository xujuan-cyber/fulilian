"""时间盒管理（F2-002 / F2-010）单元测试。"""

from __future__ import annotations

import time

from fulilian_ctf.timebox import (
    DIFFICULTY_BUDGETS,
    TIER_LABELS,
    TIER_THRESHOLDS,
    Timebox,
    difficulty_adjusted_budget,
)


# ── 难度自适应采样（F2-010）───────────────────────────────────────────────

def test_difficulty_budgets():
    assert difficulty_adjusted_budget("easy") == 300
    assert difficulty_adjusted_budget("medium") == 900
    assert difficulty_adjusted_budget("hard") == 600
    assert difficulty_adjusted_budget("HARD") == 600  # 大小写不敏感
    assert difficulty_adjusted_budget("unknown") == 300  # 未知难度按 easy
    assert difficulty_adjusted_budget("") == 300


def test_easy_gets_least_budget():
    """Easy 给最少预算。"""
    assert DIFFICULTY_BUDGETS["easy"] < DIFFICULTY_BUDGETS["medium"]
    assert DIFFICULTY_BUDGETS["easy"] == TIER_THRESHOLDS[0]


def test_hard_pressed_offline():
    """Hard 压在线下（低于 Medium 满预算）。"""
    assert DIFFICULTY_BUDGETS["hard"] < DIFFICULTY_BUDGETS["medium"]


# ── 递增式阶梯 ─────────────────────────────────────────────────────────────

def test_default_ladder():
    """默认（easy）首档 300s，接续标准档位。"""
    tb = Timebox()
    assert tb.budgets == [300, 900, 1800, 3600]
    assert tb.tier_label == "short"


def test_medium_ladder():
    """Medium 满预算 900s 起步（不再回落 300s 档）。"""
    tb = Timebox(initial_budget=900)
    assert tb.budgets == [900, 1800, 3600]
    assert tb.tier_label == "short"


def test_hard_ladder():
    """Hard 压线 600s 起步。"""
    tb = Timebox(initial_budget=600)
    assert tb.budgets == [600, 900, 1800, 3600]


def test_single_rung_non_incremental():
    """CLI --timebox 覆盖：单档时间盒，到期即中断。"""
    tb = Timebox(initial_budget=10, incremental=False)
    assert tb.budgets == [10]


# ── 档位升级与到期 ─────────────────────────────────────────────────────────

def test_tier_upgrade_continues():
    """当前档超时 → 升级档位并返回 False（允许继续）。"""
    tb = Timebox(initial_budget=1)  # budgets=[1, 300, 900, 1800, 3600]
    tb.start()
    time.sleep(1.2)
    assert tb.check() is False
    assert tb.current_tier == 1
    assert tb.is_expired is False
    assert tb.tier_label == "medium"
    assert tb.remaining() > 0


def test_final_tier_expiry():
    """耗尽最后一档 → 返回 True（最终超时）。"""
    tb = Timebox(initial_budget=1, incremental=False)  # 单档 [1]
    tb.start()
    time.sleep(1.2)
    assert tb.check() is True
    assert tb.is_expired is True


def test_not_expired_early():
    tb = Timebox(initial_budget=60)
    tb.start()
    assert tb.check() is False
    assert tb.remaining() > 50


def test_remaining_bounds():
    tb = Timebox(initial_budget=10, incremental=False)
    tb.start()
    assert 0 < tb.remaining() <= 10


def test_total_budget():
    tb = Timebox(initial_budget=300)
    assert tb.total_budget == sum([300, 900, 1800, 3600])


def test_tier_labels_exhaustive():
    """4 档标签覆盖。"""
    assert TIER_LABELS == ["short", "medium", "long", "extended"]
