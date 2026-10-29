"""调度引擎（F2-001/002/003/007/008/010）集成测试。

使用模块级 fake solver（fork 上下文直接继承，无需 pickle），覆盖：
- 单题求解 → SOLVED
- 多题并行（独立进程、同时运行）
- 时间盒到期中断 + 接力块输出（F2-002）
- 探针 INFRA_BLOCKED 跳过（F2-003）
- 收割轮重跑已放弃的题（F2-008）
- 自动调度：新题优先 + EV 排序（F2-007）
- 难度自适应预算（F2-010）
- P2 回归锁：Project 序列化往返（description / timebox_override）、
  探活逐题隔离（单题探活异常不得终止整轮调度）
- 补货：有空槽即补（不等所有 solver 空闲）、增量 flag 扫描记忆、
  spawn 名额失败回滚、黑板注入不整体覆盖并发写者

预修复基线（``git checkout HEAD -- fulilian_ctf/dispatcher.py`` 后跑对应
``-k``，再按 md5 恢复）::

    -k round_trip        → 1 failed（AssertionError: description 未往返）
    -k isolates_probe    → 1 failed（RuntimeError: dns exploded 直接外溢）
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    load_blackboard,
    save_blackboard,
)
from fulilian_ctf.dispatcher import ChallengeStatus, Dispatcher, Project
from fulilian_ctf.relay import build_relay, write_relay_file
from fulilian_ctf.solver import SolverResult


@pytest.fixture(autouse=True)
def _isolate_learning_paths(tmp_path, monkeypatch):
    """_reap 会把解题结果落库到 FULILIAN_HOME（learning.json/traces）——
    所有走 Dispatcher 的测试统一隔离到 tmp_path，避免污染真实经验库。"""
    import fulilian_ctf.experiential_learning as _el

    monkeypatch.setattr(_el, "_learning_file", lambda: tmp_path / "learning.json")
    monkeypatch.setattr(_el, "_traces_dir", lambda: tmp_path / "traces")


# ── 模块级 fake solver（multiprocessing fork 直接继承）────────────────────

def fake_solver_solve(project, work_dir, model, queue):
    """立即写 FLAG 并成功退出。"""
    work = Path(work_dir)
    work.joinpath("pid").write_text(str(os.getpid()))
    work.joinpath("started").write_text(str(time.time()))
    work.joinpath("FLAG").write_text("flag{test_solved}\n", encoding="utf-8")
    queue.put(SolverResult(ok=True, exit_code=0, flag="flag{test_solved}"))


def fake_solver_sleep(project, work_dir, model, queue):
    """长时间运行，等待时间盒中断。"""
    work = Path(work_dir)
    work.joinpath("pid").write_text(str(os.getpid()))
    work.joinpath("started").write_text(str(time.time()))
    time.sleep(60)
    queue.put(SolverResult(ok=True, exit_code=0))


def fake_solver_crash(project, work_dir, model, queue):
    raise RuntimeError("boom")


def fake_solver_succeed_on_second(project, work_dir, model, queue):
    """第一次失败，第二次成功（验证收割轮重跑）。"""
    work = Path(work_dir)
    marker = work / "attempts"
    n = int(marker.read_text()) if marker.exists() else 0
    marker.write_text(str(n + 1))
    if n + 1 >= 2:
        work.joinpath("FLAG").write_text("flag{harvested}\n", encoding="utf-8")
        queue.put(SolverResult(ok=True, exit_code=0, flag="flag{harvested}"))
    else:
        queue.put(SolverResult(ok=False, exit_code=1, error="attempt failed"))


def _project(cid: str, tmp_path: Path, **kw) -> Project:
    work = tmp_path / cid
    work.mkdir(parents=True, exist_ok=True)
    defaults = dict(challenge_id=cid, challenge_dir=str(work), difficulty="easy", score=100)
    defaults.update(kw)
    return Project(**defaults)


# ── 基本调度 ──────────────────────────────────────────────────────────────

def test_single_solved(tmp_path):
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_solve, quiet=True)
    d.add_project(_project("p1", tmp_path))
    summary = d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.SOLVED
    assert p.flag == "flag{test_solved}"
    assert summary["totals"]["solved"] == 1


def test_crash_marks_abandoned(tmp_path):
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_crash, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.ABANDONED
    assert "boom" in p.stop_reason


def test_parallel_processes(tmp_path):
    """两道题并行：独立进程（pid 不同）、同时运行（启动时间重叠）。"""
    d = Dispatcher(max_workers=2, solver_fn=fake_solver_solve, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.add_project(_project("p2", tmp_path))
    d.run()
    pid1 = int((tmp_path / "p1" / "pid").read_text())
    pid2 = int((tmp_path / "p2" / "pid").read_text())
    assert pid1 != pid2  # 独立进程（进程隔离）
    t1 = float((tmp_path / "p1" / "started").read_text())
    t2 = float((tmp_path / "p2" / "started").read_text())
    assert abs(t1 - t2) < 2.0  # 同时启动
    assert d.projects["p1"].status == ChallengeStatus.SOLVED
    assert d.projects["p2"].status == ChallengeStatus.SOLVED


def test_workers_cap_concurrency(tmp_path):
    """max_workers=1 时两道题串行（启动时间不重叠）。"""
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
                   timebox_override=1)
    d.add_project(_project("p1", tmp_path))
    d.add_project(_project("p2", tmp_path))
    d.run()
    t1 = float((tmp_path / "p1" / "started").read_text())
    t2 = float((tmp_path / "p2" / "started").read_text())
    assert abs(t1 - t2) > 0.5  # 串行：p2 在 p1 超时后才启动


# ── 时间盒（F2-002）───────────────────────────────────────────────────────

def test_timebox_interrupt_writes_relay(tmp_path):
    """时间盒到期 → 中断 solver 进程，标记 TIMEOUT，输出接力块。"""
    start = time.time()
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_sleep, quiet=True)
    d.add_project(_project("p1", tmp_path, timebox_override=1))
    d.run()
    elapsed = time.time() - start
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.TIMEOUT
    assert elapsed < 10  # 不会等 fake 的 60s 睡眠
    relay = (tmp_path / "p1" / "RELAY.md").read_text()
    assert "[已达成原语]" in relay
    assert "[下一步]" in relay
    assert "RESUME p1" in relay


# ── 探针（F2-003）─────────────────────────────────────────────────────────

def test_infra_blocked_skipped(tmp_path, monkeypatch):
    """探针返回 INFRA_BLOCKED → 标记跳过，不启动 solver。"""
    import fulilian_ctf.dispatcher as disp_mod

    monkeypatch.setattr(
        disp_mod, "probe_challenge", lambda host, port, timeout=60: "infra_blocked"
    )
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_solve, quiet=True)
    d.add_project(_project("p1", tmp_path, target_host="10.0.0.99", target_port=80))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.INFRA_BLOCKED
    assert p.attempts == 0  # 从未启动 solver
    assert "infra" in p.stop_reason


def test_reachable_proceeds(tmp_path, monkeypatch):
    """探针 REACHABLE → 正常启动 solver。"""
    import fulilian_ctf.dispatcher as disp_mod

    monkeypatch.setattr(
        disp_mod, "probe_challenge", lambda host, port, timeout=60: "reachable"
    )
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_solve, quiet=True)
    d.add_project(_project("p1", tmp_path, target_host="10.0.0.99", target_port=80))
    d.run()
    assert d.projects["p1"].status == ChallengeStatus.SOLVED


# ── 收割轮（F2-008）───────────────────────────────────────────────────────

def test_harvest_reruns_abandoned(tmp_path):
    """无新题时收割轮重跑已放弃的题；第二次成功 → SOLVED。"""
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_succeed_on_second,
                   max_attempts=2, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.attempts == 2  # 收割轮重跑了一次
    assert p.status == ChallengeStatus.SOLVED
    assert p.flag == "flag{harvested}"


def test_max_attempts_stops_harvest(tmp_path):
    """attempts 达上限后不再回收，调度终止（不死循环）。"""
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_crash,
                   max_attempts=2, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.attempts == 2
    assert p.status == ChallengeStatus.ABANDONED


def test_ev_ordering():
    """收割轮 EV 排序：easy 高价值 > hard 高分数 > medium。"""
    d = Dispatcher(max_workers=3, quiet=True)
    a = Project(challenge_id="easy1", difficulty="easy", score=100, attempts=1,
                status=ChallengeStatus.ABANDONED)
    b = Project(challenge_id="medium1", difficulty="medium", score=100, attempts=1,
                status=ChallengeStatus.ABANDONED)
    c = Project(challenge_id="hard1", difficulty="hard", score=200, attempts=1,
                status=ChallengeStatus.ABANDONED)
    for p in (a, b, c):
        d.add_project(p)
    order = [p.challenge_id for p in d.harvest_cycle()]
    assert order == ["easy1", "hard1", "medium1"]
    assert a.ev_score > c.ev_score > b.ev_score


def test_schedule_new_first():
    """自动调度：新题优先（score 降序），无新题才走收割轮。"""
    d = Dispatcher(max_workers=3, quiet=True)
    old = Project(challenge_id="old", difficulty="easy", score=50,
                  status=ChallengeStatus.ABANDONED, attempts=1)
    n1 = Project(challenge_id="n1", difficulty="easy", score=50)
    n2 = Project(challenge_id="n2", difficulty="easy", score=100)
    for p in (old, n1, n2):
        d.add_project(p)
    picked = d.schedule(2)
    assert [p.challenge_id for p in picked] == ["n2", "n1"]  # 新题优先
    # 无新题 → 收割轮
    for p in (n1, n2):
        p.status = ChallengeStatus.SOLVED
    picked2 = d.schedule(2)
    assert picked2 and picked2[0].challenge_id == "old"


def test_limit_caps_spawns(tmp_path):
    """--limit 限制总启动次数。"""
    d = Dispatcher(max_workers=2, solver_fn=fake_solver_crash, quiet=True)
    for i in range(3):
        d.add_project(_project(f"p{i}", tmp_path))
    d.run(limit=2)
    assert d._spawns == 2
    # 第三道题保持 NEW（未启动）
    assert d.projects["p2"].status == ChallengeStatus.NEW


def test_empty_run():
    d = Dispatcher(max_workers=2, quiet=True)
    summary = d.run()
    assert summary["totals"]["solved"] == 0


def test_summary_shape(tmp_path):
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_solve, quiet=True)
    d.add_project(_project("p1", tmp_path))
    summary = d.run()
    assert "totals" in summary and "projects" in summary and "duration" in summary
    assert set(summary["totals"].keys()) == {s.value for s in ChallengeStatus}


# ── FLAG 文件通道校验门（回归：声明式提交不得绕过三重校验门）──────────────

def fake_solver_write_bad_flag(project, work_dir, model, queue):
    """绕过 submit_flag 直接写占位 FLAG 文件（模拟 agent 越过校验门）。"""
    Path(work_dir).joinpath("FLAG").write_text("flag{...}\n", encoding="utf-8")
    queue.put(SolverResult(ok=True, exit_code=0, flag="flag{...}"))


def test_flag_file_channel_passes_gate(tmp_path):
    """FLAG 文件声明内容未过校验门 → 不判 SOLVED，降级 ABANDONED 并注明原因。"""
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_write_bad_flag, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.ABANDONED
    assert p.flag == ""
    assert "rejected by gate" in p.stop_reason


# ── 探活逐题隔离（回归：单题探活异常终止整轮多题调度）────────────────────

def test_spawn_candidates_isolates_probe_exception(tmp_path, monkeypatch):
    """一个候选探活抛异常时：不得外溢，其余候选照常处理。

    ``ex.map`` 会把单题异常重抛给调用方，于是 ``_spawn_candidates`` 当场
    中断、后面的候选连探活都不做，最终由 ``run()`` 的 ``except BaseException``
    终止整轮多题调度。
    """
    d = Dispatcher(max_workers=2, solver_fn=fake_solver_solve, quiet=True)
    a = _project("a", tmp_path)
    bad = _project("bad", tmp_path)
    c = _project("c", tmp_path)
    seen: list[str] = []

    # 注意签名要带 self：往类上挂普通函数后仍走描述符绑定，
    # self._probe_and_maybe_spawn(project, ...) 会额外传入实例。
    def fake_probe(self, project, limit=None):
        seen.append(project.challenge_id)
        if project.challenge_id == "bad":
            raise RuntimeError("dns exploded")
        return True

    monkeypatch.setattr(Dispatcher, "_probe_and_maybe_spawn", fake_probe)

    d._spawn_candidates([a, bad, c], limit=None)  # 不得抛出

    assert sorted(seen) == ["a", "bad", "c"]  # 崩溃之后的候选仍被处理
    assert "probe error" in bad.stop_reason
    assert "dns exploded" in bad.stop_reason
    # 代码异常 ≠ 环境不可达：不许标成 INFRA_BLOCKED（那会让整题被跳过）
    assert bad.status == ChallengeStatus.NEW
    assert a.stop_reason == "" and c.stop_reason == ""


# ── Project 序列化往返（回归：description / timebox_override 静默丢失）──────

def test_project_round_trip_preserves_all_fields():
    """``to_dict`` → ``from_dict`` 必须逐字段还原。

    旧 ``to_dict`` 漏发 ``description`` 与 ``timebox_override``：状态文件里
    没有这两项，重启后 from_dict 只能退回默认值 —— description 是题干/提示
    的唯一载体，timebox_override 又直接决定时间盒（丢回 None 等于用默认预算
    重跑一道已被人工调过预算的题），两者都是静默劣化。
    """
    src = Project(
        challenge_id="rt-01",
        category="web",
        difficulty="hard",
        score=500,
        status=ChallengeStatus.SOLVED,
        attempts=3,
        ev_score=12.5,
        flag="flag{round_trip}",
        model="deepseek-flash",
        challenge_dir="/tmp/rt-01",
        target_host="10.0.0.9",
        target_port=8080,
        title="Backup Leak",
        description="题干：在 backup.rar 里找 flag",
        stop_reason="solved",
        last_tier="hard",
        started_at=1234.5,
        finished_at=1300.0,
        timebox_override=42,
    )
    back = Project.from_dict(src.to_dict())

    for fname in src.__dataclass_fields__:
        assert getattr(back, fname) == getattr(src, fname), f"{fname} 未往返"


def test_package_exports_match_all():
    """包级 __all__ 声明的每个符号都必须可导入（回归：resolve_default_model 缺失）。"""
    import fulilian_ctf

    for name in fulilian_ctf.__all__:
        assert hasattr(fulilian_ctf, name), f"fulilian_ctf.{name} declared in __all__ but not importable"


# ── 补货（回归：主循环只在所有 solver 空闲时才补货，空槽长期闲置）─────────

def fake_solver_gated(project, work_dir, model, queue):
    """按题分流：p1 长跑（等 release 放行），p2 快速结束，p3 快速结束并放行 p1。

    release 由 p3 写出而不是 p2：保证「p1 退出」严格晚于「p3 已启动」，
    使下面的时间断言免受 p1/p2 收割竞态影响；15s 兜底让旧实现下测试
    也能自终（只是断言失败），不会挂死。
    """
    work = Path(work_dir)
    work.joinpath("pid").write_text(str(os.getpid()))
    work.joinpath("started").write_text(str(time.time()))
    cid = project.challenge_id
    if cid == "p1":
        release = work / "release"
        deadline = time.time() + 15
        while not release.exists() and time.time() < deadline:
            time.sleep(0.05)
    else:
        if cid == "p3":
            (work.parent / "p1" / "release").write_text("go")
        time.sleep(0.2)
    queue.put(SolverResult(ok=True, exit_code=0))


def test_replenishes_free_slot_while_long_solver_running(tmp_path):
    """max_workers=2：第 2 题结束后第 3 题立即补位，不等第 1 题长跑结束。

    旧主循环把补货块包在 ``if not self._running:`` 里：p2 结束让出的空槽
    一直闲置，p3 要等 p1（15s 兜底超时）退出后才会 spawn。修复后 p3 在
    p2 被收割后的下一个轮询周期内启动，此时 p1 仍在等 release——即 p3
    的启动时刻必须早于 p1 的 finished_at。
    """
    d = Dispatcher(max_workers=2, solver_fn=fake_solver_gated, quiet=True,
                   max_attempts=1)  # fake solver 不产出 flag，避免收割轮反复 respawn
    for cid in ("p1", "p2", "p3"):
        d.add_project(_project(cid, tmp_path))
    d.run()

    assert d._spawns == 3
    t3 = float((tmp_path / "p3" / "started").read_text())
    # p3 启动时 p1 还在跑（旧实现下 p3 只能等 p1 退出后才 spawn）
    assert t3 < d.projects["p1"].finished_at


# ── 增量 flag 扫描（回归：日志停止增长后 has_partial_flag 回落）───────────

def test_incremental_flag_scan_remembers_flag_when_log_idle(tmp_path):
    """增量检出 flag 后日志无增长 → 布尔语义仍为 True（临门不弃不丢）。

    旧实现只看"本轮新增字节"，日志停止增长后返回值从 True 回落为
    False，NO_OUTPUT 止损可能提前杀掉已打出 flag 的 solver。
    """
    d = Dispatcher(max_workers=1, quiet=True)
    work = tmp_path / "p1"
    work.mkdir(parents=True)
    slot = {"scan_offset": 0, "scan_tail": "", "flag_seen": False}
    log = work / "solver.log"
    log.write_text("enumerating...\nflag{real_flag_42}\n", encoding="utf-8")

    assert d._incremental_flag_scan(slot, work) is True
    # 日志无增长：不得回落
    assert d._incremental_flag_scan(slot, work) is True
    assert slot["flag_seen"] is True
    # 截断重写（新尝试）→ 记忆随日志内容失效，与全量扫描布尔语义一致
    log.write_text("fresh attempt, no flag yet\n", encoding="utf-8")
    assert d._incremental_flag_scan(slot, work) is False
    with log.open("a", encoding="utf-8") as f:
        f.write("then flag{real_flag_42} appears\n")
    assert d._incremental_flag_scan(slot, work) is True


# ── spawn 名额（回归：注入失败路径名额多计，limit 提前耗尽）───────────────

def test_spawn_slot_not_consumed_when_inject_fails(tmp_path, monkeypatch):
    """RELAY 回注黑板抛 OSError → spawn 名额不得被消耗。"""
    def boom(self, work_dir):
        raise OSError("disk full")

    monkeypatch.setattr(Dispatcher, "_inject_relay_into_board", boom)
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_solve, quiet=True)
    project = _project("p1", tmp_path)

    with pytest.raises(OSError):
        d._spawn(project, limit=None)

    assert d._spawns == 0  # 名额未消耗（旧实现此处为 1，limit 被泄漏）
    assert not d._running  # 无幽灵槽位
    assert project.status == ChallengeStatus.NEW
    assert project.attempts == 0


# ── 黑板注入（回归：覆盖式保存丢掉并发写者落盘的内容）─────────────────────

def test_inject_relay_preserves_concurrent_writer_facts(tmp_path):
    """注入 RELAY 后，磁盘黑板上并发写者的 Fact 仍在（锁内 RMW，非整体覆盖）。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True)
    # 先落一份含"别人"Fact 的黑板（模拟并发写者已写盘），再放 RELAY.md
    board = Blackboard()
    board.add_fact(Fact(content="并发写者的独家 Fact", source="solver"))
    save_blackboard(board, work / BLACKBOARD_FILENAME)
    write_relay_file(work, build_relay(
        achieved_primitives=["已拿到 login shell"],
        dead_ends=["sqlmap 全参数盲注"],
        next_steps=["RESUME p1: continue"],
    ))

    d = Dispatcher(max_workers=1, quiet=True)
    d._inject_relay_into_board(work)

    after = load_blackboard(work / BLACKBOARD_FILENAME)
    contents = {f.content for f in after.get_facts()}
    assert "并发写者的独家 Fact" in contents  # 整体覆盖写会丢掉它
    assert "已拿到 login shell" in contents  # relay 原语已注入
    assert "sqlmap 全参数盲注" in after.dead_ends
