"""专题分段索引 (P4.3) 单元测试。

所有测试通过 tmp_path + monkeypatch 覆盖 kr._resolve_kb_path（段索引的
语料库根解析入口），在合成专题文档上运行，不触碰真实知识库。
注意：match_topic_segments 在调用时才 import _resolve_kb_path，
因此 monkeypatch kr 模块属性即可生效。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import fulilian_ctf.knowledge_retriever as kr
import fulilian_ctf.topic_segments as ts
from fulilian_ctf.knowledge import _format_topic_segments_block, inject_ctf_context


# ── 合成专题库 ──────────────────────────────────────────────────────────

SQL_DOC = """# SQL 专题

## 联合注入Payload

union select 用法正文。

## 宽字节注入

GBK 编码吃掉反斜杠正文。

## 这是一条以句号结尾的叙述标题。

不应进索引。

## 概念

二字短标题。

## 过滤or and xor not 绕过

操作符词命名的真实标题形态（回归 P4.3 联调试跑时发现的误报源）。
"""

JWT_DOC = """# JWT 专题

## JWT（JSON Web Token）安全

正文。

## IDAT 数据块

图片数据块标题：ida 不应命中 IDAT，idat 应命中。
"""


@pytest.fixture()
def kb_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ctf-knowledge"
    root.mkdir()
    (root / "SQL.md").write_text(SQL_DOC, encoding="utf-8")
    (root / "JWT.md").write_text(JWT_DOC, encoding="utf-8")
    # 专题映射之外的文档：不应进索引
    (root / "README.md").write_text("## 随便什么标题\n", encoding="utf-8")
    monkeypatch.setattr(kr, "_resolve_kb_path", lambda: str(root))
    return root


# ── 解析 ────────────────────────────────────────────────────────────────

def test_parse_filters_junk_headings(kb_root: Path) -> None:
    segs = ts._cached_segments(str(kb_root / "SQL.md"))
    titles = [s.title for s in segs]
    # 正常标题在
    assert "宽字节注入" in titles
    # 句号结尾的叙述标题被排除
    assert not any(t.endswith("。") for t in titles)
    # 行号是 1-based 且对准标题行
    wide = next(s for s in segs if s.title == "宽字节注入")
    lines = (kb_root / "SQL.md").read_text(encoding="utf-8").splitlines()
    assert lines[wide.line - 1] == "## 宽字节注入"
    assert wide.doc == "SQL"


def test_unmapped_docs_excluded(kb_root: Path) -> None:
    r = ts.match_topic_segments("随便什么标题", None, limit=5)
    assert r == []


def test_cache_invalidation_on_rewrite(kb_root: Path) -> None:
    p = kb_root / "SQL.md"
    before = ts._cached_segments(str(p))
    assert len(before) >= 1
    p.write_text("# SQL 专题\n\n## 全新标题甲乙丙丁\n", encoding="utf-8")
    # 强制 mtime 变化（同秒内 write 可能不变 mtime_ns）
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    after = ts._cached_segments(str(p))
    titles = [s.title for s in after]
    assert "全新标题甲乙丙丁" in titles
    assert "宽字节注入" not in titles  # 旧内容已失效


# ── 匹配规则 ────────────────────────────────────────────────────────────

def test_two_token_match_qualifies(kb_root: Path) -> None:
    # 联合 + 注入 两个 token 都在标题里
    r = ts.match_topic_segments("union 联合注入", "web", limit=5)
    assert any(s.title == "联合注入Payload" for s in r)


def test_single_specific_token_qualifies(kb_root: Path) -> None:
    # 宽字节 = 3 字具体词，单 token 即可命中
    r = ts.match_topic_segments("宽字节", "web", limit=5)
    assert [s.title for s in r].count("宽字节注入") >= 1


def test_single_generic_token_does_not_qualify(kb_root: Path) -> None:
    # 「注入」单独出现不入选（噪声比沉默更贵）
    assert ts.match_topic_segments("注入", "web", limit=5) == []
    assert ts.match_topic_segments("绕过", "web", limit=5) == []


def test_ascii_token_word_boundary(kb_root: Path) -> None:
    # ida 不得命中 IDAT（子串误报），须独立成词
    assert ts.match_topic_segments("ida", "web", limit=5) == []
    # idat 独立成词则命中（len>=3 单 token 有资格）
    r = ts.match_topic_segments("idat", "web", limit=5)
    assert any(s.doc == "JWT" and s.title.startswith("IDAT") for s in r)
    # jwt 独立成词则命中
    r = ts.match_topic_segments("jwt", "web", limit=5)
    assert any(s.doc == "JWT" for s in r)


def test_sanitized_query_operators_stripped(kb_root: Path) -> None:
    # sanitize 后的 OR 查询串：字面操作符 or/and 不是查询词，
    # 也不得帮标题（"过滤or and xor not 绕过"）攒命中数越过资格闸门
    q = '"绕过" OR "or" OR "and"'
    r = ts.match_topic_segments(q, "web", limit=5)
    assert all(s.title != "过滤or and xor not 绕过" for s in r)
    q2 = '"宽字节" OR "GBK"'
    r2 = ts.match_topic_segments(q2, "web", limit=5)
    assert [s.title for s in r2].count("宽字节注入") >= 1


def test_category_filter(kb_root: Path) -> None:
    # 分类不符 → 域外沉默
    assert ts.match_topic_segments("宽字节", "pwn", limit=5) == []
    # 分类相符 → 命中
    assert ts.match_topic_segments("宽字节", "web", limit=5) != []
    # 分类为空 → 不过滤
    assert ts.match_topic_segments("宽字节", None, limit=5) != []


def test_empty_query_and_missing_kb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ts.match_topic_segments("", "web") == []
    monkeypatch.setattr(kr, "_resolve_kb_path", lambda: None)
    assert ts.match_topic_segments("宽字节", "web") == []
    monkeypatch.setattr(
        kr, "_resolve_kb_path", lambda: str(tmp_path / "nonexistent")
    )
    assert ts.match_topic_segments("宽字节", "web") == []


def test_limit_and_ranking(kb_root: Path) -> None:
    r = ts.match_topic_segments("宽字节 GBK 注入", "web", limit=1)
    assert len(r) == 1
    # 双 token 命中（宽字节+注入）应排在单 token（宽字节）之前
    r = ts.match_topic_segments("宽字节 GBK 注入", "web", limit=5)
    assert r[0].title == "宽字节注入"


# ── 注入层 ──────────────────────────────────────────────────────────────

def test_block_format_has_read_pointer(kb_root: Path) -> None:
    block = _format_topic_segments_block("宽字节 GBK", "web")
    assert "## 专题速查" in block
    assert "Read " in block and "offset=" in block
    wide = next(s for s in ts._cached_segments(str(kb_root / "SQL.md"))
                if s.title == "宽字节注入")
    assert f"offset={wide.line}" in block


def test_block_bare_category_gate(kb_root: Path) -> None:
    # 裸分类词（题面缺失回退形态）直接沉默
    assert _format_topic_segments_block("web", "web") == ""
    # 题面只有 JWT.md 的 README 之类无关词 → 沉默
    assert _format_topic_segments_block("存在不存在的东西", "web") == ""


def test_inject_includes_topic_block_and_idempotent(kb_root: Path) -> None:
    out = inject_ctf_context("web", "Solve the challenge.", query="宽字节 GBK")
    assert "## 专题速查" in out
    # 幂等：已含 sentinel 的 prompt 原样返回
    assert inject_ctf_context("web", out, query="宽字节") == out


def test_inject_bare_category_no_topic_block(kb_root: Path) -> None:
    out = inject_ctf_context("web", "Solve the challenge.")
    assert "## 专题速查" not in out
