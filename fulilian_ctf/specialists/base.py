"""BaseSpecialist — 分类专家 Agent 基类。

每个 Specialist 封装一类 CTF 题目的专业工具链、知识卡和工作流。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


def _challenge_query(challenge: Any) -> Optional[str]:
    """从挑战对象里尽力提取检索关键词（标题+描述），拿不到返回 None。"""
    parts = (
        str(getattr(challenge, "title", "") or ""),
        str(getattr(challenge, "description", "") or ""),
    )
    query = " ".join(p for p in parts if p).strip()
    return query or None


class BaseSpecialist(ABC):
    """专家 Agent 基类。

    Attributes:
        category: 题目类别标识（pwn/rev/web/crypto/forensics/misc）
        tools: 该类别推荐的工具列表
        knowledge_cards: 加载的知识卡内容列表
        workflow: 建议的分析流程描述
        asset_discipline: 资产使用纪律（模板库/检索/脚本路由提示），可为空
    """

    def __init__(self) -> None:
        # 子类可能已在 __init__ 中设置了 category/tools/workflow/discipline，
        # 这里只补默认值，不覆盖子类已设置的值
        if not hasattr(self, "category"):
            self.category = ""
        if not hasattr(self, "tools"):
            self.tools: list[str] = []
        self.knowledge_cards: list[str] = []
        if not hasattr(self, "workflow"):
            self.workflow = ""
        if not hasattr(self, "asset_discipline"):
            self.asset_discipline = ""
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

        知识注入统一走 knowledge.inject_ctf_context
        （playbook → 知识卡 → 历史失败教训 → 相似 WP 参考），
        检索关键词优先取挑战标题+描述。知识层任何异常都回退到
        本地知识卡（截断 2000 字符）的旧行为，绝不阻断专家 prompt。

        Args:
            challenge: 挑战上下文（Project 或类似对象）

        Returns:
            str: 注入知识上下文后的专家 prompt
        """
        lines = [f"You are a CTF {self.category} specialist."]
        if self.tools:
            lines.append(f"\nRecommended tools: {', '.join(self.tools)}")
        if self.workflow:
            lines.append(f"\nSuggested workflow:\n{self.workflow}")
        discipline = (self.asset_discipline or "").strip()
        if discipline:
            lines.append(f"\nAsset usage discipline:\n{discipline}")
        base = "\n".join(lines)
        try:
            from ..knowledge import inject_ctf_context

            return inject_ctf_context(
                self.category, base, query=_challenge_query(challenge)
            )
        except Exception:  # noqa: BLE001 — 知识层异常不能炸 specialist
            for card in self.knowledge_cards:
                base += f"\n---\n{card[:2000]}"
            return base

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