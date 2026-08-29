"""黑板架构（F2-005/006/009）单元测试 — 对应实施指南 06 验证方式清单。"""

from __future__ import annotations

import json
import time

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    Hint,
    Intent,
    State,
    load_blackboard,
    save_blackboard,
)


# ── 1. Fact/Intent/Hint 三原语正确创建和读取 ─────────────────────────────

def test_fact_defaults():
    f = Fact(content="Port 80 open", source="nmap")
    assert f.id  # 自动生成
    assert f.state == State.CONFIRMED
    assert f.tags == []
    assert 0.0 < f.created_at <= time.time()
    assert f.confidence == 1.0


def test_fact_serializes_state_as_string():
    """to_dict 必须 JSON-safe（state 输出字符串值，不是 Enum）。"""
    f = Fact(content="x", state=State.REFUTED)
    d = f.to_dict()
    assert d["state"] == "refuted"
    json.dumps(d)  # 不抛异常


def test_intent_defaults_and_open_filter():
    i = Intent(goal="Probe CVE-2021-41773", approach="curl -v target/..")
    assert i.id
    assert i.state == State.OPEN
    assert i.variant_count == 0
    b = Blackboard(challenge_id="web-01")
    b.add_intent(i)
    b.add_intent(Intent(goal="done", approach="x", state=State.CONFIRMED))
    open_goals = [x.goal for x in b.get_open_intents()]
    assert open_goals == ["Probe CVE-2021-41773"]


def test_hint_defaults():
    h = Hint(content="try path traversal", source="user")
    assert h.source == "user"
    assert 0.0 < h.created_at <= time.time()


def test_mark_intent_state():
    b = Blackboard()
    i = Intent(goal="g", approach="a")
    b.add_intent(i)
    b.mark_intent_state(i.id, State.REFUTED)
    assert b.intents[0].state == State.REFUTED
    with pytest.raises(KeyError):
        b.mark_intent_state("nonexistent", State.NEXT)


# ── 2. 父子黑板：子黑板写入 Fact，父黑板可见 ─────────────────────────────

def test_child_fact_visible_in_parent():
    global_board = Blackboard(challenge_id="global")
    challenge_board = Blackboard(parent=global_board, challenge_id="web-01")
    challenge_board.add_fact(
        Fact(content="Port 80 open, Apache 2.4.49", source="nmap", tags=["web"])
    )
    assert len(challenge_board.get_facts()) == 1
    assert len(global_board.get_facts()) == 1  # 父黑板可见
    assert global_board.get_facts()[0].content == "Port 80 open, Apache 2.4.49"


def test_get_facts_tag_filter():
    b = Blackboard()
    b.add_fact(Fact(content="a", tags=["web", "recon"]))
    b.add_fact(Fact(content="b", tags=["crypto"]))
    assert [f.content for f in b.get_facts("web")] == ["a"]
    assert len(b.get_facts("recon")) == 1
    assert len(b.get_facts("none")) == 0


def test_parent_fact_not_in_child():
    """父黑板全局 Fact 不注入子黑板（子黑板只透传自己的写入）。"""
    global_board = Blackboard(challenge_id="global")
    global_board.add_fact(Fact(content="global knowledge", source="attck"))
    child = Blackboard(parent=global_board, challenge_id="c-01")
    assert child.get_facts() == []  # 子黑板不重复拉取全局 Fact


# ── 3. 死路免疫：一个 solver 标记死路，其他 solver 不会重复探索 ─────────

def test_dead_end_immunity_across_solvers():
    global_board = Blackboard(challenge_id="global")
    solver_a = Blackboard(parent=global_board, challenge_id="web-01")
    solver_b = Blackboard(parent=global_board, challenge_id="web-02")

    solver_a.mark_dead_end("CVE-2021-41773")
    assert solver_a.is_dead_end("CVE-2021-41773")
    assert solver_b.is_dead_end("CVE-2021-41773")  # 免疫：不重复探索
    assert global_board.is_dead_end("CVE-2021-41773")


def test_dead_end_local_and_parent_fallback():
    b = Blackboard()
    assert not b.is_dead_end("x")
    b.mark_dead_end("x")
    assert b.is_dead_end("x")
    # 父黑板死路对子黑板可见
    parent = Blackboard()
    parent.mark_dead_end("y")
    child = Blackboard(parent=parent)
    assert child.is_dead_end("y")


# ── 4. Tags 信息素：跨 solver 可见 ───────────────────────────────────────

def test_tags_pheromone_cross_solver():
    global_board = Blackboard(challenge_id="global")
    solver_a = Blackboard(parent=global_board, challenge_id="web-01")
    solver_b = Blackboard(parent=global_board, challenge_id="web-02")

    solver_a.set_tag("high_value", "port_80_apache")
    assert solver_b.get_tag("high_value") == "port_80_apache"  # 跨 solver 可见
    assert global_board.get_tag("high_value") == "port_80_apache"


def test_tag_local_precedence_over_parent():
    parent = Blackboard()
    parent.set_tag("k", "parent-value")
    child = Blackboard(parent=parent)
    child.set_tag("k", "child-value")
    assert child.get_tag("k") == "child-value"  # 本地优先
    assert parent.get_tag("k") == "child-value"  # 但透传覆盖了父黑板


def test_tag_missing_returns_none():
    assert Blackboard().get_tag("nope") is None


# ── 5. 序列化 / 反序列化（to_dict / from_dict）正确 ──────────────────────

def test_to_dict_roundtrip():
    b = Blackboard(challenge_id="web-01")
    b.add_fact(
        Fact(id="f1", content="f1-content", source="nmap", tags=["web"], state=State.CONFIRMED)
    )
    b.add_intent(Intent(id="i1", goal="g1", approach="a1", state=State.OPEN, variant_count=2))
    b.add_hint(Hint(content="h1", source="user"))
    b.mark_dead_end("dead-1")
    b.set_tag("high_value", "port_80")

    d = b.to_dict()
    assert d["challenge_id"] == "web-01"
    assert d["facts"]["f1"]  # id 为 key
    assert d["facts"]["f1"]["state"] == "confirmed"
    assert d["dead_ends"] == ["dead-1"]
    assert d["tags"] == {"high_value": "port_80"}
    json.dumps(d)  # JSON-safe

    b2 = Blackboard.from_dict(d)
    assert b2.challenge_id == "web-01"
    assert b2.get_facts()[0].content == "f1-content"
    assert b2.get_facts()[0].state == State.CONFIRMED
    assert b2.intents[0].variant_count == 2
    assert b2.hints[0].content == "h1"
    assert b2.is_dead_end("dead-1")
    assert b2.get_tag("high_value") == "port_80"


def test_from_dict_preserves_ids_and_restores_parent():
    parent = Blackboard(challenge_id="global")
    child = Blackboard(parent=parent, challenge_id="c-1")
    f = Fact(content="keep me")
    child.add_fact(f)
    child.mark_dead_end("p")
    d = child.to_dict()

    loaded = Blackboard.from_dict(d, parent=parent)
    assert loaded.challenge_id == "c-1"
    assert f.id in loaded.facts
    assert loaded.get_facts()[0].content == "keep me"
    assert loaded.is_dead_end("p")
    assert len(parent.get_facts()) == 1  # 父黑板状态保留


def test_save_and_load_blackboard(tmp_path):
    b = Blackboard(challenge_id="web-01")
    b.add_fact(Fact(content="discovery", source="cmd", tags=["recon"]))
    b.add_intent(Intent(goal="next step"))
    b.set_tag("high_value", "port_80")

    path = save_blackboard(b, tmp_path / "web-01" / BLACKBOARD_FILENAME)
    assert path.is_file()
    assert "discovery" in path.read_text(encoding="utf-8")

    loaded = load_blackboard(path)
    assert loaded is not None
    assert loaded.challenge_id == "web-01"
    assert loaded.get_facts()[0].content == "discovery"
    assert loaded.get_tag("high_value") == "port_80"
    assert len(loaded.intents) == 1


def test_load_missing_returns_none(tmp_path):
    assert load_blackboard(tmp_path / "nope" / BLACKBOARD_FILENAME) is None


# ── 6. Append-only：Fact 添加后不可修改 ──────────────────────────────────

def test_add_fact_append_only_rejects_duplicate_id():
    b = Blackboard()
    f1 = Fact(id="fact_1", content="first")
    b.add_fact(f1)
    f2 = Fact(id="fact_1", content="second")  # 同 id 不同内容
    with pytest.raises(ValueError):
        b.add_fact(f2)
    assert b.get_facts()[0].content == "first"  # 原 Fact 未被修改


def test_add_fact_same_object_idempotent():
    b = Blackboard()
    f = Fact(content="x")
    b.add_fact(f)
    b.add_fact(f)  # 同一对象重复加入 → no-op
    assert len(b.get_facts()) == 1


# ── 附加：多 solver 并发写入同一父黑板（Stigmergy 聚合）──────────────────

def test_two_solvers_publish_facts_to_shared_parent():
    parent = Blackboard(challenge_id="global")
    a = Blackboard(parent=parent, challenge_id="web-01")
    b = Blackboard(parent=parent, challenge_id="web-02")
    a.add_fact(Fact(content="A found port 80", source="nmap"))
    b.add_fact(Fact(content="B found port 443", source="nmap"))
    contents = sorted(f.content for f in parent.get_facts())
    assert contents == ["A found port 80", "B found port 443"]
    # 每个子黑板只看到自己的 Fact
    assert len(a.get_facts()) == 1
    assert len(b.get_facts()) == 1
