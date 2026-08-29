"""FuLiLian 知识层 — 知识卡注入 + 检索集成 (F3-001 / F3-002).

在 solver 启动时根据题目分类自动注入对应知识卡，
同时集成 Des-CTF-Knowledge FTS5 检索。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# skills/ctf-knowledge/ 目录路径（相对于项目根）
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "ctf-knowledge"

CATEGORIES = {
    "web": "web.md",
    "crypto": "crypto.md",
    "reverse": "reverse.md",
    "pwn": "pwn.md",
    "forensics": "forensics.md",
    "misc": "misc.md",
}


def get_knowledge_card(category: str) -> Optional[str]:
    """获取指定分类的知识卡 Markdown 内容。

    Args:
        category: 题目分类（web/crypto/reverse/pwn/forensics/misc）

    Returns:
        str | None: 知识卡内容，分类不存在返回 None
    """
    filename = CATEGORIES.get(category.lower())
    if not filename:
        return None
    card_path = SKILLS_DIR / filename
    if card_path.exists():
        return card_path.read_text(encoding="utf-8")
    return None


def inject_knowledge_card(category: str, system_prompt: str) -> str:
    """根据题目分类将知识卡注入系统提示。

    Args:
        category: 题目分类
        system_prompt: 原始系统提示

    Returns:
        str: 注入知识卡后的系统提示
    """
    card = get_knowledge_card(category)
    if card:
        # 在系统提示末尾追加知识卡，用分隔线隔开
        return system_prompt.rstrip() + "\n\n---\n\n" + card
    return system_prompt