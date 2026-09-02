"""Planner 动态修订循环 — 任务分解与计划修订（F4-008）。

实现 Planner 动态修订循环：
1. Reasoner 负责分析和规划（"思考"）
2. Executor 负责执行（"行动"）
3. Planner 协调规划→执行→评估→修订→继续

设计要点：
- Reasoner 只做规划，不调用工具
- 任务分解按类别定制（PWN/REV/WEB/CRYPTO/FORENSICS/MISC）
- 卡住时自动切换策略
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskCategory(str, Enum):
    """CTF 题目类别。"""

    PWN = "pwn"
    REV = "rev"
    WEB = "web"
    CRYPTO = "crypto"
    FORENSICS = "forensics"
    MISC = "misc"


@dataclass
class Task:
    """单个任务定义。"""

    id: str = ""
    category: TaskCategory = TaskCategory.MISC
    description: str = ""
    context: str = ""
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5

    def __repr__(self) -> str:
        return f"Task(id={self.id!r}, category={self.category.value}, desc={self.description[:40]!r})"


@dataclass
class TaskResult:
    """任务执行结果。"""

    task_id: str = ""
    success: bool = False
    summary: str = ""
    flag_found: bool = False
    flag: str = ""
    is_stuck: bool = False
    new_facts: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"TaskResult(task_id={self.task_id!r}, success={self.success}, "
            f"flag_found={self.flag_found}, flag={self.flag!r}, stuck={self.is_stuck})"
        )


@dataclass
class Plan:
    """解题计划。"""

    category: TaskCategory = TaskCategory.MISC
    tasks: list[Task] = field(default_factory=list)
    round: int = 0
    description: str = ""
    is_done: bool = False
    flag: str = ""

    @classmethod
    def done(cls, flag: str) -> "Plan":
        """创建已完成计划（找到 flag 时使用）。"""
        return cls(is_done=True, flag=flag)

    def __repr__(self) -> str:
        return (
            f"Plan(category={self.category.value}, tasks={len(self.tasks)}, "
            f"round={self.round}, done={self.is_done})"
        )


# ── 类别分解策略 ──────────────────────────────────────────────────────────


# 各类别的标准任务分解
_CATEGORY_DECOMPOSE: dict[TaskCategory, list[dict]] = {
    TaskCategory.PWN: [
        {"id": "pwn_checksec", "desc": "Run checksec to analyze binary protections", "priority": 1},
        {"id": "pwn_analyze", "desc": "Disassemble and analyze the binary for vulnerabilities", "priority": 2, "depends": ["pwn_checksec"]},
        {"id": "pwn_exploit", "desc": "Develop and run exploit against the target", "priority": 3, "depends": ["pwn_analyze"]},
    ],
    TaskCategory.REV: [
        {"id": "rev_strings", "desc": "Extract strings from the binary", "priority": 1},
        {"id": "rev_disassemble", "desc": "Disassemble and analyze the code logic", "priority": 2, "depends": ["rev_strings"]},
        {"id": "rev_reconstruct", "desc": "Reconstruct the algorithm or flag format", "priority": 3, "depends": ["rev_disassemble"]},
    ],
    TaskCategory.WEB: [
        {"id": "web_recon", "desc": "Reconnaissance: enumerate endpoints, files, and parameters", "priority": 1},
        {"id": "web_scan", "desc": "Scan for common web vulnerabilities", "priority": 2, "depends": ["web_recon"]},
        {"id": "web_attack", "desc": "Exploit identified vulnerabilities", "priority": 3, "depends": ["web_scan"]},
    ],
    TaskCategory.CRYPTO: [
        {"id": "crypto_identify", "desc": "Identify the cipher and encoding scheme", "priority": 1},
        {"id": "crypto_analyze", "desc": "Analyze cryptographic weaknesses", "priority": 2, "depends": ["crypto_identify"]},
        {"id": "crypto_crack", "desc": "Crack the cipher or decode the data", "priority": 3, "depends": ["crypto_analyze"]},
    ],
    TaskCategory.FORENSICS: [
        {"id": "forensics_identify", "desc": "Identify file types and extract hidden data", "priority": 1},
        {"id": "forensics_extract", "desc": "Extract and decode embedded artifacts", "priority": 2, "depends": ["forensics_identify"]},
        {"id": "forensics_analyze", "desc": "Analyze extracted data for the flag", "priority": 3, "depends": ["forensics_extract"]},
    ],
    TaskCategory.MISC: [
        {"id": "misc_scan", "desc": "Scan the environment and identify all files/services", "priority": 1},
        {"id": "misc_identify", "desc": "Identify the challenge type and expected approach", "priority": 2, "depends": ["misc_scan"]},
        {"id": "misc_solve", "desc": "Apply the appropriate solve technique", "priority": 3, "depends": ["misc_identify"]},
    ],
}


# ── Reasoner ──────────────────────────────────────────────────────────────


class Reasoner:
    """分析器 — 负责类别判断、任务分解、计划修订。

    三阶段：
    1. initial_plan — 使用 AutoPrompter 结果制定初始计划
    2. evaluate_and_revise — 评估执行结果并修订
    3. 内部辅助方法: _detect_category / _decompose / _switch_strategy / _adjust_with_facts
    """

    def __init__(self, blackboard=None, budget_tracker=None):
        self.blackboard = blackboard
        self.budget_tracker = budget_tracker
        self._round = 0
        self._stuck_rounds = 0
        self._category: Optional[TaskCategory] = None

    def initial_plan(
        self, challenge: Any, env_info: Any = None
    ) -> Plan:
        """使用 AutoPrompter 结果或挑战元信息制定初始计划。"""
        cat = self._detect_category(challenge, env_info)
        self._category = cat
        tasks = self._decompose(cat, challenge, env_info)
        desc = f"Initial plan for {cat.value}: {len(tasks)} tasks"
        return Plan(category=cat, tasks=tasks, round=0, description=desc)

    def evaluate_and_revise(
        self, feedback: list[TaskResult]
    ) -> Plan:
        """评估执行结果并修订计划。

        Args:
            feedback: 已完成任务的执行结果列表

        Returns:
            Plan: 修订后的计划（或 Plan.done 表示完成）
        """
        self._round += 1

        # 检查是否有 flag 找到
        for r in feedback:
            if r.flag_found:
                return Plan.done(flag=r.flag or "found")

        # 检查是否卡住
        stuck_count = sum(1 for r in feedback if r.is_stuck)
        if stuck_count >= 2 or self._maybe_stuck():
            self._stuck_rounds += 1
            if self._stuck_rounds >= 2:
                return self._switch_strategy()

        # 根据新发现调整计划
        return self._adjust_with_facts(feedback)

    def _detect_category(self, challenge: Any, env_info: Any) -> TaskCategory:
        """判断题目类别。

        优先级：env_info.category_hint > 文件扩展名 > 默认 MISC。
        """
        # 尝试从 env_info 的 category_hint 获取
        if env_info is not None:
            hint = getattr(env_info, "category_hint", "") or ""
            if hint:
                hint_lower = hint.lower().strip()
                for cat in TaskCategory:
                    if cat.value == hint_lower:
                        return cat
            # 尝试从文件列表推断
            files = getattr(env_info, "files", []) or []
            for f in files:
                ext = getattr(f, "extension", "") or ""
                ftype = getattr(f, "file_type", "") or ""
                for cat in TaskCategory:
                    if cat.value in ext.lower() or cat.value in ftype.lower():
                        return cat
        # 从 challenge 元信息获取
        if challenge is not None:
            cat_str = getattr(challenge, "category", "") or ""
            if cat_str:
                cat_lower = cat_str.lower().strip()
                for cat in TaskCategory:
                    if cat.value == cat_lower:
                        return cat
        return TaskCategory.MISC

    def _decompose(
        self, category: TaskCategory, challenge: Any, env_info: Any
    ) -> list[Task]:
        """按类别分解任务。"""
        tasks: list[Task] = []
        definitions = _CATEGORY_DECOMPOSE.get(category, _CATEGORY_DECOMPOSE[TaskCategory.MISC])
        for d in definitions:
            tasks.append(Task(
                id=d["id"],
                category=category,
                description=d["desc"],
                depends_on=d.get("depends", []),
                priority=d.get("priority", 5),
            ))
        return tasks

    def _switch_strategy(self) -> Plan:
        """卡住时切换方向。"""
        cat = self._category or TaskCategory.MISC
        # 切换策略：换个角度/用不同工具
        alt_tasks: list[Task] = []
        if cat == TaskCategory.PWN:
            alt_tasks.append(Task(id="pwn_alt_rop", category=cat, description="Try ROP chain approach", priority=1))
            alt_tasks.append(Task(id="pwn_alt_heap", category=cat, description="Try heap exploitation approach", priority=2))
        elif cat == TaskCategory.REV:
            alt_tasks.append(Task(id="rev_alt_emu", category=cat, description="Try emulation-based analysis", priority=1))
            alt_tasks.append(Task(id="rev_alt_debug", category=cat, description="Try dynamic debugging", priority=2))
        elif cat == TaskCategory.WEB:
            alt_tasks.append(Task(id="web_alt_rce", category=cat, description="Try RCE/SSRF approach", priority=1))
            alt_tasks.append(Task(id="web_alt_auth", category=cat, description="Try authentication bypass", priority=2))
        else:
            alt_tasks.append(Task(id="alt_approach", category=cat, description="Try alternative approach (different tool/angle)", priority=1))

        self._stuck_rounds = 0
        return Plan(
            category=cat,
            tasks=alt_tasks,
            round=self._round,
            description=f"Strategy switch (stuck after round {self._round})",
        )

    def _adjust_with_facts(self, feedback: list[TaskResult]) -> Plan:
        """根据新发现调整计划。"""
        cat = self._category or TaskCategory.MISC
        # 收集新发现
        new_facts: list[str] = []
        for r in feedback:
            new_facts.extend(r.new_facts or [])

        # 生成新任务
        follow_up_tasks: list[Task] = []
        if new_facts:
            follow_up_tasks.append(Task(
                id=f"follow_up_{self._round}",
                category=cat,
                description=f"Follow up on findings: {'; '.join(new_facts[:3])}",
                priority=1,
            ))
        else:
            # 没有新发现，重试核心任务
            follow_up_tasks = self._decompose(cat, None, None)

        return Plan(
            category=cat,
            tasks=follow_up_tasks,
            round=self._round,
            description=f"Revised plan based on feedback (round {self._round})",
        )

    def _maybe_stuck(self) -> bool:
        """启发式：是否可能卡住（当前在第 3 轮以上）。"""
        return self._round >= 3


__all__ = [
    "Plan",
    "Reasoner",
    "Task",
    "TaskCategory",
    "TaskResult",
]