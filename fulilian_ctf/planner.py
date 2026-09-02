"""Planner 动态修订循环 — 规划→执行→评估→修订（F4-008）。

设计原则：
- Planner 只做规划，不调用工具
- Executor 只执行，不规划
- 任务结果返回摘要
- 最大轮次 10，防止无限循环
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from .blackboard import Blackboard, Fact, State
from .reasoner import Plan, Reasoner, Task, TaskResult

# ── 上下文管理 ────────────────────────────────────────────────────────────


class TurnRole:
    """对话轮次角色常量。"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Turn:
    """单轮对话记录。

    Attributes:
        role: 角色（system/user/assistant/tool）
        content: 内容文本
        is_reasoning: 是否为推理/摘要内容
        token_count: 估算 token 数
    """
    role: str
    content: str
    is_reasoning: bool = False
    token_count: int = 0


class ContextManager:
    """每个 Agent 独立的上下文管理器。

    通过裁剪和摘要保持上下文紧凑，避免超出 max_tokens 限制。

    Args:
        agent_id: Agent 标识
        max_tokens: 最大 token 数（默认 10000，近似按字符/4 估算）
    """

    def __init__(self, agent_id: str, max_tokens: int = 10000) -> None:
        self.agent_id = agent_id
        self.max_tokens = max_tokens
        self.history: list[Turn] = []
        self.system_prompt: Optional[str] = None

    def set_system_prompt(self, prompt: str) -> None:
        """设置系统提示并重置历史。"""
        self.system_prompt = prompt
        self.history = [Turn(TurnRole.SYSTEM, prompt, False, self._count_tokens(prompt))]

    def add_turn(self, role: str, content: str, is_reasoning: bool = False) -> None:
        """添加一轮对话记录，超过 max_tokens 时自动裁剪。"""
        turn = Turn(role, content, is_reasoning, self._count_tokens(content))
        self.history.append(turn)
        self._trim_if_needed()

    def _trim_if_needed(self) -> None:
        """超出 max_tokens 时：保留 system prompt + 最近 3 轮 + 摘要历史。"""
        total = sum(t.token_count for t in self.history)
        if total <= self.max_tokens:
            return
        system_part = [t for t in self.history if t.role == TurnRole.SYSTEM]
        recent = [t for t in self.history if t.role != TurnRole.SYSTEM][-3:]
        early = [
            t for t in self.history
            if t.role != TurnRole.SYSTEM and t not in recent
        ]
        if early:
            reasoning_parts = [t.content for t in early if t.is_reasoning]
            if reasoning_parts:
                summary = "\n".join(reasoning_parts)[-500:]
            else:
                summary = "\n".join(t.content[:100] for t in early)[-500:]
            self.history = (
                system_part
                + [Turn(TurnRole.SYSTEM, f"---历史摘要---\n{summary}", True)]
                + recent
            )
        else:
            self.history = system_part + recent

    def get_context(self) -> str:
        """获取完整上下文文本。"""
        return "\n".join(f"<{t.role}> {t.content}" for t in self.history)

    @staticmethod
    def _count_tokens(text: str) -> int:
        """粗略估算 token 数（按字符/4）。"""
        return max(1, len(text) // 4)


class Executor(ABC):
    """执行器基类 — 只执行不规划。"""

    @abstractmethod
    def execute(self, task: Task) -> TaskResult:
        """执行单个任务，返回结果。"""


@dataclass
class Planner:
    """规划器 — 协调规划→执行→评估→修订→继续。

    Attributes:
        reasoner: 分析器实例
        blackboard: 黑板实例
        max_rounds: 最大修订轮次（默认 10）
        _executors: 注册的执行器映射
        _round: 当前轮次
        context: 上下文管理器
    """

    reasoner: Reasoner
    blackboard: Blackboard
    max_rounds: int = 10
    _executors: dict[str, Executor] = field(default_factory=dict, init=False)
    _round: int = field(default=0, init=False)
    context: ContextManager = field(init=False)

    def __post_init__(self) -> None:
        """初始化后创建上下文管理器。"""
        self.context = ContextManager("planner", max_tokens=10000)

    def register_executor(self, name: str, executor: Executor) -> None:
        """注册执行器。"""
        self._executors[name] = executor

    def run(self, challenge: Any, env_info: Any = None) -> Plan:
        """主循环：规划→执行→评估→修订→继续。

        Args:
            challenge: 挑战对象（含元信息）
            env_info: 环境信息（来自 AutoPrompter）

        Returns:
            Plan: 最终计划（is_done=True 表示完成）
        """
        # 1. 初始规划
        plan = self.reasoner.initial_plan(challenge, env_info)
        self._round = 0
        self.context.set_system_prompt(plan.description)
        self.context.add_turn(TurnRole.USER, f"Initial plan: {plan.description}")

        # 2. 主循环
        while self._round < self.max_rounds:
            self._round += 1
            self.context.add_turn(
                TurnRole.ASSISTANT,
                f"Round {self._round}: executing {len(plan.tasks)} tasks",
                is_reasoning=True,
            )

            # 执行当前计划的所有任务
            results: list[TaskResult] = []
            for task in plan.tasks:
                result = self._execute_task(task)
                results.append(result)
                # 记录结果到黑板
                if result.new_facts:
                    for fact_content in result.new_facts:
                        self.blackboard.add_fact(
                            Fact(
                                content=fact_content,
                                source="planner",
                                state=State.CONFIRMED,
                            )
                        )

            # 记录执行结果到上下文
            for r in results:
                self.context.add_turn(
                    TurnRole.TOOL,
                    f"Task {r.task_id}: success={r.success} flag={r.flag_found} stuck={r.is_stuck}",
                    is_reasoning=True,
                )

            # 检查是否有 flag 找到
            for r in results:
                if r.flag_found:
                    self.context.add_turn(TurnRole.ASSISTANT, f"Flag found: {r.flag}")
                    return Plan.done(flag=r.flag)

            # 评估与修订
            plan = self.reasoner.evaluate_and_revise(results)
            self.context.add_turn(
                TurnRole.ASSISTANT,
                f"Plan revised to {len(plan.tasks)} tasks, round {self._round}",
                is_reasoning=True,
            )

            # 如果计划已完成
            if plan.is_done:
                return plan

        # 达到最大轮次仍未完成
        return Plan(
            category=plan.category,
            round=self._round,
            description=f"Max rounds ({self.max_rounds}) reached without solution",
        )

    def _execute_task(self, task: Task) -> TaskResult:
        """执行单个任务（通过注册的执行器）。"""
        executor = self._executors.get(task.category.value)
        if executor is None:
            # 无专门执行器，返回空结果
            return TaskResult(
                task_id=task.id,
                success=False,
                summary=f"No executor registered for category {task.category.value}",
                is_stuck=False,
            )
        try:
            return executor.execute(task)
        except Exception:  # noqa: BLE001 — 执行器异常不阻断循环
            return TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Executor error for {task.id}",
                is_stuck=True,
            )


__all__ = [
    "TurnRole",
    "Turn",
    "ContextManager",
    "Executor",
    "Planner",
]