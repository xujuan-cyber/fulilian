"""知识层检索 (F3-002) 单元测试 — 对应实施指南 08 验证方式清单。

所有测试通过 tmp_path + monkeypatch 覆盖模块常量 kr.KB_PATH / kr.DB_PATH，
在合成知识库（若干小 .md 文件）上运行，不触碰真实知识库与生产索引。
注意：常量必须通过模块属性（kr.DB_PATH）引用，不能按值 import，
否则 monkeypatch 后测试内引用的仍是旧绑定。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import fulilian_ctf.knowledge_retriever as kr


# ── 合成知识库 ───────────────────────────────────────────────────────────

# 应入库的正文文档数（不含 demo.idx.md / empty.md / README.md）
EXPECTED_DOC_COUNT = 5


def _make_synthetic_kb(kb_root: Path) -> None:
    """构造小型合成知识库：覆盖中英文关键词 + 跳过逻辑（.idx.md/空文件/README）。"""
    docs = {
        "challenges/web/sql-injection-tutorial.md": (
            "SQL injection vulnerability tutorial. SQL注入 联合查询绕过登录。"
            "Use union select to bypass the login form. path traversal is related."
        ),
        "challenges/crypto/rsa-encryption.md": (
            "RSA加密与低指数攻击。RSA encryption with small public exponent e=3."
            "模运算 素数分解 是常见思路。"
        ),
        "challenges/pwn/stack-overflow-notes.md": (
            "栈溢出基础。Buffer overflow on the stack, ret2libc and shellcode."
        ),
        "challenges/forensics/pcap-analysis.md": (
            "流量取证入门。Wireshark pcap 流量分析 memory forensics."
        ),
        "challenges/misc/plain-notes.md": (
            "这是一篇普通的读书笔记，内容与安全无关。"
            "本文包含 FTS\" OR ( 用于验证 LIKE 回退搜索。"
        ),
        # 分段索引文件：应被跳过（回归验证 endswith('.idx.md') 过滤）
        "demo.idx.md": "分段的索引文件，不应被索引进 DB。",
        # 空文件：应被跳过
        "empty.md": "",
    }
    for rel, content in docs.items():
        p = kb_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    # SKIP_FILES 命中：README.md 也不应入库
    (kb_root / "README.md").write_text("readme 内容", encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_knowledge_env(tmp_path, monkeypatch):
    """每个测试使用独立 tmp 知识库与 DB，绝不读写真实 KB / 生产索引。"""
    kb_root = tmp_path / "kb"
    db_path = tmp_path / "kb.db"
    _make_synthetic_kb(kb_root)
    monkeypatch.setattr(kr, "KB_PATH", kb_root)
    monkeypatch.setattr(kr, "DB_PATH", db_path)
    yield


# ── 1. 分类推断 ──────────────────────────────────────────────────────────


class TestGuessCategory:
    def test_web_from_path(self):
        assert kr._guess_category(Path("challenges/web-sqli/index.md")) == "web"

    def test_crypto_from_path(self):
        assert kr._guess_category(Path("challenges/crypto-rsa/index.md")) == "crypto"

    def test_reverse_from_path(self):
        assert kr._guess_category(Path("challenges/reverse-apk/index.md")) == "reverse"

    def test_pwn_from_path(self):
        assert kr._guess_category(Path("challenges/pwn-stack/index.md")) == "pwn"

    def test_forensics_from_path(self):
        assert kr._guess_category(Path("challenges/forensics-pcap/index.md")) == "forensics"

    def test_misc_fallback(self):
        assert kr._guess_category(Path("challenges/unknown/index.md")) == "misc"

    def test_content_keywords_web(self):
        p = Path("challenges/unknown/index.md")
        content = "SQL injection vulnerability in the login form"
        assert kr._guess_category(p, content) == "web"

    def test_content_keywords_crypto(self):
        p = Path("challenges/unknown/index.md")
        content = "RSA encryption with small exponent attack"
        assert kr._guess_category(p, content) == "crypto"


# ── 2. FTS5 索引构建 ─────────────────────────────────────────────────────


class TestBuildIndex:
    def test_build_index_creates_db(self):
        assert not kr.DB_PATH.exists()
        count = kr.build_index()
        assert kr.DB_PATH.exists()
        assert count == EXPECTED_DOC_COUNT  # 合成 KB 的精确文档数

    def test_build_index_returns_count(self):
        count = kr.build_index()
        assert count == EXPECTED_DOC_COUNT

    def test_build_index_idempotent(self):
        c1 = kr.build_index()
        c2 = kr.build_index()  # 非 force 模式，数据已存在应返回相同 count
        assert c2 == c1 == EXPECTED_DOC_COUNT

    def test_build_index_force_rebuild(self):
        c1 = kr.build_index()
        c2 = kr.build_index(force=True)
        assert c2 == c1 == EXPECTED_DOC_COUNT  # 重建后应相同

    def test_db_has_fts5_table(self):
        kr.build_index()
        conn = sqlite3.connect(str(kr.DB_PATH))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert any("writeups" in str(t) for t in tables)


# ── 3. FTS5 检索 ────────────────────────────────────────────────────────


class TestSearch:
    def test_search_english(self):
        kr.build_index()
        results = kr.search("path traversal", limit=3)
        assert len(results) > 0
        assert results[0]["title"]
        assert results[0]["category"]
        assert results[0]["source_path"]

    def test_search_chinese(self):
        kr.build_index()
        results = kr.search("SQL注入", limit=3)
        assert len(results) > 0

    def test_search_with_category_filter(self):
        kr.build_index()
        results = kr.search("RSA", category="crypto", limit=5)
        assert len(results) > 0
        for r in results:
            assert r["category"] == "crypto"

    def test_search_no_results(self):
        kr.build_index()
        results = kr.search("zzzzz_nonexistent_keyword_xxxxx", limit=3)
        assert len(results) == 0

    def test_search_limit(self):
        kr.build_index()
        results = kr.search("SQL", limit=2)
        assert len(results) <= 2

    def test_search_auto_build(self):
        """auto_build=True 但 DB 不存在时应自动构建。"""
        assert not kr.DB_PATH.exists()
        results = kr.search("RSA", auto_build=True)
        assert len(results) > 0

    def test_search_no_auto_build(self):
        """auto_build=False 且 DB 不存在时返回空。"""
        results = kr.search("RSA", auto_build=False)
        assert len(results) == 0

    def test_like_fallback_on_fts_syntax_error(self):
        """FTS5 语法错误时应回退到 LIKE 搜索并命中包含原文的文档。"""
        kr.build_index()
        # 未闭合引号触发 FTS5 语法错误 → LIKE '%FTS" OR (%'
        results = kr.search('FTS" OR (', limit=5)
        assert len(results) == 1
        assert results[0]["source_path"].endswith("plain-notes.md")


# ── 4. 索引统计 ──────────────────────────────────────────────────────────


class TestIndexStats:
    def test_get_index_stats(self):
        kr.build_index()
        stats = kr.get_index_stats()
        assert stats["total_docs"] == EXPECTED_DOC_COUNT
        assert "by_category" in stats
        assert "db_path" in stats
        assert stats["db_path"] == str(kr.DB_PATH)

    def test_get_index_stats_empty_db(self):
        """DB 不存在时返回零值。"""
        stats = kr.get_index_stats()
        assert stats["total_docs"] == 0
        assert stats["by_category"] == {}

    def test_list_categories(self):
        kr.build_index()
        cats = kr.list_categories()
        assert set(cats) == {"web", "crypto", "pwn", "forensics", "misc"}
        assert "web" in cats

    def test_list_categories_empty(self):
        cats = kr.list_categories()
        assert cats == []


# ── 5. 检索结果格式 ──────────────────────────────────────────────────────


class TestSearchResultFormat:
    def test_result_has_required_fields(self):
        kr.build_index()
        results = kr.search("shellcode", limit=1)
        assert len(results) == 1
        r = results[0]
        assert "title" in r
        assert "category" in r
        assert "snippet" in r or True  # snippet 可选
        assert "source_path" in r

    def test_result_source_path_exists(self):
        kr.build_index()
        results = kr.search("shellcode", limit=1)
        assert len(results) == 1
        path = Path(results[0]["source_path"])
        assert path.exists() or path.suffix == ".md"


# ── 6. 跳过逻辑回归 ─────────────────────────────────────────────────────


class TestSkipRulesRegression:
    def test_idx_md_not_indexed(self):
        """回归：.idx.md 文件不应被索引进 DB（按 source_path 查询计数）。

        注意：knowledge_retriever.py 曾用 `md_file.suffix in SKIP_SUFFIXES`
        判断，对 "x.idx.md" 永远不命中（suffix 是 ".md"）。
        """
        count = kr.build_index()
        conn = sqlite3.connect(str(kr.DB_PATH))
        idx_rows = conn.execute(
            "SELECT count(*) FROM writeups WHERE source_path LIKE '%.idx.md'"
        ).fetchone()[0]
        total = conn.execute("SELECT count(*) FROM writeups").fetchone()[0]
        conn.close()
        assert idx_rows == 0
        assert total == count == EXPECTED_DOC_COUNT

    def test_empty_and_skip_files_not_indexed(self):
        """空文件与 SKIP_FILES（README.md）不应入库。"""
        kr.build_index()
        conn = sqlite3.connect(str(kr.DB_PATH))
        for pattern in ("%/empty.md", "%README.md"):
            n = conn.execute(
                "SELECT count(*) FROM writeups WHERE source_path LIKE ?", (pattern,)
            ).fetchone()[0]
            assert n == 0, f"{pattern} 不应被索引"
        conn.close()
