"""FuLiLian 知识层 — 知识卡注入 + 检索集成 (F3-001 / F3-002).

在 solver 启动时根据题目分类自动注入对应知识卡，
同时集成 Des-CTF-Knowledge FTS5 检索。

注入顺序（inject_ctf_context 统一入口）：
1. playbook.md（通用 CTF 解题 playbook，存在才注入，位于知识卡之前）
2. 分类知识卡（web/crypto/reverse/pwn/forensics/misc）
3. 历史失败教训（experiential_learning.get_avoid_list）
4. 相似历史 WP 参考（knowledge_retriever.search top-3，题面关键词优先）

所有环节均为 best-effort：检索失败/文件缺失/DB 空时静默降级，
绝不让 solve 因此崩溃；检索块严格限体积（每条 title+snippet≤300 字符
+路径，最多 3 条）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# skills/ctf-cards/ 目录路径（相对于项目根）
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "ctf-cards"

# 通用解题 playbook（注入在知识卡之前）
PLAYBOOK_PATH = SKILLS_DIR / "playbook.md"

CATEGORIES = {
    "web": "web.md",
    "crypto": "crypto.md",
    "reverse": "reverse.md",
    "pwn": "pwn.md",
    "forensics": "forensics.md",
    "misc": "misc.md",
}

# 检索注入体积限制
_MAX_WP_REFS = 3          # 最多 3 条 WP 参考
_MAX_REF_CHARS = 300      # 每条 title+snippet 合计上限（路径另计）
_MAX_AVOID_ITEMS = 10     # 历史教训最多条数
_MAX_QUERY_TOKENS = 8     # （P4.2 起口径以 knowledge_retriever.sanitize_match_query 为准）

_CJK_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

# FTS5 MATCH 保留操作符词：裸出现在 token 序列里是语法错误
_FTS_OPERATOR_WORDS = {"and", "or", "not", "near"}

# 注入幂等 sentinel：以代码常量判断，不依赖文档文案是否被改动
_CONTEXT_MARKER = "<!-- fulilian:ctf-context -->"


def get_knowledge_card(category: str) -> Optional[str]:
    """获取指定分类的知识卡 Markdown 内容。

    Args:
        category: 题目分类（web/crypto/reverse/pwn/forensics/misc）

    Returns:
        str | None: 知识卡内容，分类不存在返回 None
    """
    filename = CATEGORIES.get((category or "").lower())
    if not filename:
        return None
    card_path = SKILLS_DIR / filename
    if card_path.exists():
        return card_path.read_text(encoding="utf-8")
    return None


def get_playbook() -> str:
    """读取通用 CTF 解题 playbook；文件缺失/读取失败返回空串。"""
    try:
        if PLAYBOOK_PATH.exists():
            content = PLAYBOOK_PATH.read_text(encoding="utf-8")
            return content if content.strip() else ""
    except OSError:
        pass
    return ""


def _sanitize_query(text: str) -> str:
    """把题面文本清洗成 FTS5 MATCH 友好的查询串。

    P4.2 起实现下沉到 ``knowledge_retriever.sanitize_match_query``（sanitize
    必须在 ``search()`` 内部生效才是不变量，任何入口进来都不该崩）；
    本函数保留为兼容壳，口径/常量（_MAX_QUERY_TOKENS 等）以那边为准。
    """
    from .knowledge_retriever import sanitize_match_query

    return sanitize_match_query(text)


def _format_lessons_block(category: str) -> str:
    """构造「历史失败教训」块；无教训/查询异常返回空串。"""
    try:
        from .experiential_learning import get_avoid_list

        avoid = [t for t in get_avoid_list(category) if t][: _MAX_AVOID_ITEMS]
    except Exception:  # noqa: BLE001 — 经验查询失败不阻断注入
        return ""
    if not avoid:
        return ""
    lines = "\n".join(f"- {t}" for t in avoid)
    return (
        "\n\n## 历史失败教训（avoid list — 该分类下这些做法曾失败，别再犯）\n"
        + lines
    )


def _wp_query_tokens(query_text: str) -> list[str]:
    """从 sanitize 后的 FTS 查询串还原裸 token（去引号与 OR 操作符）。"""
    return [t for t in re.findall(r'"([^"]+)"', query_text) if t]


def _wp_refs_relevance_floor(token_count: int) -> int:
    """相关性闸门的命中下限：题面 token 数 >=2 时要求命中 >=2 个。

    检索查询是题面 token 的 OR 连接（``_sanitize_query``），任一弱 token
    命中即可入选——「注入」这类高频二字词命中数百篇 WP，靠 bm25/LIMIT
    兜出来的 3 条与题面相关度约等于随机（§3.E 实测为噪声）。要求至少
    2 个不同 token 同时出现在结果的 title+snippet 里，把"沾一个词就
    入选"的噪声挡在注入之外；单 token 查询（已过特异性闸门）仍按 1 判。
    噪声比沉默更贵：全数不过线就注入空。
    """
    return min(2, max(1, token_count))


def _format_topic_segments_block(query_text: str, category: str) -> str:
    """构造「专题速查」块：标题自建段索引的行号直达指针（P4.3）。

    指针形态沿用语料库的按需分段读取约定（``Read offset=行号``），但行号
    来自运行时标题扫描而非手工 ``*.idx.md``——后者行号已实测漂移 32%
    （见计划书 §9 P4.3 探针条目）。相关性闸门在段匹配器内部（命中资格 =
    >=2 个不同查询 token 出现在标题，或单个 len>=3 的具体 token），域外
    查询（pwn/crypto/reverse 等无专题库覆盖）返回空——噪声比沉默更贵。
    """
    # 特异性闸门：查询退化为裸分类词（题面缺失时的回退形态）时直接不注入
    from .knowledge_retriever import _MATCH_OPERATOR_WORDS
    from .topic_segments import _TOKEN_RE, match_topic_segments

    cat_l = (category or "").strip().lower()
    qtokens = [
        t
        for t in _TOKEN_RE.findall(query_text.lower())
        if len(t) >= 2 and t not in _MATCH_OPERATOR_WORDS
    ]
    if cat_l and [t.lower() for t in qtokens] == [cat_l]:
        return ""
    try:
        from .topic_segments import match_topic_segments

        segs = match_topic_segments(query_text, category=category, limit=2)
    except Exception:  # noqa: BLE001 — 索引失败静默降级
        return ""
    if not segs:
        return ""
    lines = [
        f"- {s.doc} · {s.title}（L{s.line} 起）\n  Read {s.doc_path} offset={s.line}"
        for s in segs
    ]
    return "\n\n## 专题速查（技术专题文档，行号直达可分段读取）\n" + "\n".join(lines)


def _format_wp_refs_block(query_text: str, category: str) -> str:
    """构造「相似历史 WP 参考」块；无结果/检索异常/不过相关性闸门返回空串。

    体积控制：每条 title+snippet 合计截断到 _MAX_REF_CHARS，
    路径单独一行；最多 _MAX_WP_REFS 条。

    相关性闸门（两级，噪声比沉默更贵）：
    1. 特异性：查询退化为裸分类词（题面缺失时 ``inject_ctf_context``
       的回退形态，如 "web"）时直接不检索——它命中的是该分类下任意
       N 篇，纯噪声。
    2. 命中下限：结果的 title+snippet 须包含 >= _wp_refs_relevance_floor
       个不同查询 token。
    """
    tokens = _wp_query_tokens(query_text)
    if not tokens:
        return ""
    cat = (category or "").strip().lower()
    if cat and [t.lower() for t in tokens] == [cat]:
        return ""
    floor = _wp_refs_relevance_floor(len(tokens))

    try:
        from .knowledge_retriever import search

        results = search(
            query=query_text,
            category=category or None,
            limit=_MAX_WP_REFS,
            auto_build=True,
        )
    except Exception:  # noqa: BLE001 — 检索失败静默降级
        return ""
    if not results:
        return ""

    tokens_lower = [t.lower() for t in tokens]
    lines = []
    for r in results[:_MAX_WP_REFS]:
        title = str(r.get("title") or "").strip()
        snippet = " ".join(str(r.get("snippet") or "").split())
        hits = sum(
            1 for t in tokens_lower if t in title.lower() or t in snippet.lower()
        )
        if hits < floor:
            continue
        combined = f"{title} — {snippet}" if snippet else title
        if len(combined) > _MAX_REF_CHARS:
            combined = combined[: _MAX_REF_CHARS - 1] + "…"
        src = str(r.get("source_path") or "").strip()
        lines.append(f"- {combined}\n  ({src})" if src else f"- {combined}")
    if not lines:
        return ""
    return (
        "\n\n## 相似历史 WP 参考（来自 Des-CTF-Knowledge，可参考其思路）\n"
        + "\n".join(lines)
    )


def inject_ctf_context(
    category: str,
    prompt: str,
    query: Optional[str] = None,
) -> str:
    """统一知识注入入口：playbook + 知识卡 + 历史教训 + 专题速查 + 相似 WP 检索。

    Args:
        category: 题目分类（web/crypto/reverse/pwn/forensics/misc，可为空）
        prompt: 要 enrich 的提示文本。P8 修正：旧参数名 ``system_prompt``
            是谎言 —— 实际调用方传的多是**首个 user 消息**（solver.py/cli.py
            的 "Solve the CTF challenge..."），specialist/base.py 传的才是
            拼好的 specialist prompt 块。注入统一追加到这段文本之后。
        query: 可选题面关键词（标题/描述等）。检索优先使用它构造查询，
               缺失时回退到纯 category 词。

    Returns:
        str: 注入后的提示；所有环节失败时原样返回。
    """
    # 幂等守卫：specialist prompt 经 dispatcher 拼进 description 后，
    # solver 侧会再调一次注入。已含注入 sentinel 时跳过，避免双份。
    if _CONTEXT_MARKER in prompt:
        return prompt

    blocks: list[str] = []

    # 1) playbook —— 无条件注入（存在才注入），位于知识卡之前
    playbook = get_playbook()
    if playbook:
        blocks.append(playbook)

    # 2) 分类知识卡
    card = get_knowledge_card(category)
    if card:
        blocks.append(card)

    # 3) 历史失败教训 + 4) 相似 WP 参考（均 best-effort、限体积）
    cat = (category or "").strip()
    if cat:
        lessons = _format_lessons_block(cat)
        if lessons:
            blocks.append(lessons)

    query_text = _sanitize_query(query or "") or (cat or "")
    if query_text:
        quick = _format_topic_segments_block(query_text, cat)
        if quick:
            blocks.append(quick)
        refs = _format_wp_refs_block(query_text, cat)
        if refs:
            blocks.append(refs)

    if not blocks:
        return prompt
    # sentinel 打头，供幂等守卫识别（见 _CONTEXT_MARKER）
    return (
        prompt.rstrip()
        + "\n\n---\n\n"
        + _CONTEXT_MARKER
        + "\n\n"
        + "\n\n---\n\n".join(blocks)
    )


def inject_knowledge_card(
    category: str,
    system_prompt: str,
    query: Optional[str] = None,
) -> str:
    """根据题目分类将知识卡注入系统提示（兼容入口，委托 inject_ctf_context）。

    Args:
        category: 题目分类
        system_prompt: 原始系统提示
        query: 可选题面关键词（标题/描述），用于相似 WP 检索

    Returns:
        str: 注入后的系统提示
    """
    return inject_ctf_context(category, system_prompt, query=query)
