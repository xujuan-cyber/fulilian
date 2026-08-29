"""时间盒管理 — 递增式时间预算 + 难度自适应采样（F2-002 / F2-010）。

递增式时间盒：初始档按难度自适应（Easy 最少预算 / Medium 满预算 / Hard 压线），
后续档位从标准阈值接续，给足探索空间：

    easy   → [300, 900, 1800, 3600]   （5m → 15m → 30m → 60m）
    medium → [900, 1800, 3600]        （15m → 30m → 60m，满预算起步）
    hard   → [600, 900, 1800, 3600]   （10m 压线起步，快速判断可解性）

``check()`` 语义：当前档位超时即升级到下一档并返回 False（继续运行）；
只有耗尽最后一档才返回 True（最终超时）。CLI ``--timebox`` 覆盖时退化为单档
时间盒（``incremental=False``），到期立即中断——用于测试与短跑。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# 标准递增档位（秒）
TIER_THRESHOLDS = [300, 900, 1800, 3600]  # 5m, 15m, 30m, 60m
TIER_LABELS = ["short", "medium", "long", "extended"]

# 难度自适应首档预算（F2-010）
# Easy: 300s (5min) — 最少预算
# Medium: 900s (15min) — 满预算
# Hard: 600s (10min) — 压在线下（快速判断是否可解）
DIFFICULTY_BUDGETS = {
    "easy": 300,
    "medium": 900,
    "hard": 600,
}


def difficulty_adjusted_budget(difficulty: str) -> int:
    """难度自适应采样：返回该难度下的首档时间预算（秒）。未知难度按 easy。"""
    return DIFFICULTY_BUDGETS.get((difficulty or "").lower(), 300)


@dataclass
class Timebox:
    """时间盒状态。

    Attributes:
        initial_budget: 首档预算（秒），由难度自适应或 CLI 覆盖决定
        incremental: True 时首档之后接续标准档位（递增式）；False 时单档（到期即中断）
    """

    initial_budget: int = 300
    incremental: bool = True
    current_tier: int = 0
    start_time: float = 0.0
    elapsed: float = 0.0
    is_expired: bool = False
    budgets: list[int] = field(init=False)

    def __post_init__(self) -> None:
        first = int(self.initial_budget)
        if self.incremental:
            # 递增式阶梯：首档（难度自适应）+ 不低于首档的标准档位
            self.budgets = sorted({first, *(t for t in TIER_THRESHOLDS if t >= first)})
        else:
            self.budgets = [first]

    def start(self) -> None:
        self.start_time = time.time()
        self.elapsed = 0.0
        self.is_expired = False

    def check(self) -> bool:
        """检查是否超时。当前档位超时：升级档位返回 False（继续）；最终档返回 True。"""
        self.elapsed = time.time() - self.start_time
        budget = self.current_budget
        if self.elapsed >= budget:
            if self.current_tier < len(self.budgets) - 1:
                self.current_tier += 1  # 升级到下一阶段
                return False  # 还没最终超时，允许升级
            self.is_expired = True
            return True
        return False

    def remaining(self) -> float:
        """当前档位剩余时间（秒）。"""
        return max(0.0, self.current_budget - self.elapsed)

    @property
    def current_budget(self) -> int:
        """当前档位预算（秒）。"""
        return self.budgets[min(self.current_tier, len(self.budgets) - 1)]

    @property
    def tier_label(self) -> str:
        return TIER_LABELS[min(self.current_tier, len(TIER_LABELS) - 1)]

    @property
    def total_budget(self) -> int:
        """全部档位预算之和（秒）。"""
        return sum(self.budgets)


__all__ = [
    "TIER_THRESHOLDS",
    "TIER_LABELS",
    "DIFFICULTY_BUDGETS",
    "Timebox",
    "difficulty_adjusted_budget",
]
