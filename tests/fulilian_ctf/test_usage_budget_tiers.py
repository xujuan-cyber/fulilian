"""止损配置单元测试（2026-09-04 语义翻转后）：默认不限 token / 不限轮数。

覆盖：
- stopper.difficulty_token_budget / DIFFICULTY_TOKEN_BUDGETS 分档表（仅显式启用时参考）
- Stopper 默认 max_tokens=None → 无预算上限；显式传入 → 启用保险丝；partial flag ×2
- stopper.usage_tokens / read_exact_usage（usage.json 读取容错）
- solver.write_usage_record 累计语义（跨尝试）+ 无消耗时不动文件
- solver.resolve_max_turns_from_env：显式 env 才限制；未设/0 → sys.maxsize
- Dispatcher 集成：默认不限 token（usage.json 大值不触发）；显式 max_tokens 启用保险丝；
  注入计数器仍最高优先
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from fulilian_ctf.stopper import (
    DEFAULT_MAX_TOKENS,
    DIFFICULTY_TOKEN_BUDGETS,
    USAGE_FILE,
    Stopper,
    difficulty_token_budget,
    usage_tokens,
)
from fulilian_ctf.solver import (
    SolverResult,
    difficulty_max_turns,
    resolve_max_turns_from_env,
    write_usage_record,
)
from fulilian_ctf.dispatcher import ChallengeStatus, Dispatcher, Project


@pytest.fixture(autouse=True)
def _isolate_learning_paths(tmp_path, monkeypatch):
    """_reap 落库隔离到 tmp_path，避免污染真实经验库。"""
    import fulilian_ctf.experiential_learning as _el

    monkeypatch.setattr(_el, "LEARNING_FILE", tmp_path / "learning.json")
    monkeypatch.setattr(_el, "TRACES_DIR", tmp_path / "traces")


def _project(cid: str, tmp_path: Path, **kw) -> Project:
    work = tmp_path / cid
    work.mkdir(parents=True, exist_ok=True)
    defaults = dict(challenge_id=cid, challenge_dir=str(work), difficulty="easy", score=100)
    defaults.update(kw)
    return Project(**defaults)


class _FakeAgent:
    """模拟 AIAgent 的 session_* 计数器接口。"""

    def __init__(self, inp=1000, out=500, cache_read=200, cache_write=100,
                 calls=3, cost=0.01):
        self.session_input_tokens = inp
        self.session_output_tokens = out
        self.session_cache_read_tokens = cache_read
        self.session_cache_write_tokens = cache_write
        self.session_api_calls = calls
        self.session_estimated_cost_usd = cost


# ── 难度分档表（仅显式启用时参考）────────────────────────────────────────

def test_difficulty_token_budget_tiers_table():
    """分档表保留、数值不变，供显式启用分档的调用方参考。"""
    assert difficulty_token_budget("easy") == 200_000
    assert difficulty_token_budget("medium") == DEFAULT_MAX_TOKENS
    assert difficulty_token_budget("hard") == 1_000_000
    assert difficulty_token_budget("expert") == 1_500_000
    # 未知难度 / 空 / 大小写 → medium 默认
    assert difficulty_token_budget("") == DEFAULT_MAX_TOKENS
    assert difficulty_token_budget("HARD") == 1_000_000
    assert difficulty_token_budget("nope") == DEFAULT_MAX_TOKENS


def test_stopper_default_unlimited():
    """默认 max_tokens=None → 无预算上限（不限 token，仅记账）。"""
    s = Stopper()
    assert s.max_tokens is None
    # 无论消耗多少 token，只要其余维度不命中就继续
    common = dict(rounds_without_new_fact=0, variant_failures=0,
                  is_infra_blocked=False, has_partial_flag=False)
    assert s.check(project_tokens=300_000, **common) is None
    assert s.check(project_tokens=10**9, **common) is None


def test_stopper_explicit_max_tokens_enables_fuse():
    """显式传入 max_tokens（CLI --max-tokens）→ 启用 BUDGET_EXCEEDED 保险丝。"""
    common = dict(rounds_without_new_fact=0, variant_failures=0,
                  is_infra_blocked=False, has_partial_flag=False)
    s = Stopper(max_tokens=500_000)
    assert s.max_tokens == 500_000
    assert s.check(project_tokens=499_999, **common) is None
    assert s.check(project_tokens=500_000, **common) == "BUDGET_EXCEEDED"


def test_stopper_partial_flag_doubles_explicit_budget():
    """临门不弃：显式预算 + 已拿到 flag → ×2；None 预算不受影响。"""
    s = Stopper(max_tokens=500_000)
    assert s.check(750_000, 0, 0, False, True) is None  # 放大后在预算内
    assert s.check(1_000_000, 0, 0, False, True) == "BUDGET_EXCEEDED"
    unlimited = Stopper()  # None → 永不 BUDGET_EXCEEDED
    assert unlimited.check(10**9, 0, 0, False, True) is None


def test_stopper_other_dims_still_active_when_unlimited():
    """不限 token 时其余止损维度照常工作。"""
    s = Stopper()
    assert s.check(10**9, 0, 0, True, False) == "INFRA_BLOCKED"
    assert s.check(0, 7, 0, False, False) == "NO_OUTPUT"
    assert s.check(0, 0, 7, False, False) == "HYPOTHESIS_REPEATED"


def test_difficulty_max_turns_table():
    """max_turns 分档表保留（仅显式启用参考），数值不变。"""
    assert difficulty_max_turns("easy") == 20
    assert difficulty_max_turns("medium") == 30
    assert difficulty_max_turns("hard") == 45
    assert difficulty_max_turns("expert") == 45
    assert difficulty_max_turns("") == 30
    assert difficulty_max_turns("unknown") == 30


def test_resolve_max_turns_env(monkeypatch):
    """--max-turns 经 env 显式设置才限制；未设/0/非法 → sys.maxsize（不限）。"""
    monkeypatch.delenv("FULILIAN_CTF_MAX_TURNS", raising=False)
    assert resolve_max_turns_from_env() == sys.maxsize
    monkeypatch.setenv("FULILIAN_CTF_MAX_TURNS", "0")
    assert resolve_max_turns_from_env() == sys.maxsize
    monkeypatch.setenv("FULILIAN_CTF_MAX_TURNS", "notanumber")
    assert resolve_max_turns_from_env() == sys.maxsize
    monkeypatch.setenv("FULILIAN_CTF_MAX_TURNS", "42")
    assert resolve_max_turns_from_env() == 42


# ── usage.json 精确消耗（纯记账，不拦截）─────────────────────────────────

def test_usage_tokens_reads_file(tmp_path):
    (tmp_path / USAGE_FILE).write_text(
        json.dumps({"total_tokens": 12345, "api_calls": 9}), encoding="utf-8"
    )
    assert usage_tokens(tmp_path) == 12345


def test_usage_tokens_missing_or_broken(tmp_path):
    assert usage_tokens(tmp_path) is None  # 缺文件
    (tmp_path / USAGE_FILE).write_text("{not json", encoding="utf-8")
    assert usage_tokens(tmp_path) is None  # 损坏
    (tmp_path / USAGE_FILE).write_text('["list"]', encoding="utf-8")
    assert usage_tokens(tmp_path) is None  # 非 dict


def test_write_usage_record_accumulates(tmp_path):
    write_usage_record(tmp_path, _FakeAgent())
    first = json.loads((tmp_path / USAGE_FILE).read_text(encoding="utf-8"))
    assert first["total_tokens"] == 1000 + 500 + 200 + 100
    assert first["api_calls"] == 3
    assert first["attempts"] == 1
    # 第二次尝试：累计而非覆盖
    write_usage_record(tmp_path, _FakeAgent(), attempt=1)
    second = json.loads((tmp_path / USAGE_FILE).read_text(encoding="utf-8"))
    assert second["total_tokens"] == 2 * (1000 + 500 + 200 + 100)
    assert second["api_calls"] == 6
    assert second["attempts"] == 2


def test_write_usage_record_no_usage_keeps_file(tmp_path):
    """agent 无任何消耗记录（未跑/老版本）→ 不写也不动已有文件。"""
    (tmp_path / USAGE_FILE).write_text(json.dumps({"total_tokens": 42}), encoding="utf-8")
    assert write_usage_record(tmp_path, _FakeAgent(inp=0, out=0, cache_read=0,
                                                   cache_write=0, calls=0, cost=0.0)) is None
    assert json.loads((tmp_path / USAGE_FILE).read_text())["total_tokens"] == 42


def test_write_usage_record_tolerates_missing_counters(tmp_path):
    """计数器属性完全缺失（老版本 run_agent）→ 视为无消耗，不写。"""
    class _Empty:
        pass

    assert write_usage_record(tmp_path, _Empty()) is None
    assert not (tmp_path / USAGE_FILE).exists()


# ── Dispatcher 集成 ──────────────────────────────────────────────────────

def _sleep_solver(project, work_dir, model, queue):
    import time
    time.sleep(60)
    queue.put(SolverResult(ok=True, exit_code=0))


def test_dispatcher_default_unlimited_tokens(tmp_path):
    """默认（无 --max-tokens）：usage.json 大值不触发止损，时间盒兜底。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    (work / USAGE_FILE).write_text(json.dumps({"total_tokens": 5_000_000}), encoding="utf-8")
    d = Dispatcher(max_workers=1, solver_fn=_sleep_solver, quiet=True, timebox_override=2)
    d.add_project(_project("p1", tmp_path))  # easy；旧分档 200K 会立刻止损
    d.run()
    assert d.projects["p1"].status == ChallengeStatus.TIMEOUT


def test_dispatcher_explicit_max_tokens_enables_fuse(tmp_path):
    """显式 max_tokens（CLI --max-tokens）：超限即止损。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    (work / USAGE_FILE).write_text(json.dumps({"total_tokens": 250_000}), encoding="utf-8")
    d = Dispatcher(max_workers=1, solver_fn=_sleep_solver, quiet=True,
                   max_tokens=200_000)
    d.add_project(_project("p1", tmp_path))
    d.run()
    assert d.projects["p1"].status == ChallengeStatus.ABANDONED
    assert d.projects["p1"].stop_reason.startswith("STOPPED: BUDGET_EXCEEDED")


def test_dispatcher_explicit_max_tokens_not_hit(tmp_path):
    """显式 max_tokens 但未超限 → 不止损，时间盒兜底。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    (work / USAGE_FILE).write_text(json.dumps({"total_tokens": 250_000}), encoding="utf-8")
    d = Dispatcher(max_workers=1, solver_fn=_sleep_solver, quiet=True,
                   max_tokens=300_000, timebox_override=2)
    d.add_project(_project("p1", tmp_path))
    d.run()
    assert d.projects["p1"].status == ChallengeStatus.TIMEOUT


def test_dispatcher_injected_counter_still_wins(tmp_path):
    """注入 token_counter 时优先级最高（向后兼容）。"""
    work = tmp_path / "p1"
    work.mkdir(parents=True, exist_ok=True)
    (work / USAGE_FILE).write_text(json.dumps({"total_tokens": 250_000}), encoding="utf-8")
    d = Dispatcher(max_workers=1, solver_fn=_sleep_solver, quiet=True,
                   token_counter=lambda wd: 10, timebox_override=2)
    d.add_project(_project("p1", tmp_path))
    d.run()
    assert d.projects["p1"].status == ChallengeStatus.TIMEOUT
