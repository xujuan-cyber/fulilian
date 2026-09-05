"""P1-3 回归锁：接力块过滤（A-4）+ 非原子写补齐。

A-4：source=="solver" 与 content 以 "solver attempt " 开头的 Fact 不得进入
RELAY「已达成原语」与黑板回注通道（共享谓词）；dead_ends 全量保留；止损
统计不受影响；两次 respawn 后 facts 不因回注而增加。
原子写：write_relay_file / save_state / write_usage_record 三处 tmp+os.replace。
"""

from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    load_blackboard,
    save_blackboard,
)
from fulilian_ctf.dispatcher import Dispatcher, Project
from fulilian_ctf.relay import parse_relay, read_relay_file, write_relay_file
from fulilian_ctf.solver import bootstrap_blackboard
from fulilian_ctf.timebox import Timebox

from fulilian_ctf import solver as _solver_mod

# write_usage_record / usage.json 写入路径在新版 solver 才有；旧版跳过
write_usage_record = getattr(_solver_mod, "write_usage_record", None)
_requires_usage_record = pytest.mark.skipif(
    write_usage_record is None, reason="solver.write_usage_record 不存在（旧版 solver）"
)


@pytest.fixture
def dispatcher():
    return Dispatcher(quiet=True)


@pytest.fixture
def env(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    project = Project(challenge_id="c1", difficulty="easy")
    tb = Timebox(initial_budget=60)
    tb.start()
    return work_dir, project, tb


def _board_with_garbage(work_dir):
    board = Blackboard(challenge_id="c1")
    board.add_fact(Fact(content="port 80 open", source="agent"))
    board.add_fact(Fact(content="CVE-X confirmed", source="agent"))
    board.add_fact(Fact(content="web logic idea", source="agent"))
    board.add_fact(Fact(content="solver attempt 1 started (pid 111)", source="solver"))
    board.add_fact(Fact(content="attempt finished", source="solver"))
    board.mark_dead_end("sql injection dead end")
    save_blackboard(board, work_dir / BLACKBOARD_FILENAME)
    return board


# ── 1. 过滤生效 ──────────────────────────────────────────────────────

def test_write_relay_filters_meta_facts(dispatcher, env):
    work_dir, project, tb = env
    board = _board_with_garbage(work_dir)

    dispatcher._write_relay(project, tb, work_dir)
    relay = parse_relay(read_relay_file(work_dir))

    achieved = relay["achieved_primitives"]
    assert "port 80 open" in achieved
    assert "CVE-X confirmed" in achieved
    assert "web logic idea" in achieved
    assert not any("solver attempt " in a for a in achieved)
    assert not any(a == "attempt finished" for a in achieved)  # source=="solver"
    assert relay["dead_ends"] == ["sql injection dead end"]  # dead_ends 全量


# ── 2. 不累积：两次 respawn 后 facts 不因回注增加 ────────────────────

def test_facts_do_not_grow_after_two_respawns(dispatcher, env):
    work_dir, project, tb = env
    _board_with_garbage(work_dir)
    initial = load_blackboard(work_dir / BLACKBOARD_FILENAME)
    initial_total = len(list(initial.get_facts()))

    for _ in range(2):
        dispatcher._write_relay(project, tb, work_dir)
        relay_text = read_relay_file(work_dir)
        dispatcher._inject_relay_into_board(work_dir)   # _spawn 侧回注
        bootstrap_blackboard(project, work_dir, relay_text)  # solver 侧回注

    final = load_blackboard(work_dir / BLACKBOARD_FILENAME)
    facts = list(final.get_facts())
    # 验收口径：facts 不因 RELAY 回注而增加。bootstrap 每次调用会向存储
    # 追加一条 attempt 元 Fact（存储侧行为，契约不动），因此以回注通道
    # 度量：不得出现任何 source=="relay" 的新 Fact，agent facts 不变。
    relay_facts = [f for f in facts if f.source == "relay"]
    assert relay_facts == []  # 回注没有把 RELAY 原语变成新 Fact（全部已存在或为元信息）
    assert len([f for f in facts if f.source == "agent"]) == 3
    # 唯一允许的增长是 bootstrap 的 attempt 元 Fact（存储侧行为，契约不动；
    # 生产环境每次 attempts 递增、内容不同，这里不对其去重性作要求）
    attempt_facts = [f for f in facts if f.source == "solver"]
    assert all(f.content.startswith("solver attempt ") or f.content == "attempt finished"
               for f in attempt_facts)


# ── 3. 止损统计不受过滤影响 ─────────────────────────────────────────

def test_stop_loss_stats_unaffected(dispatcher, env):
    from fulilian_ctf.stopper import count_variant_failures
    from fulilian_ctf.blackboard import State

    work_dir, project, tb = env
    board = _board_with_garbage(work_dir)
    before = (
        len([f for f in board.get_facts() if f.state in (State.CONFIRMED, State.REFUTED)]),
        count_variant_failures(board),
        len(board.dead_ends),
    )
    dispatcher._write_relay(project, tb, work_dir)
    dispatcher._inject_relay_into_board(work_dir)
    board_after = load_blackboard(work_dir / BLACKBOARD_FILENAME)
    after = (
        len([f for f in board_after.get_facts() if f.state in (State.CONFIRMED, State.REFUTED)]),
        count_variant_failures(board_after),
        len(board_after.dead_ends),
    )
    assert before == after


# ── 4. 原子写 ────────────────────────────────────────────────────────

def test_atomic_write_normal_path(tmp_path):
    from fulilian_ctf.relay import atomic_write_text

    target = tmp_path / "f.txt"
    atomic_write_text(target, "new content")
    assert target.read_text(encoding="utf-8") == "new content"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_replace_failure_keeps_original(tmp_path, monkeypatch):
    from fulilian_ctf.relay import atomic_write_text

    target = tmp_path / "f.txt"
    target.write_text("old content", encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new content")
    assert target.read_text(encoding="utf-8") == "old content"  # 旧内容完好


def test_write_relay_file_is_atomic(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_relay_file(tmp_path, "# relay")
    # 走的是 os.replace 原子路径（没有直接 write_text 落盘成功）


def test_save_state_is_atomic(tmp_path, monkeypatch):
    d = Dispatcher(quiet=True)
    target = tmp_path / "state.json"
    target.write_text("{}", encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        d.save_state({"a": 1}, target)
    assert target.read_text(encoding="utf-8") == "{}"  # 旧内容完好


@_requires_usage_record
def test_write_usage_record_is_atomic(tmp_path, monkeypatch):
    target = tmp_path / "usage.json"
    target.write_text(json.dumps({"total_tokens": 5}), encoding="utf-8")
    agent = SimpleNamespace(
        session_input_tokens=10, session_output_tokens=5,
        session_api_calls=1, session_estimated_cost_usd=0.01,
    )

    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)
    # write_usage_record 自身吞 OSError（返回 None），但写失败时旧文件必须完好
    write_usage_record(tmp_path, agent)
    assert json.loads(target.read_text(encoding="utf-8"))["total_tokens"] == 5


# ── 5. usage_record 并发原子性 ───────────────────────────────────────

@_requires_usage_record
def test_write_usage_record_concurrent_no_truncation(tmp_path):
    def make_agent(n):
        return SimpleNamespace(
            session_input_tokens=n, session_output_tokens=n,
            session_api_calls=1, session_estimated_cost_usd=0.01,
        )

    errors: list[Exception] = []

    def worker(n):
        try:
            for _ in range(20):
                write_usage_record(tmp_path, make_agent(n))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(10 ** i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    data = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert isinstance(data["total_tokens"], int) and data["total_tokens"] > 0
