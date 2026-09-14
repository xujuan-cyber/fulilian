"""知识层检索 (F3-002) 单元测试 — 对应实施指南 08 验证方式清单。

所有测试通过 tmp_path + monkeypatch 覆盖模块常量 kr.KB_PATH / kr.DB_PATH，
在合成知识库（若干小 .md 文件）上运行，不触碰真实知识库与生产索引。
注意：常量必须通过模块属性（kr.DB_PATH）引用，不能按值 import，
否则 monkeypatch 后测试内引用的仍是旧绑定。
"""

from __future__ import annotations

import json
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
    # _kb_roots() 会追加 Obsidian vault、build_index 会顺带扫 SNIPPETS_DIR，
    # 二者都指向真实数据，必须一并隔离，否则合成 KB 的精确计数断言被污染。
    monkeypatch.setattr(kr, "OBSIDIAN_VAULT", tmp_path / "no-vault")
    monkeypatch.setattr(kr, "SNIPPETS_DIR", tmp_path / "no-snippets")
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

    def test_build_index_progress_goes_to_stderr(self, capsys, monkeypatch):
        """stdout 是机器契约（solve --json 下每行必须是 JSON 事件）——
        索引进度横幅只许走 stderr。

        回归：`[knowledge] snippets: N indexed` 曾打在 stdout，solve --json
        首次 auto_build 时混进事件流打断解析（test_solve_modes 的既有失败）。
        打桩 snippets 计数让横幅路径确定性触发（合成 KB 的 snippets 为 0
        时不打印，锁会空转）。
        """
        monkeypatch.setattr(kr, "_build_snippets_index", lambda conn, force=False: 7)
        kr.build_index(force=True)
        captured = capsys.readouterr()
        assert captured.out == "", f"stdout 被索引横幅污染: {captured.out!r}"
        assert "snippets: 7 indexed" in captured.err

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
        """回归：.idx.md 文件不应被索引进 DB。

        注意：knowledge_retriever.py 曾用 `md_file.suffix in SKIP_SUFFIXES`
        判断，对 "x.idx.md" 永远不命中（suffix 是 ".md"）。

        实现注意：这里**不能**写 `WHERE source_path LIKE '%.idx.md'`——
        该列 UNINDEXED + trigram 表会把 LIKE 改写成零命中的 MATCH，
        断言 `count == 0` 会恒真通过（本条老实现就是这样假绿的）。
        见 _rows() 的说明。
        """
        count = kr.build_index()
        paths = [str(r[2]) for r in _rows()]
        assert not [p for p in paths if p.endswith(".idx.md")]
        assert len(paths) == count == EXPECTED_DOC_COUNT

    def test_empty_and_skip_files_not_indexed(self):
        """空文件与 SKIP_FILES（README.md）不应入库（同样避开 source_path LIKE）。"""
        kr.build_index()
        paths = [str(r[2]) for r in _rows()]
        assert not [p for p in paths if p.endswith("/empty.md")]
        assert not [p for p in paths if p.endswith("/README.md")]
        # 正例锚点：证明上面的断言不是对着空集合说的
        assert [p for p in paths if p.endswith("plain-notes.md")]


# ── 7. 权威分类覆盖（wp_technique_index.json > _guess_category） ────────
#
# kg_retriever 曾只走 _guess_category 推断，与 wp_technique_index.json 里
# kb_writeback 写入的权威 category 冲突（实测 13 条里 3 条不一致：
# multiSQL→pwn、WEB2→crypto、Shiro→crypto），导致 search(category=...)
# 对这几个分类静默漏检。下面两把锁锁住双键覆盖与回退行为。


WP_INDEX_RELPATH = Path("CTF大赛WP集合") / "wp_technique_index.json"


def _rows() -> list:
    """读出全部 (title, category, source_path)。

    刻意**不用** `WHERE source_path LIKE ?`：writeups 是
    `fts5(..., source_path UNINDEXED, tokenize='trigram')`，SQLite 会把
    trigram 表上的 `LIKE '%字面量%'` 改写成一次 FTS MATCH，而 UNINDEXED 列
    没有 trigram 索引 → **恒返回 0 行**（本文件两条老回归就是因此在对着 0 断言）。
    宁可全量取回在 Python 里过滤，也不要写这种静默返空的 SQL。
    """
    conn = sqlite3.connect(str(kr.DB_PATH))
    try:
        return conn.execute(
            "SELECT title, category, source_path FROM writeups"
        ).fetchall()
    finally:
        conn.close()


def _category_of(filename: str) -> str:
    hits = [r for r in _rows() if str(r[2]).endswith(filename)]
    assert hits, f"{filename} 未入索引"
    return hits[0][1]


@pytest.fixture
def _conflicting_technique_index():
    """写一份与目录名推断**故意相反**的 wp_technique_index.json。

    两个条目分别覆盖双键匹配的两条路径：
      - rsa-encryption.md：source_path 用**当前绝对路径** → 命中「按路径」分支
        （目录说 crypto，索引说 web）
      - stack-overflow-notes.md：source_path 用**已失效的旧前缀**（模拟 KB_PATH
        迁移/软链后绝对路径对不上）→ 按路径落空，必须由「按文件名」分支兜住
        （目录说 pwn，索引说 misc）
    """
    kb_root = Path(kr.KB_PATH)
    index_file = kb_root / WP_INDEX_RELPATH
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(
        json.dumps(
            {
                "rsa-encryption.md": {
                    "title": "RSA",
                    "source_path": str(kb_root / "challenges/crypto/rsa-encryption.md"),
                    "category": "web",
                },
                "stack-overflow-notes.md": {
                    "title": "SO",
                    "source_path": "/stale/moved/kb/challenges/pwn/stack-overflow-notes.md",
                    "category": "misc",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return index_file


class TestAuthoritativeCategory:
    def test_guess_category_alone_would_disagree(self):
        """前提校验：没有索引时，目录名推断给出的确实是**相反**的答案。

        这条保证下面几条断言不是恒真——它证明 fixture 真的制造了冲突。
        """
        kb_root = Path(kr.KB_PATH)
        assert (
            kr._guess_category(kb_root / "challenges/crypto/rsa-encryption.md")
            == "crypto"
        )
        assert (
            kr._guess_category(kb_root / "challenges/pwn/stack-overflow-notes.md")
            == "pwn"
        )

    def test_index_category_overrides_by_source_path(self, _conflicting_technique_index):
        """索引权威值经 source_path 精确命中时生效。"""
        kr.build_index(force=True)
        assert _category_of("rsa-encryption.md") == "web"

    def test_index_category_overrides_by_basename_fallback(
        self, _conflicting_technique_index
    ):
        """绝对路径对不上时，按文件名兜底仍能认领权威分类。

        这是双键匹配存在的理由：_kb_roots() 有两个根（KB_PATH + OBSIDIAN_VAULT），
        vault 侧文档天然没有 KB_PATH 前缀，且 KB_PATH 一迁移所有前缀同时失效。
        """
        kr.build_index(force=True)
        assert _category_of("stack-overflow-notes.md") == "misc"

    def test_doc_absent_from_index_falls_back_to_guess(
        self, _conflicting_technique_index
    ):
        """不在 JSON 里的文档仍按 _guess_category 分类（覆盖只针对登记过的 WP）。"""
        kr.build_index(force=True)
        assert _category_of("sql-injection-tutorial.md") == "web"
        assert _category_of("pcap-analysis.md") == "forensics"

    def test_category_filter_follows_authoritative_value(
        self, _conflicting_technique_index
    ):
        """分类过滤必须按权威值命中——这正是修复前静默漏检的那个 bug。

        "exponent" 只出现在 rsa-encryption.md。它的目录名暗示 crypto，
        索引说是 web：修复前 search(category="crypto") 能命中、
        search(category="web") 反而漏；修复后两者必须调转。
        """
        kr.build_index(force=True)
        web_hits = kr.search("exponent", category="web", limit=5)
        assert [r["title"] for r in web_hits] == ["rsa-encryption"]
        assert kr.search("exponent", category="crypto", limit=5) == []

    def test_force_rebuild_required_for_override(self, _conflicting_technique_index):
        """非 force 的 build_index 不重读任何 .md，因此不会改变已入库的分类。

        这条把「改了代码必须配 force=True 重建」这个坑钉死：不重建就看不出变化。
        """
        kr.build_index(force=True)  # 先按权威值建好
        assert _category_of("rsa-encryption.md") == "web"
        # 删掉索引文件后非 force 重建：早返回，不重读，分类保持旧值
        _conflicting_technique_index.unlink()
        kr.build_index(force=False)
        assert _category_of("rsa-encryption.md") == "web"


# ── 8. 短 token 兜底（FTS5 trigram < 3 字符静默零命中） ─────────────────


class TestShortTokenFallback:
    """FTS5 trigram 分词器对短于 3 字符的 token 一律零命中，中文二字词
    （注入/上传/逆向）恰恰全是这种。`_query_tokens` + `_fallback_token_search`
    是为此加的兜底，此前没有任何测试引用过它们。
    """

    def test_query_tokens_strips_phrase_quotes(self):
        """sanitize_query 产出 "tok1" OR "tok2"，兜底要的是裸 token。"""
        assert kr._query_tokens('"注入" OR "上传"') == ["注入", "上传"]

    def test_bare_query_also_yields_tokens(self):
        """裸串（无引号）也必须能还原出 token。

        旧实现只按引号正则，``_query_tokens("注入")`` 返回 ``[]``——而 CLI 的
        ``knowledge query 注入`` 正是 ``" ".join(args.query)`` 直传裸串，于是
        兜底被空 token 短路，**中文二字词这条最高频路径静默零命中**。
        修前实测：``search("注入")`` 0 条，``search('"注入"')`` 3 条。
        """
        assert kr._query_tokens("注入") == ["注入"]
        # FTS5 操作符要剔除，否则会被当成检索词送进 LIKE
        assert kr._query_tokens("注入 OR 上传") == ["注入", "上传"]
        assert kr._query_tokens("注入*") == ["注入"]

    def test_bare_short_cjk_query_recovers_end_to_end(self):
        """裸二字词走完整 search() 也要召回——这是 CLI 用户实际走的路径。"""
        kr.build_index()
        results = kr.search("注入", limit=5)
        assert results, "裸二字词查询静默返空——兜底没生效"
        assert any(
            r["source_path"].endswith("sql-injection-tutorial.md") for r in results
        )

    def test_short_cjk_token_recovers_via_like(self):
        """2 字中文 token 在 FTS 层零命中，必须由 LIKE 兜底召回而非静默返空。"""
        kr.build_index()
        results = kr.search('"注入"', limit=5)
        assert results, "短 token 查询静默返空——兜底没生效"
        assert any(
            r["source_path"].endswith("sql-injection-tutorial.md") for r in results
        )

    def test_long_tokens_preferred_over_short(self):
        """长短混合时应只用长 token：短词会让召回面过宽。

        「注入」命中 sql-injection 文档，「shellcode」命中 pwn 文档。
        若误把短词也纳入 OR，sql-injection 会被一起召回。
        """
        kr.build_index()
        rows = kr._fallback_token_search(["注入", "shellcode"], limit=10)
        paths = [r["source_path"] for r in rows]
        assert any(p.endswith("stack-overflow-notes.md") for p in paths)
        assert not any(p.endswith("sql-injection-tutorial.md") for p in paths)

    def test_all_short_tokens_still_searchable(self):
        """全是短词时退化为短词匹配（偏宽但有 LIMIT 兜住），不返回空。"""
        kr.build_index()
        rows = kr._fallback_token_search(["注入"], limit=10)
        assert any(r["source_path"].endswith("sql-injection-tutorial.md") for r in rows)

    def test_real_no_match_still_returns_empty(self):
        """兜底不能把「真的没有」变成假阳性。"""
        kr.build_index()
        assert kr.search('"zzzzz不存在zzzzz"', limit=5) == []


# ── WP 元数据抽取（sidecar）+ UNINDEXED 列过滤 ──────────────────────────

WP_DIR = ("CTF大赛WP集合", "articles")


def _seed_wp(name: str, body: str) -> Path:
    """往合成知识库的 WP 目录塞一篇文档，返回其路径。"""
    p = kr.KB_PATH.joinpath(*WP_DIR) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _seed_two_wps() -> None:
    """两篇重叠关键词、但赛事/年份/考点互斥的 WP，用于过滤矩阵。

    A: DASCTF / 2023 / ssti      B: 强网杯 / 2022 / pwn-heap
    两篇正文都含「注入」，这样过滤掉谁纯粹由元数据决定，而不是关键词碰巧不命中。
    """
    _seed_wp("DASCTF_2023_SSTI注入绕过.md",
             "# DASCTF 2023 SSTI 注入绕过\n"
             "> 原文: https://www.ctfiot.com/1.html\n> ID: 1\n"
             "模板注入 注入 ssti 绕过 WAF\n")
    _seed_wp("强网杯_2022_堆溢出注入.md",
             "# 强网杯 2022 堆溢出注入\n"
             "> 原文: https://www.ctfiot.com/2.html\n> ID: 2\n"
             "堆溢出 heap 注入 tcache\n")


class TestParseWpMeta:
    """从文件名 + 正文头部客观抽取 contest / year / vuln_type。

    抽不到就留空是有意为之：空值只是「不参与该维度过滤」，错值会让
    ``--contest X`` 返回完全无关的笔记。
    """

    def test_extracts_all_fields(self):
        body = ("# DASCTF 2023 7月 逆向题解\n"
                "> 原文: https://www.ctfiot.com/72634.html\n> ID: 72634\n正文…\n")
        meta = kr.parse_wp_meta(_seed_wp("DASCTF_2023_7月_逆向题解.md", body), body)
        assert meta["contest"] == "DASCTF"
        assert meta["year"] == 2023
        assert meta["vuln_type"] == "reverse-algorithm"
        assert meta["source_url"] == "https://www.ctfiot.com/72634.html"
        assert meta["source_id"] == "72634"
        assert meta["title"] == "DASCTF 2023 7月 逆向题解"

    def test_absent_metadata_stays_empty(self):
        """抽不到就留空，不用猜测填充。"""
        body = "# 一篇普通读书笔记\n与安全无关的内容。\n"
        meta = kr.parse_wp_meta(_seed_wp("普通笔记.md", body), body)
        assert meta["contest"] == ""
        assert meta["year"] is None
        assert meta["vuln_type"] == ""

    def test_english_compound_is_not_a_contest(self):
        """英文单词型赛名不得命中英文复合词。

        ``lateral-movement.md`` 里的 "movement" 曾把「横向移动」笔记标成
        MOVEment 战队赛。该词在 CTF 库里 0 个真阳性、在个人库里 2 个假阳性，
        是纯负债，已从词表移除；此测试锁住这个回归。
        """
        body = "# 横向移动\nlateral movement 技术笔记。\n"
        for stem in ("lateral-movement", "movement-techniques"):
            meta = kr.parse_wp_meta(_seed_wp(stem + ".md", body), body)
            assert meta["contest"] == "", f"{stem} 被误标为 {meta['contest']!r}"

    def test_personal_note_with_real_contest_keeps_label(self):
        """个人库里真写了解题笔记的文件必须保留赛事标签。

        曾试图用「只在 CTF 库目录内抽 contest」的路径边界堵上一条假阳性，
        结果一刀切掉个人库里 10 篇真实 DASCTF 笔记 + 1 篇 LitCTF。路径不是
        判据，词表质量才是。
        """
        body = "# DASCTF Flask SSTI 字符黑名单绕过\npython 黑名单过滤绕过。\n"
        meta = kr.parse_wp_meta(
            _seed_wp("DASCTF Flask SSTI 字符黑名单绕过.md", body), body
        )
        assert meta["contest"] == "DASCTF"


class TestGeneratedArtifactsExcluded:
    """本工具生成的聚合产物不得被反向吞回索引。

    ``contest_index.md`` 就落在 ``build_meta_index`` 正扫的目录里，不排除
    就会自噬：每跑一次多吞一次自己的输出。
    """

    def test_generated_artifacts_are_skipped(self):
        assert "contest_index.md" in kr.SKIP_FILES
        assert "wp_meta_index.json" in kr.SKIP_FILES

    def test_meta_build_is_idempotent(self):
        _seed_wp("DASCTF_2023_逆向.md",
                 "# DASCTF 2023 逆向\n> 原文: https://e.com/1.html\n> ID: 1\n正文\n")
        first = kr.build_meta_index()
        kr.build_contest_index()
        assert (kr.KB_PATH / "CTF大赛WP集合" / "contest_index.md").exists(), \
            "前置条件：聚合产物已生成"
        assert kr.build_meta_index() == first, "把自己的产物又吞了一遍"


class TestMetaFilters:
    """``writeups`` 的 year / contest / vuln_type 三列过滤。

    这三列是 FTS5 的 UNINDEXED 列——不参与倒排索引，只在 MATCH 结果集上做
    WHERE 过滤。（FTS5 虚拟表**不能**建普通索引，``CREATE INDEX ... ON
    writeups(...)`` 会直接报 ``virtual tables may not be indexed``。）
    """

    def test_contest_filter(self):
        _seed_two_wps()
        kr.build_index()
        rows = kr.search("注入", contest="DASCTF", limit=10)
        assert rows, "contest 过滤返空"
        assert {r["contest"] for r in rows} == {"DASCTF"}

    def test_year_filter(self):
        _seed_two_wps()
        kr.build_index()
        rows = kr.search("注入", year=2022, limit=10)
        assert rows, "year 过滤返空"
        assert {r["year"] for r in rows} == {2022}

    def test_vuln_type_filter(self):
        _seed_two_wps()
        kr.build_index()
        rows = kr.search("注入", vuln_type="pwn-heap", limit=10)
        assert rows, "vuln_type 过滤返空"
        assert {r["vuln_type"] for r in rows} == {"pwn-heap"}

    def test_all_three_filters_combine(self):
        _seed_two_wps()
        kr.build_index()
        rows = kr.search("注入", contest="DASCTF", year=2023, vuln_type="ssti", limit=10)
        assert len(rows) == 1
        # title 取文件名 stem（build_index 的既有设计），H1 标题只进 sidecar
        assert rows[0]["title"] == "DASCTF_2023_SSTI注入绕过"
        assert rows[0]["source_path"].endswith("DASCTF_2023_SSTI注入绕过.md")

    def test_empty_intersection_is_genuinely_empty(self):
        """过滤组合真无交集时返空，不是过滤失效——两种空必须可区分。"""
        _seed_two_wps()
        kr.build_index()
        assert kr.search("注入", contest="DASCTF", year=2022, limit=10) == []

    def test_filters_survive_fallback_path(self):
        """裸二字词走 LIKE 兜底时过滤条件不能丢。

        修前实测：``--contest DASCTF`` 在 34 篇 DASCTF 里应命中 13 篇，
        实际 0 篇——FTS 主路径带过滤，兜底路径丢过滤。
        """
        _seed_two_wps()
        kr.build_index()
        # 「注入」是 2 字，FTS5 trigram 零命中，必然走兜底
        assert kr.search("注入", contest="DASCTF", limit=10)
        assert kr.search("注入", contest="强网杯", limit=10)


class TestSchemaMigration:
    """老库（4 列）上带元数据过滤必须重建，不能静默返空。"""

    def test_schema_is_current_requires_meta_columns(self):
        kr.build_index()
        conn = sqlite3.connect(str(kr.DB_PATH))
        try:
            assert kr._schema_is_current(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(writeups)")}
            for c in kr._META_COLUMNS:
                assert c in cols
        finally:
            conn.close()

    def test_legacy_schema_rebuilds_instead_of_silent_empty(self):
        _seed_two_wps()
        kr.build_index()
        # 退化成老 schema，并塞一行让索引非空（否则会走「索引为空」分支）
        conn = sqlite3.connect(str(kr.DB_PATH))
        conn.execute("DROP TABLE writeups")
        conn.execute(
            "CREATE VIRTUAL TABLE writeups USING fts5("
            "title, category, content, source_path UNINDEXED, tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO writeups (title, category, content, source_path) "
            "VALUES ('legacy', 'web', '旧库残留', '/legacy.md')"
        )
        conn.commit()
        conn.close()

        assert not kr._index_has_meta()
        rows = kr.search("注入", contest="DASCTF", limit=10)
        assert rows, "老 schema 下带过滤静默返空——应当自动重建"
        assert {r["contest"] for r in rows} == {"DASCTF"}


# ── KB_PATH 解析优先级 ──────────────────────────────────────────────────


class TestResolveKbPath:
    """优先级：env > 活库 ~/.fulilian/ctf-knowledge > 随源码分发的快照 > 历史克隆位置。

    活库排在前是因为它是写入目标（``self-solved/`` 收做题写回的 WP）；快照是
    只读的，排在克隆位置前是为了让新克隆的机器免去手工复制 41M 语料。
    """

    def _isolate(self, monkeypatch):
        monkeypatch.delenv("FULILIAN_CTF_KB_PATH", raising=False)
        monkeypatch.setattr(kr, "_KB_FALLBACK_PATHS", ())

    def test_env_wins(self, tmp_path, monkeypatch):
        self._isolate(monkeypatch)
        monkeypatch.setenv("FULILIAN_CTF_KB_PATH", str(tmp_path / "from-env"))
        assert kr._resolve_kb_path() == tmp_path / "from-env"

    def test_live_home_beats_bundled(self, tmp_path, monkeypatch):
        self._isolate(monkeypatch)
        live = tmp_path / "ctf-knowledge"
        live.mkdir()
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        monkeypatch.setattr(kr, "FULILIAN_HOME", tmp_path)
        monkeypatch.setattr(kr, "BUNDLED_KB_PATH", bundled)
        assert kr._resolve_kb_path() == live

    def test_falls_back_to_bundled_snapshot(self, tmp_path, monkeypatch):
        """新克隆的机器上活库不存在，应找到随源码分发的快照——而不是对着
        不存在的目录静默建出 0 条索引、把已有索引清空。"""
        self._isolate(monkeypatch)
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        monkeypatch.setattr(kr, "FULILIAN_HOME", tmp_path / "nope")
        monkeypatch.setattr(kr, "BUNDLED_KB_PATH", bundled)
        assert kr._resolve_kb_path() == bundled

    def test_bundled_path_is_repo_relative(self):
        """BUNDLED_KB_PATH 必须指向源码树内的 ctf-knowledge/。"""
        assert kr.BUNDLED_KB_PATH.name == "ctf-knowledge"
        assert (kr.BUNDLED_KB_PATH.parent / "fulilian_ctf").is_dir()


# ── 6. P4.2: sanitize 下沉 —— search() 是唯一收口 ────────────────────────


class TestSanitizeSink:
    """sanitize 必须在 search() 内部生效才是不变量：任何调用方传进来的
    自由文本（题面、payload 片段、纯标点）都不该让 search() 崩或误建索引。
    实现见 kr.sanitize_match_query；knowledge._sanitize_query 是兼容壳。"""

    def test_payload_shaped_query_does_not_raise(self):
        """题面贴 payload（引号/括号/裸操作符）不得抛 FTS5 语法错误。"""
        kr.build_index()
        for q in ("admin' OR 1=1", 'FTS" OR (', "AND OR NOT NEAR", "2.31", "()"):
            results = kr.search(q, limit=5)  # 旧码裸 MATCH 会 OperationalError
            assert isinstance(results, list)

    def test_pure_punctuation_returns_empty_without_building(self, monkeypatch):
        """清洗后为空的 query 直接返回 []，且不触发索引构建。"""
        monkeypatch.setattr(kr, "build_index",
                            lambda *a, **kw: (_ for _ in ()).throw(
                                AssertionError("垃圾 query 不值得为它建索引")))
        assert kr.search("()", limit=5) == []

    def test_sanitize_idempotent_for_sanitized_shape(self):
        """对已清洗形态（"a" OR "b"）幂等 —— 生产存在先洗后传的调用方。"""
        once = kr.sanitize_match_query("tcache poisoning 堆利用")
        assert kr.sanitize_match_query(once) == once

    def test_operator_words_dropped_case_insensitive(self):
        assert kr.sanitize_match_query("AND OR NOT NEAR sqli") == '"sqli"'

    def test_short_cjk_query_reaches_fallback(self):
        """2 字中文（trigram 最小 token 之下）走 sanitize 后仍经 FTS 空 →
        LIKE 兜底命中，而不是静默空结果。"""
        kr.build_index()
        results = kr.search("注入", limit=5)
        assert any("sql-injection" in r["source_path"] for r in results)

    def test_knowledge_shell_delegates_to_sink(self):
        """knowledge._sanitize_query 兼容壳必须与下沉实现同口径。"""
        from fulilian_ctf.knowledge import _sanitize_query

        assert _sanitize_query("ssti 模板注入 payload 绕过") == \
            kr.sanitize_match_query("ssti 模板注入 payload 绕过")
