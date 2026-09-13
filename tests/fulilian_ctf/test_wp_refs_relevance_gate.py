"""WP 参考相关性闸门 (计划书 P4.4) 回归测试。

修复前的问题：检索查询是题面 token 的 OR 连接，任一弱 token 命中即可
入选；「注入」这类高频二字词（FTS trigram 零命中 → LIKE 兜底）裸 LIMIT
按 rowid 返回的 3 条与题面相关度约等于随机，全部注入上下文成为噪声。

修复（两级闸门 + 兜底排序）：
1. ``knowledge._format_wp_refs_block`` 特异性闸门 —— 查询退化为裸分类词
   （题面缺失时的回退形态）时直接不检索。
2. ``knowledge._wp_refs_relevance_floor`` 命中下限 —— 结果的
   title+snippet 须包含 >= floor 个不同查询 token，否则丢弃。
3. ``knowledge_retriever._fallback_token_search`` —— LIKE OR 多取候选
   按「命中的不同 token 数」降序，附 ``score``；title+snippet 零命中的
   行（只在 content 深处命中）被过滤。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fulilian_ctf.knowledge import (
    _format_wp_refs_block,
    _wp_query_tokens,
    _wp_refs_relevance_floor,
)
import fulilian_ctf.knowledge_retriever as kr


# ---------------------------------------------------------------------------
# token 还原与命中下限（纯函数）
# ---------------------------------------------------------------------------


def test_query_tokens_extracts_quoted_terms():
    assert _wp_query_tokens('"sql注入" OR "union"') == ["sql注入", "union"]
    assert _wp_query_tokens("") == []
    assert _wp_query_tokens("web") == []  # 回退形态是裸分类词，无引号包裹


def test_relevance_floor_scales_with_token_count():
    assert _wp_refs_relevance_floor(0) == 1
    assert _wp_refs_relevance_floor(1) == 1   # 单 token（已过特异性闸门）按 1 判
    assert _wp_refs_relevance_floor(2) == 2
    assert _wp_refs_relevance_floor(8) == 2   # 封顶 2


# ---------------------------------------------------------------------------
# 特异性闸门 + 命中下限（mock 检索层，不触真实 DB）
# ---------------------------------------------------------------------------


@pytest.fixture
def search_calls(monkeypatch):
    """拦截 knowledge_retriever.search，记录调用并返回可配置结果。"""
    calls = []
    holder = {"results": []}

    def fake_search(*args, **kwargs):
        calls.append(kwargs)
        return holder["results"]

    monkeypatch.setattr(kr, "search", fake_search)
    return calls, holder


def test_category_only_query_never_searches(search_calls):
    """题面缺失时的回退形态（裸分类词）直接不检索——特异性闸门。"""
    calls, holder = search_calls
    holder["results"] = [{"title": "any-wp", "snippet": "web web web",
                          "source_path": "x"}]
    assert _format_wp_refs_block('"web"', "web") == ""
    assert calls == []  # 闸门在检索之前，一次都不该查


def test_category_gate_is_case_insensitive(search_calls):
    calls, _ = search_calls
    assert _format_wp_refs_block('"WEB"', "web") == ""


def test_multi_token_query_passes_gate_and_reaches_search(search_calls):
    calls, _ = search_calls
    _format_wp_refs_block('"sql注入" OR "union"', "web")
    assert len(calls) == 1


def test_results_below_hit_floor_are_dropped(search_calls):
    """只沾 1 个 token 的结果（floor=2）不得入选。"""
    calls, holder = search_calls
    holder["results"] = [
        {   # 只含 "union" —— 1 hit < floor(2) → 丢弃
            "title": "unrelated-writeup",
            "snippet": "some union query somewhere",
            "source_path": "a.md",
        },
        {   # 同时含 "sql注入" 与 "union" —— 2 hits → 保留
            "title": "zentao-sqli",
            "snippet": "禅道 SQL注入，union select 读文件",
            "source_path": "b.md",
        },
    ]
    block = _format_wp_refs_block('"sql注入" OR "union"', "web")
    assert "unrelated-writeup" not in block
    assert "zentao-sqli" in block


def test_all_below_floor_yields_empty_block(search_calls):
    """噪声比沉默更贵：全数不过线就注入空。"""
    _, holder = search_calls
    holder["results"] = [
        {"title": "t1", "snippet": "sql注入 only", "source_path": "a.md"},
        {"title": "t2", "snippet": "union only", "source_path": "b.md"},
    ]
    assert _format_wp_refs_block('"sql注入" OR "union"', "web") == ""


def test_search_failure_degrades_to_empty(search_calls, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(kr, "search", boom)
    assert _format_wp_refs_block('"sql注入" OR "union"', "web") == ""


def test_empty_search_results_yield_empty_block(search_calls):
    _, holder = search_calls
    holder["results"] = []
    assert _format_wp_refs_block('"sql注入" OR "union"', "web") == ""


# ---------------------------------------------------------------------------
# 兜底检索排序（临时 FTS5 DB，验证 score 降序 + 深处命中被过滤）
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_kb(monkeypatch, tmp_path):
    db = tmp_path / "knowledge.db"
    conn = sqlite3.connect(str(db))
    conn.execute(kr.CREATE_TABLE_SQL)
    rows = [
        # 双 token 命中 —— 应排第一
        ("dual-hit", "web", "sql注入 union select 复现", "dual.md"),
        # 单 token 命中 —— 排后
        ("single-hit", "web", "union 查询去重技巧", "single.md"),
        # 只在 content 深处命中 union —— title+snip(前200字符) 零命中 → 被过滤
        ("deep-only", "web", "x" * 300 + "union", "deep.md"),
    ]
    for title, cat, content, src in rows:
        conn.execute(
            "INSERT INTO writeups(title, category, content, source_path) "
            "VALUES (?, ?, ?, ?)",
            (title, cat, content, src),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(kr, "DB_PATH", db)
    return db


def test_fallback_orders_by_token_hits(tmp_kb):
    results = kr._fallback_token_search(["sql注入", "union"], limit=5)
    assert results, "临时库应有命中"
    assert results[0]["title"] == "dual-hit"
    assert results[0]["score"] == 2
    titles = [r["title"] for r in results]
    assert "dual-hit" in titles and "single-hit" in titles


def test_fallback_drops_deep_content_only_hits(tmp_kb):
    """只在 content 深处命中的行，title+snippet 零命中 → score 0 → 过滤。"""
    results = kr._fallback_token_search(["union"], limit=5)
    assert "deep-only" not in [r["title"] for r in results]
    assert all(r["score"] >= 1 for r in results)


def test_fallback_empty_tokens_returns_empty(tmp_kb):
    assert kr._fallback_token_search(["", "  "]) == []
