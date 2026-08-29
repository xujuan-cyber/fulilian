"""跨题运行学习 + 自进化 (F3-003 / F3-004) 单元测试 — 对应实施指南 08 验证方式清单。

所有测试通过 tmp_path + monkeypatch 覆盖模块常量 el.LEARNING_FILE / el.TRACES_DIR，
不读写真实的 ~/.fulilian/learning.json 与 traces 目录。
注意：常量必须通过模块属性（el.LEARNING_FILE）引用，不能按值 import，
否则 monkeypatch 后测试内引用的仍是旧绑定。
"""

from __future__ import annotations

import json

import pytest

import fulilian_ctf.experiential_learning as el


# ── Fixture ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_learning_env(tmp_path, monkeypatch):
    """每个测试使用独立 tmp 学习文件与轨迹目录，绝不触碰真实数据。"""
    monkeypatch.setattr(el, "LEARNING_FILE", tmp_path / "learning.json")
    monkeypatch.setattr(el, "TRACES_DIR", tmp_path / "traces")
    yield


def _write_trace(challenge_id: str, trace_data: dict) -> None:
    """把轨迹文件写入 monkeypatch 后的 tmp TRACES_DIR。"""
    el.TRACES_DIR.mkdir(parents=True, exist_ok=True)
    trace_file = el.TRACES_DIR / f"{challenge_id}.json"
    trace_file.write_text(
        json.dumps(trace_data, ensure_ascii=False), encoding="utf-8"
    )
    return trace_file


# ── 1. 正/负知识记录 ─────────────────────────────────────────────────────


class TestRecordLesson:
    def test_record_positive_lesson(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True,
                         command="sqlmap -u 'http://target?id=1'",
                         notes="发现联合注入")
        learnings = el.load_learnings()
        assert len(learnings["entries"]) == 1
        assert learnings["entries"][0]["success"] is True
        assert learnings["entries"][0]["technique"] == "SQL注入"

    def test_record_negative_lesson(self):
        el.record_lesson("web-02", "web", "XSS绕过", success=False,
                         command="<script>alert(1)</script>",
                         notes="WAF拦截了基本的script标签")
        learnings = el.load_learnings()
        assert len(learnings["entries"]) == 1
        assert learnings["entries"][0]["success"] is False

    def test_multiple_lessons(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("crypto-01", "crypto", "RSA低指数", success=True)
        el.record_lesson("web-02", "web", "XSS绕过", success=False)
        learnings = el.load_learnings()
        assert len(learnings["entries"]) == 3

    def test_attck_index_updates(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("web-02", "web", "SQL注入", success=True)
        el.record_lesson("web-03", "web", "SQL注入", success=False)
        learnings = el.load_learnings()
        key = "web::SQL注入"
        assert key in learnings["index"]
        assert learnings["index"][key]["success"] == 2
        assert learnings["index"][key]["fail"] == 1

    def test_persistence(self):
        """save_learnings 后文件应存在且可读。"""
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        assert el.LEARNING_FILE.exists()
        data = json.loads(el.LEARNING_FILE.read_text(encoding="utf-8"))
        assert len(data["entries"]) == 1


# ── 2. 经验查询 ──────────────────────────────────────────────────────────


class TestQueryExperience:
    def test_query_by_category(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("crypto-01", "crypto", "RSA", success=True)
        results = el.query_experience(category="web")
        assert len(results) == 1
        assert results[0]["technique"] == "SQL注入"

    def test_query_by_technique(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("crypto-01", "crypto", "RSA", success=True)
        results = el.query_experience(technique="RSA")
        assert len(results) == 1

    def test_query_limit(self):
        for i in range(5):
            el.record_lesson(f"web-{i:02d}", "web", f"technique-{i}", success=True)
        results = el.query_experience(category="web", limit=3)
        assert len(results) == 3

    def test_query_empty_db(self):
        results = el.query_experience()
        assert results == []


# ── 3. ATT&CK 索引查询 ───────────────────────────────────────────────────


class TestQueryIndex:
    def test_query_index(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("web-02", "web", "SQL注入", success=True)
        results = el.query_index()
        assert len(results) >= 1
        sql_entry = [r for r in results if r["technique"] == "SQL注入"]
        assert len(sql_entry) >= 1
        assert sql_entry[0]["total"] == 2

    def test_query_index_by_category(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("crypto-01", "crypto", "RSA", success=True)
        results = el.query_index(category="crypto")
        assert len(results) == 1
        assert results[0]["category"] == "crypto"

    def test_query_index_min_total(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        results = el.query_index(min_total=2)
        assert len(results) == 0  # 不够 2 次


# ── 4. 避免列表 ──────────────────────────────────────────────────────────


class TestGetAvoidList:
    def test_get_avoid_list(self):
        el.record_lesson("web-01", "web", "XSS绕过", success=False)
        el.record_lesson("web-02", "web", "XSS绕过", success=False)
        avoid = el.get_avoid_list("web", min_fail=2)
        assert "XSS绕过" in avoid

    def test_get_avoid_list_no_match(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        avoid = el.get_avoid_list("web", min_fail=1)
        assert avoid == []


# ── 5. 自进化 ────────────────────────────────────────────────────────────


class TestSelfEvolve:
    def test_self_evolve_no_trace(self):
        """没有轨迹文件时返回 None。"""
        result = el.self_evolve("nonexistent-challenge")
        assert result is None

    def test_self_evolve_with_trace(self):
        """有轨迹文件时提取知识点。"""
        _write_trace("test-challenge", {
            "challenge_id": "test-challenge",
            "category": "web",
            "flag": "flag{test123}",
            "key_commands": [
                "nmap -p 80 target",
                "sqlmap -u 'http://target?id=1' --batch",
            ],
        })

        result = el.self_evolve("test-challenge")
        assert result is not None
        assert result["extracted"] > 0
        assert result["challenge_id"] == "test-challenge"

        # 验证知识点已落库
        learnings = el.load_learnings()
        assert len(learnings["entries"]) >= result["extracted"]

    def test_self_evolve_without_flag(self):
        """没有 flag 时提取负知识。"""
        _write_trace("failed-challenge", {
            "challenge_id": "failed-challenge",
            "category": "web",
            "flag": "",
            "key_commands": ["sqlmap -u 'http://target?id=1' --batch"],
        })

        result = el.self_evolve("failed-challenge")
        assert result is not None
        # 没 flag 的条目应标记为失败
        learnings = el.load_learnings()
        failed_entries = [e for e in learnings["entries"] if not e["success"]]
        assert len(failed_entries) > 0

    def test_self_evolve_dedup(self):
        """去重：同一轨迹重复自进化不应产生重复条目。"""
        _write_trace("dup-challenge", {
            "challenge_id": "dup-challenge",
            "category": "web",
            "flag": "flag{dup}",
            "key_commands": ["sqlmap -u 'http://target?id=1' --batch"],
        })
        r1 = el.self_evolve("dup-challenge")
        r2 = el.self_evolve("dup-challenge")
        assert r1 is not None and r1["extracted"] == 1
        assert r2 is not None and r2["extracted"] == 0
        learnings = el.load_learnings()
        assert len(learnings["entries"]) == 1


# ── 6. 学习统计 ──────────────────────────────────────────────────────────


class TestLearningStats:
    def test_get_learning_stats_empty(self):
        stats = el.get_learning_stats()
        assert stats["total_entries"] == 0
        assert stats["positive"] == 0
        assert stats["negative"] == 0
        assert stats["techniques"] == 0

    def test_get_learning_stats(self):
        el.record_lesson("web-01", "web", "SQL注入", success=True)
        el.record_lesson("web-02", "web", "XSS绕过", success=False)
        stats = el.get_learning_stats()
        assert stats["total_entries"] == 2
        assert stats["positive"] == 1
        assert stats["negative"] == 1
