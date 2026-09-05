"""P1-2 回归锁：run_agent.main 返回值（M-2）+ dispatcher 并发计数锁（M-3）。

M-2：main 正常完成 return 0 / 可识别失败 return 1；solver 侧 None 退出码
视为失败（ok=((code or 1) == 0)）。
M-3：_try_consume_spawn_slot 原子消耗名额；10 线程压力无超额；limit 语义不变。
"""

from __future__ import annotations

import threading

import pytest

from fulilian_ctf.dispatcher import Dispatcher, Project
from fulilian_ctf.solver import SolverResult, _solver_result_from_code


# ── M-2：solver 退出码 → ok 判定 ────────────────────────────────────

def test_solver_result_none_is_failure():
    r = _solver_result_from_code(None)
    assert r.ok is False


def test_solver_result_zero_is_ok():
    r = _solver_result_from_code(0)
    assert r.ok is True
    assert r.exit_code == 0


def test_solver_result_nonzero_is_failure():
    r = _solver_result_from_code(1)
    assert r.ok is False
    assert r.exit_code == 1


# ── M-2：main 返回值 ────────────────────────────────────────────────

def _patch_turn(monkeypatch, completed, agent):
    import run_agent

    monkeypatch.setattr(
        run_agent, "_run_solver_turn",
        lambda **kw: {"result": {"completed": completed, "messages": [],
                                 "final_response": "", "api_calls": 0},
                      "agent": agent},
    )


def test_main_returns_1_when_agent_init_failed(monkeypatch):
    import run_agent

    _patch_turn(monkeypatch, completed=False, agent=None)
    assert run_agent.main(query="hi", mode="ctf") == 1


def test_main_returns_1_when_session_incomplete(monkeypatch):
    import run_agent

    _patch_turn(monkeypatch, completed=False, agent=object())
    assert run_agent.main(query="hi") == 1


def test_main_returns_0_when_completed(monkeypatch):
    import run_agent

    _patch_turn(monkeypatch, completed=True, agent=object())
    assert run_agent.main(query="hi") == 0


def test_main_source_has_return_codes():
    # 防线：usage 早退 return 0、尾部按 completed 返回 0/1 的表达式存在
    import inspect

    import run_agent

    src = inspect.getsource(run_agent.main)
    assert "return 0  # usage/help" in src
    assert 'return 0 if (agent is not None and result.get("completed")) else 1' in src


# ── M-3：并发计数锁 ─────────────────────────────────────────────────

def test_consume_slot_limit_semantics():
    d = Dispatcher(quiet=True)
    assert d._try_consume_spawn_slot(3) is True
    assert d._try_consume_spawn_slot(3) is True
    assert d._try_consume_spawn_slot(3) is True
    assert d._try_consume_spawn_slot(3) is False  # 第 4 次拒绝
    assert d._spawns == 3


def test_consume_slot_unlimited():
    d = Dispatcher(quiet=True)
    assert d._try_consume_spawn_slot(None) is True
    assert d._spawns == 1


def test_concurrent_consume_never_exceeds_limit():
    d = Dispatcher(quiet=True)
    limit = 500
    successes: list[bool] = []
    lock = threading.Lock()

    def worker():
        local = [d._try_consume_spawn_slot(limit) for _ in range(100)]
        with lock:
            successes.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert d._spawns == limit  # 恰好 500：无超额、无丢失
    assert sum(successes) == limit
    assert len(successes) == 1000


def test_spawn_with_exhausted_limit_does_not_spawn():
    d = Dispatcher(quiet=True)
    p = Project(challenge_id="c1", difficulty="easy")
    assert d._spawn(p, limit=0) is False
    assert d._spawns == 0
    assert "c1" not in d._running
