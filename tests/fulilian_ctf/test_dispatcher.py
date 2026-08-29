"""调度引擎（F2-001/002/003/007/008/010）集成测试。

使用模块级 fake solver（fork 上下文直接继承，无需 pickle），覆盖：
- 单题求解 → SOLVED
- 多题并行（独立进程、同时运行）
- 时间盒到期中断 + 接力块输出（F2-002）
- 探针 INFRA_BLOCKED 跳过（F2-003）
- 收割轮重跑已放弃的题（F2-008）
- 自动调度：新题优先 + EV 排序（F2-007）
- 难度自适应预算（F2-010）
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fulilian_ctf.dispatcher import ChallengeStatus, Dispatcher, Project
from fulilian_ctf.solver import SolverResult


@pytest.fixture(autouse=True)
def _isolate_learning_paths(tmp_path, monkeypatch):
    """_reap 会把解题结果落库到 FULILIAN_HOME（learning.json/traces）——
    所有走 Dispatcher 的测试统一隔离到 tmp_path，避免污染真实经验库。"""
    import fulilian_ctf.experiential_learning as _el

    monkeypatch.setattr(_el, "LEARNING_FILE", tmp_path / "learning.json")
    monkeypatch.setattr(_el, "TRACES_DIR", tmp_path / "traces")


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


def test_package_exports_match_all():
    """包级 __all__ 声明的每个符号都必须可导入（回归：resolve_default_model 缺失）。"""
    import fulilian_ctf

    for name in fulilian_ctf.__all__:
        assert hasattr(fulilian_ctf, name), f"fulilian_ctf.{name} declared in __all__ but not importable"
