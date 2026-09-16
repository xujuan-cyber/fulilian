"""止损与续接集成测试（F2-004 / F2-011 / F2-012）。

覆盖实施指南 07-P2-止损与续接.md 的调度器集成：
- 预算超限 → 终止 solver（ABANDONED + STOPPED: BUDGET_EXCEEDED + RELAY.md）
- 连续 N 轮无新 Fact → 终止（NO_OUTPUT）；有增长则重置
- 同一攻击类 3 次变体失败 → 强制切换（HYPOTHESIS_REPEATED）
- 多 flag 链临门不弃：已拿 flag 预算放大，750K 不终止（时间盒兜底）
- --no-stop-loss 关闭止损后不终止
- RELAY.md → 黑板死路/原语注入（续接不重复侦察）
- 续接查询注入「下一步」（solver 从下一步开始）
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fulilian_ctf.blackboard import (
    Blackboard,
    Fact,
    Intent,
    load_blackboard,
    save_blackboard,
)
from fulilian_ctf.dispatcher import ChallengeStatus, Dispatcher, Project
from fulilian_ctf.relay import build_relay, write_relay_file
from fulilian_ctf.solver import SolverResult, build_solve_query


@pytest.fixture(autouse=True)
def _isolate_learning_paths(tmp_path, monkeypatch):
    """_reap 会把解题结果落库到 FULILIAN_HOME（learning.json/traces）——
    所有走 Dispatcher 的测试统一隔离到 tmp_path，避免污染真实经验库。"""
    import fulilian_ctf.experiential_learning as _el

    monkeypatch.setattr(_el, "_learning_file", lambda: tmp_path / "learning.json")
    monkeypatch.setattr(_el, "_traces_dir", lambda: tmp_path / "traces")


# ── 模块级 fake solver（multiprocessing fork 直接继承）────────────────────

def fake_solver_sleep(project, work_dir, model, queue):
    """长时间运行，等待止损/时间盒中断。"""
    work = Path(work_dir)
    work.joinpath("pid").write_text(str(os.getpid()))
    time.sleep(60)
    queue.put(SolverResult(ok=True, exit_code=0))


def fake_solver_succeed(project, work_dir, model, queue):
    """立即写 FLAG 并成功退出。"""
    work = Path(work_dir)
    work.joinpath("FLAG").write_text("flag{ok}\n", encoding="utf-8")
    queue.put(SolverResult(ok=True, exit_code=0, flag="flag{ok}"))


def _project(cid: str, tmp_path: Path, **kw) -> Project:
    work = tmp_path / cid
    work.mkdir(parents=True, exist_ok=True)
    defaults = dict(challenge_id=cid, challenge_dir=str(work), difficulty="easy", score=100)
    defaults.update(kw)
    return Project(**defaults)


# ── 维度 1：预算超限终止 solver ──────────────────────────────────────────

def test_budget_exceeded_stops_solver(tmp_path):
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,  # 显式锚定（2026-09-04：默认值改为按难度分档）
        token_counter=lambda wd: 600_000,  # 注入精确计数器：超过 500K
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.ABANDONED
    assert p.stop_reason.startswith("STOPPED: BUDGET_EXCEEDED")
    relay = (tmp_path / "p1" / "RELAY.md").read_text()
    assert "stop-loss 'BUDGET_EXCEEDED'" in relay  # 接力块带止损原因


def test_budget_within_limit_not_stopped(tmp_path):
    """token 在预算内 → 不触发止损（时间盒兜底）。"""
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,
        token_counter=lambda wd: 100, timebox_override=1,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.TIMEOUT
    assert not p.stop_reason.startswith("STOPPED")


# ── 维度 2：无产出终止 ───────────────────────────────────────────────────

def test_no_output_stops_solver(tmp_path):
    work = tmp_path / "p1"
    save_blackboard(Blackboard(challenge_id="p1"), work / "blackboard.json")
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_no_output_rounds=1, no_output_round_seconds=0.1,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.ABANDONED
    assert p.stop_reason.startswith("STOPPED: NO_OUTPUT")


def test_no_board_skips_no_output_dimension(tmp_path):
    """无黑板文件 → 无产出维度无法判定，不误杀（默认流程兼容）。"""
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_no_output_rounds=1, timebox_override=1,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.TIMEOUT  # 未被止损，时间盒兜底
    assert not p.stop_reason.startswith("STOPPED")


def test_fact_growth_resets_no_output_rounds(tmp_path):
    """新 Fact 出现 → 无产出重置；黑板/日志都不变才按停滞时长累计到阈值。

    「轮」是时间基准（1 轮 = no_output_round_seconds 秒无任何进展），
    与调度器轮询频率解耦——高频轮询不会加速累计。
    """
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    d = Dispatcher(max_workers=1, quiet=True, max_no_output_rounds=3,
                   no_output_round_seconds=60)
    slot = {
        "project": Project(challenge_id="p1", challenge_dir=str(work)),
        "work_dir": work,
        "no_output_rounds": 0,
        "last_fact_count": 0,
    }
    # 无黑板：维度跳过，不累计
    assert d._stop_reason_for(slot) is None
    assert slot["no_output_rounds"] == 0
    # 黑板存在：首拍建立基准（log_size 初始化），记为有进展
    save_blackboard(Blackboard(challenge_id="p1"), work / "blackboard.json")
    assert d._stop_reason_for(slot) is None
    assert slot["no_output_rounds"] == 0
    # 高频轮询不加速累计：连续多拍（无进展、时间未推进）仍是 0 轮
    assert d._stop_reason_for(slot) is None
    assert d._stop_reason_for(slot) is None
    assert slot["no_output_rounds"] == 0
    # 停滞 130s（= 2 轮 @60s/轮）→ 累计 2 轮
    slot["last_progress_time"] = time.time() - 130
    assert d._stop_reason_for(slot) is None
    assert slot["no_output_rounds"] == 2
    # 新 Fact → 重置
    board = load_blackboard(work / "blackboard.json")
    board.add_fact(Fact(content="new discovery", source="test"))
    save_blackboard(board, work / "blackboard.json")
    assert d._stop_reason_for(slot) is None
    assert slot["no_output_rounds"] == 0
    # 再停滞 200s（= 3 轮）→ NO_OUTPUT
    slot["last_progress_time"] = time.time() - 200
    assert d._stop_reason_for(slot) == "NO_OUTPUT"


def test_log_growth_counts_as_progress(tmp_path):
    """solver.log 增长也算进展（agent 未接黑板时止损不误杀活跃 solver）。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    save_blackboard(Blackboard(challenge_id="p1"), work / "blackboard.json")
    d = Dispatcher(max_workers=1, quiet=True, max_no_output_rounds=2,
                   no_output_round_seconds=60)
    slot = {
        "project": Project(challenge_id="p1", challenge_dir=str(work)),
        "work_dir": work,
        "no_output_rounds": 0,
        "last_fact_count": 0,
    }
    d._stop_reason_for(slot)  # 首拍建基准
    slot["last_progress_time"] = time.time() - 300
    (work / "solver.log").write_text("agent still working...\n", encoding="utf-8")
    assert d._stop_reason_for(slot) is None
    assert slot["no_output_rounds"] == 0  # 日志增长 → 重置


# ── 维度 4：假设空间重复 ─────────────────────────────────────────────────

def test_hypothesis_repeated_stops_solver(tmp_path):
    work = tmp_path / "p1"
    board = Blackboard(challenge_id="p1")
    board.add_intent(Intent(goal="CVE-2021-41773", approach="curl", variant_count=3))
    save_blackboard(board, work / "blackboard.json")
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
                   max_variant_failures=3)  # 显式锚定（默认值 2026-09-04 起为 7）
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.ABANDONED
    assert p.stop_reason.startswith("STOPPED: HYPOTHESIS_REPEATED")


# ── 临门不弃（F2-011）───────────────────────────────────────────────────

def test_partial_flag_doubles_budget_integration(tmp_path):
    """已拿到至少一个 flag：750K（>500K 但 <1M 放大后）不触发止损，时间盒兜底。
    max_tokens 显式锚定 500K（默认值已改按难度分档，easy 题 200K 分档
    不适用于本用例的旧语义）。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    (work / "FLAG").write_text("flag{first}\n", encoding="utf-8")  # 已解出第一枚
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,
        token_counter=lambda wd: 750_000, timebox_override=2,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.TIMEOUT  # 未被止损，时间盒到期
    assert not p.stop_reason.startswith("STOPPED")


def test_no_flag_budget_exceeded_stops(tmp_path):
    """对照：无 flag 时 750K 超限 → 立即止损。"""
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,
        token_counter=lambda wd: 750_000,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.ABANDONED
    assert p.stop_reason.startswith("STOPPED: BUDGET_EXCEEDED")


# ── 开关：--no-stop-loss ────────────────────────────────────────────────

def test_stop_loss_disabled(tmp_path):
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,
        token_counter=lambda wd: 10**9, timebox_override=1, stop_loss=False,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.TIMEOUT  # 止损关闭 → 时间盒兜底
    assert not p.stop_reason.startswith("STOPPED")


# ── 续接：RELAY.md → 黑板注入（07 指南集成步骤 1）────────────────────────

def test_relay_injected_into_blackboard(tmp_path):
    work = tmp_path / "p1"
    save_blackboard(Blackboard(challenge_id="p1"), work / "blackboard.json")
    write_relay_file(
        work,
        build_relay(
            achieved_primitives=["port 80 open", "apache 2.4.49"],
            dead_ends=["CVE-2021-41773 not exploitable"],
            next_steps=["try CVE-2021-42013"],
        ),
    )
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_succeed, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.run()
    board = load_blackboard(work / "blackboard.json")
    assert "CVE-2021-41773 not exploitable" in board.dead_ends  # 死路免疫
    contents = [f.content for f in board.get_facts()]
    assert "port 80 open" in contents
    assert "apache 2.4.49" in contents
    assert any(f.source == "relay" for f in board.get_facts())


def test_relay_without_board_untouched(tmp_path):
    """无黑板文件时注入为 no-op（不创建黑板，不报错）。"""
    work = tmp_path / "p1"
    write_relay_file(work, build_relay(["a"], ["dead"], ["next"]))
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_succeed, quiet=True)
    d.add_project(_project("p1", tmp_path))
    d.run()
    assert not (work / "blackboard.json").exists()


# ── 续接：solver 查询从「下一步」开始（不重复侦察）────────────────────────

def test_build_solve_query_includes_relay():
    p = Project(challenge_id="web-01", difficulty="easy")
    relay_text = build_relay(
        ["port 80 open"], ["CVE-2021-41773 404"], ["try CVE-2021-42013"]
    )
    q = build_solve_query(p, relay_text)
    assert "resume from [下一步]" in q
    assert "try CVE-2021-42013" in q  # 下一步注入
    assert "CVE-2021-41773 404" in q  # 死路注入（不再重复侦察）
    # 无 relay：不含续接指令
    assert "resume" not in build_solve_query(p)


# ── 回归：预算耗尽不进收割轮（重跑必再撞墙）──────────────────────────────

def test_budget_exceeded_not_harvested(tmp_path):
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,  # 显式锚定（2026-09-04：默认改为不限 token，预算保险丝需显式启用）
        token_counter=lambda wd: 600_000, max_attempts=3,
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    p = d.projects["p1"]
    assert p.stop_reason.startswith("STOPPED: BUDGET_EXCEEDED")
    assert p.attempts == 1  # 不被收割轮重跑空耗 attempts


# ── 回归：占位 FLAG 不算临门不弃（与声明式提交同口径过校验门）────────────

def test_placeholder_flag_not_partial_flag(tmp_path):
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    (work / "FLAG").write_text("flag{...}\n", encoding="utf-8")  # 占位内容
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_sleep, quiet=True,
        max_tokens=500_000,  # 显式锚定（默认不限 token；测保险丝维度需显式预算）
        token_counter=lambda wd: 750_000,  # >500K：<1M 若被误判 partial 会存活
    )
    d.add_project(_project("p1", tmp_path))
    d.run()
    assert d.projects["p1"].stop_reason.startswith("STOPPED: BUDGET_EXCEEDED")


# ── 回归：RELAY→黑板注入幂等（不随重跑繁殖重复 Fact）────────────────────

def test_relay_injection_idempotent(tmp_path):
    work = tmp_path / "p1"
    save_blackboard(Blackboard(challenge_id="p1"), work / "blackboard.json")
    write_relay_file(
        work,
        build_relay(
            achieved_primitives=[
                "solver ran 60s at tier 'short' (budget 60s); progress log: x/solver.log",
                "port 80 open",
            ],
            dead_ends=["dead-1"],
            next_steps=["RESUME: try x"],
        ),
    )
    d = Dispatcher(max_workers=1, quiet=True)
    d._inject_relay_into_board(work)
    d._inject_relay_into_board(work)  # 重复注入（模拟多次重跑）
    board = load_blackboard(work / "blackboard.json")
    contents = [f.content for f in board.get_facts()]
    assert contents.count("port 80 open") == 1  # 不繁殖
    assert not any(c.startswith("solver ran ") for c in contents)  # 运行时行不入黑板
    assert "dead-1" in board.dead_ends


# ── 回归：solver 侧黑板接线（真实链路闭环）───────────────────────────────

def test_solver_worker_bootstraps_blackboard(tmp_path):
    """真实 solver_worker 启动即创建黑板、注入接力块（无产出维度数据源闭环）。"""
    import multiprocessing

    import fulilian_ctf.solver as solver_mod

    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    write_relay_file(
        work, build_relay(["port 80 open"], ["dead-end-1"], ["RESUME: try x"])
    )
    p = Project(challenge_id="p1", challenge_dir=str(work), difficulty="easy")
    q = multiprocessing.Queue()
    solver_mod.solver_worker(p, str(work), "", q, solver_impl=lambda pr, wd, query: 0)
    board = load_blackboard(work / "blackboard.json")
    assert board is not None
    assert "dead-end-1" in board.dead_ends  # 接力块死路入免疫集
    contents = [f.content for f in board.get_facts()]
    assert "port 80 open" in contents  # 原语注入（source=relay）
    assert any(c.startswith("solver attempt") for c in contents)  # attempt 开始 Fact
    assert any(c.startswith("solver attempt") and "finished" in c for c in contents)
# ── 经验落库接线（F3-003/F3-004）：_reap → record_solve_outcome ──────────

def fake_solver_solved_with_facts(project, work_dir, model, queue):
    """写 FLAG + 预置黑板 2 个 Fact，模拟 solver 产出。"""
    from fulilian_ctf.blackboard import (
        BLACKBOARD_FILENAME,
        Blackboard,
        Fact,
        save_blackboard,
    )

    work = Path(work_dir)
    work.joinpath("FLAG").write_text("flag{learn}\n", encoding="utf-8")
    board = Blackboard(challenge_id=project.challenge_id)
    board.add_fact(Fact(content="sqlmap tamper=space2comment bypassed WAF", source="solver"))
    board.add_fact(Fact(content="union select via /api/search", source="solver"))
    save_blackboard(board, work / BLACKBOARD_FILENAME)
    queue.put(SolverResult(ok=True, exit_code=0, flag="flag{learn}"))


def fake_solver_fail_no_flag(project, work_dir, model, queue):
    """立即退出且无 FLAG → 正常 reap 路径判 ABANDONED（非止损路径）。"""
    queue.put(SolverResult(ok=False, exit_code=1, error="no luck"))


def test_reap_records_solve_outcome(tmp_path, monkeypatch):
    """SOLVED 收割后经验落库：trace 写入 + 黑板 Fact 提取进 learning.json。"""
    import json

    import fulilian_ctf.experiential_learning as el

    monkeypatch.setattr(el, "_learning_file", lambda: tmp_path / "learning.json")
    monkeypatch.setattr(el, "_traces_dir", lambda: tmp_path / "traces")
    d = Dispatcher(max_workers=1, solver_fn=fake_solver_solved_with_facts, quiet=True)
    d.add_project(_project("p1", tmp_path, category="web"))
    d.run()
    p = d.projects["p1"]
    assert p.status == ChallengeStatus.SOLVED
    # trace 文件落盘
    assert (tmp_path / "traces" / "p1.json").exists()
    # learning.json 存在，entries 来自黑板 fact，index 有对应键
    assert (tmp_path / "learning.json").exists()
    data = json.loads((tmp_path / "learning.json").read_text(encoding="utf-8"))
    techniques = [e["technique"] for e in data["entries"]]
    assert "sqlmap tamper=space2comment bypassed WAF" in techniques
    assert data["index"]["web::sqlmap tamper=space2comment bypassed WAF"]["success"] == 1


def test_reap_records_abandoned_outcome(tmp_path, monkeypatch):
    """ABANDONED 收割同样落经验（success=False），flag 为空。"""
    import json

    import fulilian_ctf.experiential_learning as el

    monkeypatch.setattr(el, "_learning_file", lambda: tmp_path / "learning.json")
    monkeypatch.setattr(el, "_traces_dir", lambda: tmp_path / "traces")
    work = tmp_path / "p1"
    board = Blackboard(challenge_id="p1")
    board.add_fact(Fact(content="bruteforce with RockYou wordlist", source="solver"))
    save_blackboard(board, work / "blackboard.json")
    d = Dispatcher(
        max_workers=1, solver_fn=fake_solver_fail_no_flag, quiet=True,
    )
    d.add_project(_project("p1", tmp_path, category="crypto"))
    d.run()
    assert d.projects["p1"].status == ChallengeStatus.ABANDONED
    assert (tmp_path / "traces" / "p1.json").exists()
    data = json.loads((tmp_path / "learning.json").read_text(encoding="utf-8"))
    assert "bruteforce with RockYou wordlist" in [
        e["technique"] for e in data["entries"]
    ]
    assert all(not e["success"] for e in data["entries"])
    assert data["index"]["crypto::bruteforce with RockYou wordlist"]["fail"] == 1
    assert d.projects["p1"].flag == ""


def test_build_solve_query_injects_avoid_list(tmp_path, monkeypatch):
    """知识卡之后注入历史教训；无失败记录时不注入。"""
    import fulilian_ctf.experiential_learning as el

    monkeypatch.setattr(el, "_learning_file", lambda: tmp_path / "learning.json")
    el.record_lesson("old-1", "web", "sqlmap --batch 被封 IP", success=False)
    el.record_lesson("old-2", "web", "无过滤直接 union 注入", success=False)
    p = Project(challenge_id="web-02", category="web", difficulty="easy")
    q = build_solve_query(p)
    assert "## 历史失败教训" in q
    assert "sqlmap --batch 被封 IP" in q
    # 无失败记录 → 不注入
    monkeypatch.setattr(el, "_learning_file", lambda: tmp_path / "empty.json")
    assert "历史失败教训" not in build_solve_query(p)
    # 无分类 → 不查询不注入
    p2 = Project(challenge_id="misc-01", difficulty="easy")
    monkeypatch.setattr(el, "_learning_file", lambda: tmp_path / "learning.json")
    assert "历史失败教训" not in build_solve_query(p2)
