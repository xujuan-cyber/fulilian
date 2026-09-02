"""统一预算控制层 — Token 与费用追踪（F2-002 补充）。

在 timebox.py 的时间控制基础上，增加 Token 消耗和费用追踪。
设计要点：
- BudgetTracker 与 Timebox 解耦：Timebox 仅管时间，BudgetTracker 管 Token+费用
- 每道题独立追踪，支持并发挑战
- 预算告警不打断主流程（异常静默降级）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Difficulty(str, Enum):
    """题目难度等级。"""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


@dataclass
class BudgetConfig:
    """预算配置 — 时间、Token、费用上限。

    Attributes:
        max_time_per_challenge: 单题最长耗时（秒），0 表示不限制
        max_tokens_per_challenge: 单题最大 Token 消耗，0 表示不限制
        max_cost_per_challenge: 单题最大费用（USD），0 表示不限制
        stall_timeout: 无进展判定超时（秒），超过此时间无进展视为卡住
    """

    max_time_per_challenge: int = 900
    max_tokens_per_challenge: int = 50000
    max_cost_per_challenge: float = 0.20
    stall_timeout: int = 120

    @classmethod
    def for_difficulty(cls, difficulty: Difficulty) -> "BudgetConfig":
        """根据难度返回推荐的预算配置。"""
        mapping = {
            Difficulty.EASY: cls(
                max_time_per_challenge=300,
                max_tokens_per_challenge=10000,
                max_cost_per_challenge=0.05,
                stall_timeout=60,
            ),
            Difficulty.MEDIUM: cls(
                max_time_per_challenge=900,
                max_tokens_per_challenge=50000,
                max_cost_per_challenge=0.20,
                stall_timeout=120,
            ),
            Difficulty.HARD: cls(
                max_time_per_challenge=1800,
                max_tokens_per_challenge=100000,
                max_cost_per_challenge=0.50,
                stall_timeout=180,
            ),
            Difficulty.EXPERT: cls(
                max_time_per_challenge=3600,
                max_tokens_per_challenge=500000,
                max_cost_per_challenge=2.00,
                stall_timeout=300,
            ),
        }
        return mapping.get(difficulty, cls())


@dataclass
class ChallengeUsage:
    """单道题的消耗记录。"""

    challenge_id: str = ""
    llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    last_progress: float = 0.0
    started_at: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def elapsed(self) -> float:
        if self.started_at:
            return time.time() - self.started_at
        return 0.0

    def to_dict(self) -> dict:
        return {
            "challenge_id": self.challenge_id,
            "llm_calls": self.llm_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost": round(self.total_cost, 6),
            "last_progress": self.last_progress,
            "started_at": self.started_at,
            "elapsed": round(self.elapsed, 2),
        }


class BudgetTracker:
    """预算追踪器 — 管理多个挑战的 Token/费用消耗。

    与 Timebox 互补：Timebox 管时间盒，BudgetTracker 管 Token+费用。
    预算告警不打断主流程，仅记录状态供外部查询。
    """

    def __init__(self, config: Optional[BudgetConfig] = None):
        self.config = config or BudgetConfig()
        self._challenges: dict[str, ChallengeUsage] = {}

    def start_challenge(self, challenge_id: str) -> ChallengeUsage:
        """开始追踪一道题。如果已存在则重置。"""
        usage = ChallengeUsage(
            challenge_id=challenge_id,
            started_at=time.time(),
            last_progress=time.time(),
        )
        self._challenges[challenge_id] = usage
        return usage

    def record_llm_call(
        self,
        challenge_id: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        """记录一次 LLM 调用消耗。"""
        usage = self._challenges.get(challenge_id)
        if usage is None:
            return
        usage.llm_calls += 1
        usage.total_input_tokens += max(0, int(input_tokens))
        usage.total_output_tokens += max(0, int(output_tokens))
        usage.total_cost += max(0.0, float(cost))

    def record_progress(self, challenge_id: str) -> None:
        """记录进展（重置卡住计时器）。"""
        usage = self._challenges.get(challenge_id)
        if usage is None:
            return
        usage.last_progress = time.time()

    def is_stalled(self, challenge_id: str) -> bool:
        """检查是否卡住：无进展时间超过 stall_timeout 且有 LLM 调用。"""
        usage = self._challenges.get(challenge_id)
        if usage is None:
            return False
        if usage.llm_calls == 0:
            return False
        idle = time.time() - usage.last_progress
        return idle > self.config.stall_timeout

    def within_budget(self, challenge_id: str) -> bool:
        """检查是否在预算内。"""
        usage = self._challenges.get(challenge_id)
        if usage is None:
            return True
        if self.config.max_time_per_challenge > 0:
            if usage.elapsed > self.config.max_time_per_challenge:
                return False
        if self.config.max_tokens_per_challenge > 0:
            if usage.total_tokens > self.config.max_tokens_per_challenge:
                return False
        if self.config.max_cost_per_challenge > 0:
            if usage.total_cost > self.config.max_cost_per_challenge:
                return False
        return True

    def get_summary(self, challenge_id: str) -> dict:
        """返回消耗摘要。"""
        usage = self._challenges.get(challenge_id)
        if usage is None:
            return {"challenge_id": challenge_id, "error": "not tracked"}
        summary = usage.to_dict()
        summary["stalled"] = self.is_stalled(challenge_id)
        summary["within_budget"] = self.within_budget(challenge_id)
        summary["budget"] = {
            "max_time": self.config.max_time_per_challenge,
            "max_tokens": self.config.max_tokens_per_challenge,
            "max_cost": self.config.max_cost_per_challenge,
        }
        return summary

    def get_challenge_ids(self) -> list[str]:
        """返回所有被追踪的挑战 ID 列表。"""
        return list(self._challenges.keys())


__all__ = [
    "BudgetConfig",
    "BudgetTracker",
    "ChallengeUsage",
    "Difficulty",
]