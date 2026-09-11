"""调度引擎 P1 回归锁：中断认领 flag / 坏黑板降级 / 槽位注册顺序。

三条防线都指向同一类事故——**产出被丢**：

1. ``_interrupt`` / ``_interrupt_stopped`` 只 terminate 进程、不排空结果队列。
   ``solver_worker`` 是先 ``queue.put(结果)`` 再写 trace 的，主循环同一轮里
   判定超时/止损时队列中可能已有通过校验门的 flag，被直接丢弃 → SOLVED 被
   误标 TIMEOUT/ABANDONED；下一轮 respawn 以 "w" 截断 solver.log 后连日志
   兜底来源也没了。
2. 损坏的 ``blackboard.json`` 让 ``load_blackboard`` 抛异常，经 ``run()`` 的
   ``except BaseException`` 终止**整个**多题 run（连带杀掉其它题 solver）。
3. ``_spawn`` 先 ``proc.start()`` 后注册 ``_running`` 槽位，中段异常会留下
   无人回收的孤儿 solver 进程（因为黑板损坏就够触发）。

用真子进程 + 模块级 fake solver（forkserver 需按引用 pickle），不用假 Process：
中断路径要验证的正是「真进程投递进真队列的结果能否被取回」。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from fulilian_ctf import dispatcher as dispatcher_mod
from fulilian_ctf.dispatcher import (
    ChallengeStatus,
    Dispatcher,
    Project,
    _load_blackboard_safe,
)
from fulilian_ctf.solver import SolverResult

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="fork/信号语义与 POSIX 不同"
)

FLAG = "flag{interrupt_drain}"


# ── 模块级 fake solver（子进程需按引用 pickle）───────────────────────────

def solver_puts_flag_then_waits(project, work_dir, model, queue):
    queue.put(SolverResult(ok=True, exit_code=0, flag=FLAG))
    Path(work_dir, "FLAG").write_text(FLAG + "\n", encoding="utf-8")
    time.sleep(60)  # 模拟「已产出但还没退出」，等待被中断


def solver_silent(project, work_dir, model, queue):
    time.sleep(60)


def solver_reports_model(project, work_dir, model, queue):
    Path(work_dir, "seen_model.txt").write_text(model, encoding="utf-8")
    queue.put(SolverResult(ok=False, exit_code=1))


def _wait(pred, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _project(tmp_path, cid="c1", **kw):
    return Project(
        challenge_id=cid,
        challenge_dir=str(tmp_path),
        difficulty="easy",
        title="t",
        category="web",
        score=100,
        **kw,
    )


@pytest.fixture
def disp():
    made: list[Dispatcher] = []

    def factory(**kw):
        kw.setdefault("quiet", True)
        kw.setdefault("warmup", False)
        d = Dispatcher(**kw)
        made.append(d)
        return d

    yield factory
    for d in made:
        try:
            d.stop_all()
        except Exception:  # noqa: BLE001
            pass


# ── 1. 中断时认领队列中已通过的 flag ────────────────────────────────────

@pytest.mark.parametrize("method", ["_interrupt", "_interrupt_stopped"])
def test_interrupt_claims_queued_flag(disp, tmp_path, method):
    d = disp(solver_fn=solver_puts_flag_then_waits, max_workers=2)
    p = _project(tmp_path)
    d.add_project(p)
    d._spawn(p)
    slot = d._running["c1"]
    assert _wait(lambda: (Path(slot["work_dir"]) / "FLAG").exists(), timeout=20)

    if method == "_interrupt":
        d._interrupt("c1", slot)
    else:
        d._interrupt_stopped("c1", slot, "NO_OUTPUT")

    assert p.status is ChallengeStatus.SOLVED, p.status
    assert p.flag == FLAG
    assert p.stop_reason == ""


@pytest.mark.parametrize("method", ["_interrupt", "_interrupt_stopped"])
def test_interrupt_claims_flag_without_relay(disp, tmp_path, method):
    """已解出就不该再留下「未完成」的接力块与停止原因。"""
    d = disp(solver_fn=solver_puts_flag_then_waits, max_workers=2)
    p = _project(tmp_path)
    d.add_project(p)
    d._spawn(p)
    slot = d._running["c1"]
    assert _wait(lambda: (Path(slot["work_dir"]) / "FLAG").exists(), timeout=20)

    if method == "_interrupt":
        d._interrupt("c1", slot)
    else:
        d._interrupt_stopped("c1", slot, "NO_OUTPUT")

    assert not (Path(slot["work_dir"]) / "RELAY.md").exists()
    assert not p.stop_reason.startswith("STOPPED")
    assert "timebox expired" not in p.stop_reason


def test_interrupt_without_output_still_times_out(disp, tmp_path):
    """负例：确实无产出时按原语义判 TIMEOUT 并写接力块（认领逻辑不误判）。"""
    d = disp(solver_fn=solver_silent, max_workers=2)
    p = _project(tmp_path)
    d.add_project(p)
    d._spawn(p)
    slot = d._running["c1"]
    time.sleep(0.5)
    d._interrupt("c1", slot)

    assert p.status is ChallengeStatus.TIMEOUT
    assert (Path(slot["work_dir"]) / "RELAY.md").exists()


# ── 2. 损坏黑板降级，不终止整个 run ─────────────────────────────────────

def test_corrupt_blackboard_degrades_to_none(tmp_path):
    bad = tmp_path / "blackboard.json"
    bad.write_text("{ not json at all", encoding="utf-8")
    assert _load_blackboard_safe(bad) is None
    # 直调仍抛（证明降级发生在包装层，未改变 blackboard 模块契约）
    with pytest.raises((ValueError, json.JSONDecodeError)):
        dispatcher_mod.load_blackboard(bad)


def test_corrupt_blackboard_does_not_break_spawn_and_relay(disp, tmp_path):
    bad = tmp_path / "blackboard.json"
    bad.write_text("{ not json at all", encoding="utf-8")
    d = disp(solver_fn=solver_reports_model, max_workers=2)
    p = _project(tmp_path)
    d.add_project(p)
    assert d._spawn(p) is True          # 旧实现：JSONDecodeError 穿透 _spawn
    d._write_relay(p, d._running["c1"]["timebox"], tmp_path)  # 旧实现：此处抛
    assert (tmp_path / "RELAY.md").exists()
    d._interrupt("c1", d._running["c1"])
    assert p.status in (ChallengeStatus.TIMEOUT, ChallengeStatus.SOLVED)


def test_corrupt_blackboard_in_one_project_spares_others(disp, tmp_path):
    """一道题的黑板坏掉，不得影响同批其它题的 solver。"""
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "blackboard.json").write_text("}{", encoding="utf-8")
    good_dir = tmp_path / "good"
    good_dir.mkdir()

    d = disp(solver_fn=solver_reports_model, max_workers=3)
    p_bad = _project(bad_dir, cid="bad")
    p_ok = _project(good_dir, cid="ok")
    d.add_project(p_bad)
    d.add_project(p_ok)

    assert d._spawn(p_bad) is True
    assert d._spawn(p_ok) is True
    assert set(d._running) == {"bad", "ok"}
    assert _wait(lambda: (good_dir / "seen_model.txt").exists()), "好题的 solver 未运行"


# ── 3. 槽位注册先于 proc.start()（不留幽灵条目）─────────────────────────

def test_spawn_start_failure_leaves_no_slot(disp, tmp_path, monkeypatch):
    d = disp(solver_fn=solver_reports_model, max_workers=2)
    p = _project(tmp_path)
    d.add_project(p)

    class _BoomCtx:
        def Queue(self):
            return None

        def Process(self, target=None, args=(), name=None):
            class _P:
                pid = -1

                def start(self):
                    raise OSError("fork failed")

            return _P()

    monkeypatch.setattr(dispatcher_mod, "_SAFE_MP_CONTEXT", _BoomCtx())
    with pytest.raises(OSError):
        d._spawn(p)
    assert "c1" not in d._running


def test_spawn_returns_true_on_success(disp, tmp_path):
    """_spawn 声明 `-> bool`：成功必须返回 True（旧实现返回 None）。"""
    d = disp(solver_fn=solver_reports_model, max_workers=2)
    p = _project(tmp_path)
    d.add_project(p)
    assert d._spawn(p) is True
    assert d._spawn(p, limit=0) is False  # limit 用尽仍返回 False
