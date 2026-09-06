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
DEFAULT_MAX_TOKENS = 1_500_000        # 历史参考值；默认不限 token（见下）
DEFAULT_MAX_NO_OUTPUT_ROUNDS = 7      # 连续无新 Fact 轮数
DEFAULT_MAX_VARIANT_FAILURES = 7      # 同一攻击类变体失败次数
PARTIAL_FLAG_BUDGET_MULTIPLIER = 2    # 临门不弃：预算放大倍数

# 按难度分档的 token 预算（2026-09-04 起默认不启用）：max_tokens=None
# 表示不设 token 上限（题目可一直解到出 flag），本表仅在调用方显式
# 选择难度分档时作参考（easy/medium/hard/expert 档，medium=全局历史默认）。
DIFFICULTY_TOKEN_BUDGETS = {
    "easy": 200_000,
    "medium": DEFAULT_MAX_TOKENS,
    "hard": 1_000_000,
    "expert": 1_500_000,
}


def difficulty_token_budget(difficulty: str) -> int:
    """难度 → token 止损上限（仅显式启用分档时使用；未知难度按 medium）。"""
    return DIFFICULTY_TOKEN_BUDGETS.get((difficulty or "").lower(), DEFAULT_MAX_TOKENS)

# 精确消耗文件名（solver 每次尝试结束时由 run_agent 会话计数器写入；
# stopper 优先读它，solver.log 估算仅作 fallback/运行中无文件时的兜底）
USAGE_FILE = "usage.json"

SOLVER_LOG = "solver.log"


def read_exact_usage(work_dir: str | Path) -> Optional[dict]:
    """读取 solver 写入的精确消耗记录 usage.json。

    Returns:
        dict（total_tokens/input_tokens/output_tokens/api_calls/cost_usd/
        attempts 累计），文件缺失或损坏返回 None（调用方走日志估算）。
    """
    import json

    usage_file = Path(work_dir) / USAGE_FILE
    try:
        if not usage_file.is_file():
            return None
        data = json.loads(usage_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def usage_tokens(work_dir: str | Path) -> Optional[int]:
    """精确 token 数：usage.json 的累计 total_tokens；无文件返回 None。"""
    data = read_exact_usage(work_dir)
    if not data:
        return None
    try:
        return int(data.get("total_tokens", 0) or 0)
    except (TypeError, ValueError):
        return None


def estimate_tokens_from_log(work_dir: str | Path) -> int:
    """从 solver.log 估算已消耗 token 数（4 字符 ≈ 1 token）。

    run_agent 日志不含精确 token 计数，按字符量估算用于止损判断；
    精确计数优先走 usage.json（``usage_tokens``），本函数仅作 fallback。
    注意：solver.log 每次尝试被 ``open(..., "w")`` 截断重写，估算值只反映
    当前尝试——跨尝试累计依赖 usage.json 的 attempts 加权。
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
    不做任何 IO。阈值可配置（默认值见常量）。``max_tokens=None`` 表示
    不设 token 预算上限（默认：题目一直解到解出为止，token 仅记账）；
    传入具体数值（如 CLI --max-tokens）即启用预算保险丝。``difficulty``
    不再隐式分档，仅供调用方自查。
    """

    def __init__(
        self,
        max_tokens: Optional[int] = None,
        max_no_output_rounds: int = DEFAULT_MAX_NO_OUTPUT_ROUNDS,
        max_variant_failures: int = DEFAULT_MAX_VARIANT_FAILURES,
        difficulty: str = "",
    ):
        self.difficulty = str(difficulty or "").lower()
        # max_tokens=None → 无预算上限（不限 token，靠其余维度止损）；
        # 显式传入 → 启用 BUDGET_EXCEEDED 保险丝。
        self.max_tokens = int(max_tokens) if max_tokens is not None else None
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
        # max_tokens=None（默认不限 token）时跳过预算维度。
        if self.max_tokens is not None:
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
    "DIFFICULTY_TOKEN_BUDGETS",
    "difficulty_token_budget",
    "USAGE_FILE",
    "read_exact_usage",
    "usage_tokens",
    "Stopper",
    "estimate_tokens_from_log",
    "count_variant_failures",
]
