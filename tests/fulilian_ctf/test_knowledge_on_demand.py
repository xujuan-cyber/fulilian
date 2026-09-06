"""扩展包按需加载 (F4-007) 测试。

知识卡是懒加载的：只在求解对应分类的题时读取对应单张卡
（get_knowledge_card），CTF 技能不整体注入上下文。
"""

from __future__ import annotations

from fulilian_ctf.knowledge import CATEGORIES, SKILLS_DIR, get_knowledge_card, inject_knowledge_card


def test_unknown_category_returns_none():
    assert get_knowledge_card("nonexistent-cat") is None


def test_card_loaded_on_demand_only_for_category():
    """有卡的分类返回非空内容；无卡文件时返回 None（按需、不预载）。"""
    for cat in CATEGORIES:
        card = get_knowledge_card(cat)
        path = SKILLS_DIR / CATEGORIES[cat]
        if path.exists():
            assert card and card.strip()
        else:
            assert card is None


def test_inject_prefixes_prompt_when_card_missing():
    """无卡分类：原提示保留在前；playbook.md 存在时无条件注入。"""
    from fulilian_ctf.knowledge import get_playbook

    prompt = "BASE PROMPT"
    out = inject_knowledge_card("nonexistent-cat", prompt)
    assert out.startswith(prompt)  # 原提示保留在前，不丢失
    playbook = get_playbook()
    if playbook:
        assert out != prompt  # playbook 已注入
        assert playbook.strip().splitlines()[0] in out
    else:
        assert out == prompt  # playbook 缺失且无卡 → 原样返回
