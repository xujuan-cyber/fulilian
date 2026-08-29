"""止损治理器 — 4 维止损 + 多 flag 链临门不弃（F2-004 / F2-011）。

对应实施指南 07-P2-止损与续接.md 7.1。四维止损：

| 维度 | 触发条件 | 动作 |
|------|---------|------|
| 预算超限 (BUDGET_EXCEEDED) | 超过最大 token 消耗（默认 500K） | 终止 solver |
| 无产出 (NO_OUTPUT) | 连续 N 轮无新 Fact（CONFIRMED/REFUTED 不变） | 切换方向或终止 |
| 不可达目标 (INFRA_BLOCKED) | 探针返回 INFRA_BLOCKED | 直接标记跳过 |
| 假设空间重复 (HYPOTHESIS_REPEATED) | 同一攻击类 N 次变体失败 | 强制切换攻击类 |

多 flag 链「临门不弃」（F2-011）：已拿到至少一个 flag 的题，不因会话上限
截断——预算放大 2 倍，且无产出维度豁免。

本模块是纯逻辑（无 IO 副作用、可单测）；调度器集成（dispatcher 主循环调用
check、命中后终止进程并写接力块）在 dispatcher.py 中完成。token 消耗在
真实 run_agent 日志中无直接计数，提供 ``estimate_tokens_from_log`` 按字符量
估算（4 字符 ≈ 1 token），亦可由调用方注入精确计数器。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

# 终止原因（与 07 指南 / 03 代码设计一致）
STOP_REASONS = {
    "BUDGET_EXCEEDED": "预算超限：超过最大 token 消耗",
    "NO_OUTPUT": "无产出：连续多轮无新 Fact",
    "INFRA_BLOCKED": "不可达目标：探针返回 INFRA_BLOCKED",
    "HYPOTHESIS_REPEATED": "假设空间重复：同一攻击类变体失败超限",
}

# 默认阈值
DEFAULT_MAX_TOKENS = 500_000          # 最大 token 消耗（默认 500K）
DEFAULT_MAX_NO_OUTPUT_ROUNDS = 5      # 连续无新 Fact 轮数
DEFAULT_MAX_VARIANT_FAILURES = 3      # 同一攻击类变体失败次数
PARTIAL_FLAG_BUDGET_MULTIPLIER = 2    # 临门不弃：预算放大倍数

SOLVER_LOG = "solver.log"


def estimate_tokens_from_log(work_dir: str | Path) -> int:
    """从 solver.log 估算已消耗 token 数（4 字符 ≈ 1 token）。

    run_agent 日志不含精确 token 计数，按字符量估算用于止损判断；
    调用方可注入更精确的计数器（如按 API 响应统计）。
    """
    log_file = Path(work_dir) / SOLVER_LOG
    try:
        size = log_file.stat().st_size if log_file.is_file() else 0
    except OSError:
        return 0
    return size // 4


def count_variant_failures(board) -> int:
    """从黑板统计同一攻击类的变体失败次数（最高值）。

    黑板 Intent.variant_count 由 solver 在每次变体尝试失败后递增；
    任一攻击类的变体失败次数达到阈值即视为假设空间重复。
    """
    if board is None or not getattr(board, "intents", None):
        return 0
    return max((int(getattr(i, "variant_count", 0) or 0) for i in board.intents), default=0)


class Stopper:
    """4 维止损治理器（F2-004）+ 多 flag 链临门不弃（F2-011）。

    纯计算：``check()`` 根据输入状态返回终止原因或 None（继续运行），
    不做任何 IO。阈值可配置（默认值见常量）。
    """

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_no_output_rounds: int = DEFAULT_MAX_NO_OUTPUT_ROUNDS,
        max_variant_failures: int = DEFAULT_MAX_VARIANT_FAILURES,
    ):
        self.max_tokens = max(1, int(max_tokens))
        self.max_no_output_rounds = max(1, int(max_no_output_rounds))
        self.max_variant_failures = max(1, int(max_variant_failures))

    def check(
        self,
        project_tokens: int,
        rounds_without_new_fact: int,
        variant_failures: int,
        is_infra_blocked: bool,
        has_partial_flag: bool,
    ) -> Optional[str]:
        """检查止损条件，返回终止原因或 None。

        Args:
            project_tokens: 已消耗的 token 数（跨重跑累计）
            rounds_without_new_fact: 连续无新 Fact（CONFIRMED/REFUTED 不变）的轮数
            variant_failures: 同一攻击类变体失败次数
            is_infra_blocked: 是否基础设施不可达（探针 INFRA_BLOCKED）
            has_partial_flag: 是否已拿到至少一个 flag（多 flag 题，临门不弃）

        Returns:
            str: 终止原因（STOP_REASONS 键），或 None（继续运行）
        """
        # 临门不弃修正：已经有 flag 的题放大预算（F2-011）
        effective_max_tokens = self.max_tokens
        if has_partial_flag:
            effective_max_tokens *= PARTIAL_FLAG_BUDGET_MULTIPLIER

        if int(project_tokens or 0) >= effective_max_tokens:
            return "BUDGET_EXCEEDED"

        if is_infra_blocked:
            return "INFRA_BLOCKED"

        # 无产出（非临门不弃：已有 flag 的题豁免，避免多 flag 链被截断）
        if (
            not has_partial_flag
            and int(rounds_without_new_fact or 0) >= self.max_no_output_rounds
        ):
            return "NO_OUTPUT"

        # 假设空间重复：同一攻击类变体失败超限 → 强制切换攻击类
        if int(variant_failures or 0) >= self.max_variant_failures:
            return "HYPOTHESIS_REPEATED"

        return None  # 继续运行

    def describe(self, reason: str) -> str:
        """返回终止原因的可读描述。"""
        return STOP_REASONS.get(reason, reason)


# 兼容别名：外部可注入的 token 计数回调类型
TokenCounter = Callable[[str | Path], int]


__all__ = [
    "STOP_REASONS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MAX_NO_OUTPUT_ROUNDS",
    "DEFAULT_MAX_VARIANT_FAILURES",
    "PARTIAL_FLAG_BUDGET_MULTIPLIER",
    "Stopper",
    "estimate_tokens_from_log",
    "count_variant_failures",
]
