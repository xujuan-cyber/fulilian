"""BaseSpecialist — 分类专家 Agent 基类。

每个 Specialist 封装一类 CTF 题目的专业工具链、知识卡和工作流。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


class BaseSpecialist(ABC):
    """专家 Agent 基类。

    Attributes:
        category: 题目类别标识（pwn/rev/web/crypto/forensics/misc）
        tools: 该类别推荐的工具列表
        knowledge_cards: 加载的知识卡内容列表
        workflow: 建议的分析流程描述
    """

    def __init__(self) -> None:
        # 子类可能已在 __init__ 中设置了 category/tools/workflow，
        # 这里只补默认值，不覆盖子类已设置的值
        if not hasattr(self, "category"):
            self.category = ""
        if not hasattr(self, "tools"):
            self.tools: list[str] = []
        self.knowledge_cards: list[str] = []
        if not hasattr(self, "workflow"):
            self.workflow = ""
        self._load_knowledge()

    def _load_knowledge(self) -> None:
        """从知识卡文件加载该类别知识（若存在）。"""
        if not self.category:
            return
        try:
            from ..knowledge import get_knowledge_card

            card = get_knowledge_card(self.category)
            if card:
                self.knowledge_cards.append(card)
        except Exception:  # noqa: BLE001 — 知识卡加载失败不阻断
            pass

    def build_prompt(self, challenge: Any) -> str:
        """构建针对此类别专家的 system prompt。

        Args:
            challenge: 挑战上下文（Project 或类似对象）

        Returns:
            str: 注入知识卡后的专家 prompt
        """
        lines = [f"You are a CTF {self.category} specialist."]
        if self.tools:
            lines.append(f"\nRecommended tools: {', '.join(self.tools)}")
        if self.workflow:
            lines.append(f"\nSuggested workflow:\n{self.workflow}")
        if self.knowledge_cards:
            for card in self.knowledge_cards:
                lines.append(f"\n---\n{card[:2000]}")
        return "\n".join(lines)

    def verify_result(self, flag: str) -> bool:
        """验证 flag 是否通过三重校验门。

        Args:
            flag: 候选 flag 字符串

        Returns:
            bool: 是否 CONFIRMED
        """
        if not flag:
            return False
        try:
            from ..verify import VerificationResult, verify_flag

            return verify_flag(flag, evidence="", require_grounding=False) is VerificationResult.CONFIRMED
        except Exception:  # noqa: BLE001
            return False