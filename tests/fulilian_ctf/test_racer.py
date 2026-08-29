"""多模型竞速 + Coordinator LLM（F3-005 / F3-006）集成测试。

使用注入的 fake solver（fork 上下文直接继承，无需 pickle），覆盖：
- 第一个找到 flag 的 racer 停止其他（F3-005 验收）
- 畸形 FLAG（不过校验门）不算解出
- 竞速结束后父工作目录 FLAG / 黑板合并（胜者 Fact + 全部死路）
- 模型列表解析（显式 / config / 默认回退）
- coordinator_advice：注入 LLM 正常路径 + LLM 失败启发式降级（F3-006）
- CoordinatorLoop.tick_once 写 Hint 回黑板
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
    Hint,
    State,
    load_blackboard,
    save_blackboard,
)
from fulilian_ctf.dispatcher import Project
from fulilian_ctf.racer import (
    CoordinatorLoop,
    RaceResult,
    coordinator_advice,
    model_slug,
    resolve_race_models,
    run_race,
)
from fulilian_ctf.solver import SolverResult


@pytest.fixture(autouse=True)
def _isolate_default_model(tmp_path, monkeypatch):
    """测试不依赖真实 config：默认模型解析固定为可预测值。"""
    import fulilian_ctf.racer as _racer

    monkeypatch.setattr(_racer, "resolve_default_model", lambda: "test-model-a")


# ── fake solver ───────────────────────────────────────────────────────────

def fake_racer_slow(project, work_dir, model, queue):
    """慢 racer：5 秒后写 FLAG（应被先解出者终止，never 上报）。"""
    time.sleep(5)
    Path(work_dir, "FLAG").write_text("flag{slow}\n", encoding="utf-8")
    queue.put(SolverResult(ok=True, exit_code=0))


def _make_fast(flag: str = "flag{winner}"):
    def _impl(project, work_dir, model, queue):
        # 快 racer：把旗子写进自己的目录（哪个目录由 project 的子目录决定）
        Path(work_dir, "FLAG").write_text(flag + "\n", encoding="utf-8")
        queue.put(SolverResult(ok=True, exit_code=0))
    return _impl


def fake_racer_bad_flag(project, work_dir, model, queue):
    """畸形 FLAG：过不了三重校验门。"""
    Path(work_dir, "FLAG").write_text("not-a-flag-placeholder\n", encoding="utf-8")
    queue.put(SolverResult(ok=True, exit_code=0))


# ── F3-005 竞速 ───────────────────────────────────────────────────────────

def test_race_first_flag_stops_others(tmp_path):
    """第一个找到 flag 的 racer 胜出，慢 racer 被提前终止（总耗时 < 5s）。"""
    project = Project(challenge_id="race-01", challenge_dir=str(tmp_path / "race-01"))

    # 让慢 racer 挂着：第一个模型快解出，第二个模型永远睡
    def two_models(project_, work_dir_, model_, queue_):
        if model_.endswith("fast"):
            _make_fast()(project_, work_dir_, model_, queue_)
        else:
            time.sleep(5)

    started = time.time()
    result = run_race(
        project,
        models=["test/fast", "test/slow"],
        timeout=30,
        solver_fn=two_models,
        coordinator=False,
        quiet=True,
    )
    elapsed = time.time() - started

    assert isinstance(result, RaceResult)
    assert result.solved
    assert result.flag == "flag{winner}"
    assert result.winner_model == "test/fast"
    # 慢 racer（还在睡）必须被终止，而不是等满 5 秒
    assert elapsed < 4.0, f"race took {elapsed:.1f}s — slow racer was not stopped"
    # 每个 racer 一条结果
    assert [r.model for r in result.results] == ["test/fast", "test/slow"]


def test_race_writes_flag_and_merges_board(tmp_path):
    """胜者 flag 回写父工作目录；黑板合并胜者 Fact 与败者死路。"""
    base = tmp_path / "chall"
    project = Project(challenge_id="race-02", challenge_dir=str(base))

    def impl(project_, work_dir_, model_, queue_):
        d = Path(work_dir_)
        d.joinpath("FLAG").write_text("flag{merge-me}\n", encoding="utf-8")
        # racer 自己的黑板：发现 + 死路
        board = Blackboard(challenge_id=project_.challenge_id)
        board.add_fact(Fact(content="found suspicious endpoint /admin", source="solver"))
        board.mark_dead_end("tried sqli on login")
        save_blackboard(board, d / BLACKBOARD_FILENAME)
        queue_.put(SolverResult(ok=True, exit_code=0))

    result = run_race(
        project, models=["test/only"], timeout=20,
        solver_fn=impl, coordinator=False, quiet=True,
    )

    assert result.solved
    assert (base / "FLAG").read_text().strip() == "flag{merge-me}"
    parent_board = load_blackboard(base / BLACKBOARD_FILENAME)
    assert parent_board is not None
    contents = {f.content for f in parent_board.get_facts()}
    assert "found suspicious endpoint /admin" in contents
    assert "tried sqli on login" in parent_board.dead_ends


def test_race_rejects_invalid_flag(tmp_path):
    """畸形 FLAG 过不了校验门：不判胜出。"""
    project = Project(challenge_id="race-03", challenge_dir=str(tmp_path / "r3"))
    result = run_race(
        project, models=["test/bad"], timeout=20,
        solver_fn=fake_racer_bad_flag, coordinator=False, quiet=True,
    )
    assert not result.solved
    assert result.flag == ""


def test_race_all_timeout(tmp_path):
    """全局时间盒到期：仍在跑的 racer 被终止，返回未解出。"""
    project = Project(challenge_id="race-04", challenge_dir=str(tmp_path / "r4"))
    started = time.time()
    result = run_race(
        project, models=["test/sleepy"], timeout=2,
        solver_fn=lambda p, w, m, q: time.sleep(30),
        coordinator=False, quiet=True,
    )
    assert not result.solved
    assert time.time() - started < 10


def test_race_solver_crash_isolated(tmp_path):
    """单个 racer 崩溃不影响其他（进程隔离语义）。"""
    project = Project(challenge_id="race-05", challenge_dir=str(tmp_path / "r5"))

    def impl(project_, work_dir_, model_, queue_):
        if model_.endswith("crash"):
            raise RuntimeError("boom")
        _make_fast("flag{crash-ok}")(project_, work_dir_, model_, queue_)

    result = run_race(
        project, models=["test/crash", "test/ok"], timeout=20,
        solver_fn=impl, coordinator=False, quiet=True,
    )
    assert result.solved
    assert result.winner_model == "test/ok"


# ── 模型列表解析 ──────────────────────────────────────────────────────────

def test_resolve_race_models_explicit_string():
    assert resolve_race_models("a:b , b:c,a:b") == ["a:b", "b:c"]


def test_resolve_race_models_fallback_default(monkeypatch):
    import fulilian_ctf.racer as _racer

    monkeypatch.setattr(_racer, "resolve_default_model", lambda: "fallback-model")
    assert resolve_race_models(None) == ["fallback-model"]


def test_resolve_race_models_none_available(monkeypatch):
    import fulilian_ctf.racer as _racer

    monkeypatch.setattr(_racer, "resolve_default_model", lambda: "")
    with pytest.raises(ValueError):
        resolve_race_models(None)


def test_model_slug():
    assert model_slug("openrouter:deepseek/deepseek-v4-flash") == "openrouter-deepseek-deepseek-v4-flash"
    assert model_slug("") == "model"


# ── F3-006 Coordinator LLM ───────────────────────────────────────────────

def _board_data() -> dict:
    from fulilian_ctf.blackboard import Intent

    board = Blackboard(challenge_id="c")
    board.add_fact(Fact(content="port 80 open (nginx)", source="nmap"))
    board.add_intent(Intent(goal="probe /admin", approach="dirbust"))
    return board.to_dict()


def test_coordinator_advice_with_injected_llm():
    data = _board_data()
    prompts: list[str] = []
    advice = coordinator_advice(
        data, llm_fn=lambda prompt: (prompts.append(prompt), "- 建议一\n- 建议二\n- 建议三")[1]
    )
    assert advice.count("- ") >= 3
    # prompt 应包含黑板状态
    assert "port 80 open (nginx)" in prompts[0]
    assert "probe /admin" in prompts[0]


def test_coordinator_advice_llm_failure_degrades():
    """LLM 抛异常 → 启发式降级，不阻断。"""
    data = _board_data()

    def boom(prompt):
        raise RuntimeError("api down")

    advice = coordinator_advice(data, llm_fn=boom)
    assert advice.strip()
    assert "- " in advice


def test_coordinator_advice_empty_llm_degrades():
    data = _board_data()
    advice = coordinator_advice(data, llm_fn=lambda prompt: "   ")
    assert advice.strip()


def test_coordinator_loop_writes_hint(tmp_path):
    """CoordinatorLoop.tick_once：建议写入黑板 Hint 并记录。"""
    board = Blackboard(challenge_id="c")
    board.add_fact(Fact(content="find nginx", source="s"))
    save_blackboard(board, tmp_path / BLACKBOARD_FILENAME)

    loop = CoordinatorLoop(tmp_path / BLACKBOARD_FILENAME, interval=999, llm_fn=lambda p: "- do X")
    advice = loop.tick_once()
    assert advice == "- do X"
    assert loop.advices == ["- do X"]

    reloaded = load_blackboard(tmp_path / BLACKBOARD_FILENAME)
    hints = [h.content for h in reloaded.hints if h.source == "coordinator"]
    assert hints == ["- do X"]


def test_coordinator_loop_missing_board(tmp_path):
    loop = CoordinatorLoop(tmp_path / "missing.json", interval=999, llm_fn=lambda p: "x")
    assert loop.tick_once() is None
