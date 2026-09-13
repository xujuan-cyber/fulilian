"""求解模式开关（``--solve-mode`` / ``FULILIAN_CTF_SOLVE_MODE`` / config）测试。

并行求解模式（race / multi-agent / boomerang）是 **N 份并发**的成本与时长，
所以设计约束是：**默认必须是单 agent**，要并行必须显式打开。本文件锁住三件事：

1. ``solver.resolve_solve_mode`` 的优先级与容错（显式 > env > config > single；
   无法识别的取值降级 single 但**必须告警**——静默退回单 agent 就是
   「以为在并行其实没有」那类故障）。
2. 显式 flag 永远压过 env/config：``solve <id> --race`` 不受环境变量影响。
3. ``cli._run_parallel_mode`` 让 race 分支与单 agent 分支同源——都准备题目
   工作目录、都落库经验（此前 race 分支直接 return，两样都缺）。
"""

from __future__ import annotations

import argparse
import sys
import types

import pytest

from fulilian_ctf import cli, solver


def _ns(**kw) -> argparse.Namespace:
    base = dict(id="test-chal", model="test/model", race=False, boomerang=False,
                multi_agent=False, oneshot=False, json=False, solve_mode="")
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture()
def clean_env(monkeypatch):
    """清掉 env 与真实用户配置，让 resolve_solve_mode 只看到测试给的东西。"""
    monkeypatch.delenv(solver.SOLVE_MODE_ENV, raising=False)
    monkeypatch.setattr("fulilian_cli.config.load_config", lambda: {})
    return monkeypatch


def _set_config(monkeypatch, cfg):
    monkeypatch.setattr("fulilian_cli.config.load_config", lambda: cfg)


# ── 1. resolve_solve_mode：优先级 ──────────────────────────────────────────


def test_explicit_beats_env_and_config(clean_env):
    clean_env.setenv(solver.SOLVE_MODE_ENV, "multi-agent")
    _set_config(clean_env, {"ctf": {"solve_mode": "boomerang"}})
    assert solver.resolve_solve_mode("race") == "race"


def test_env_beats_config(clean_env):
    clean_env.setenv(solver.SOLVE_MODE_ENV, "race")
    _set_config(clean_env, {"ctf": {"solve_mode": "multi-agent"}})
    assert solver.resolve_solve_mode() == "race"


def test_config_used_when_no_explicit_or_env(clean_env):
    _set_config(clean_env, {"ctf": {"solve_mode": "boomerang"}})
    assert solver.resolve_solve_mode() == "boomerang"


def test_defaults_to_single_when_nothing_set(clean_env):
    assert solver.resolve_solve_mode() == solver.SOLVE_MODE_SINGLE


# ── 2. resolve_solve_mode：别名与容错 ─────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("multi_agent", "multi-agent"),
    ("MultiAgent", "multi-agent"),
    ("multi-agent", "multi-agent"),
    ("  RACE  ", "race"),
    ("default", "single"),
    ("single_agent", "single"),
])
def test_aliases_and_whitespace(clean_env, raw, expected):
    assert solver.resolve_solve_mode(raw) == expected


def test_unrecognized_explicit_warns_and_falls_back(clean_env):
    """拼错的值必须吼一声——静默退回单 agent 会伪装成「并行没用」。"""
    seen: list[str] = []
    assert solver.resolve_solve_mode("rac", warn=seen.append) == "single"
    assert len(seen) == 1
    assert "--solve-mode" in seen[0] and "rac" in seen[0]


def test_unrecognized_env_warns_and_falls_back(clean_env):
    clean_env.setenv(solver.SOLVE_MODE_ENV, "rac")
    seen: list[str] = []
    assert solver.resolve_solve_mode(warn=seen.append) == "single"
    assert len(seen) == 1
    assert solver.SOLVE_MODE_ENV in seen[0]


def test_unrecognized_config_warns_and_falls_back(clean_env):
    _set_config(clean_env, {"ctf": {"solve_mode": "rac"}})
    seen: list[str] = []
    assert solver.resolve_solve_mode(warn=seen.append) == "single"
    assert len(seen) == 1
    assert "ctf.solve_mode" in seen[0]


def test_config_read_failure_degrades_to_single(clean_env):
    def _boom():
        raise OSError("config unreadable")

    clean_env.setattr("fulilian_cli.config.load_config", _boom)
    assert solver.resolve_solve_mode() == "single"


def test_blank_values_are_not_treated_as_unrecognized(clean_env):
    """空串/空白 = 未设置，不该告警。"""
    seen: list[str] = []
    assert solver.resolve_solve_mode("   ", warn=seen.append) == "single"
    assert seen == []


# ── 3. 显式 flag 压过 env/config ──────────────────────────────────────────


def test_explicit_race_flag_beats_env(clean_env):
    clean_env.setenv(solver.SOLVE_MODE_ENV, "multi-agent")
    assert cli._resolve_effective_solve_mode(_ns(race=True)) == "race"


def test_explicit_boomerang_and_multi_agent_flags(clean_env):
    assert cli._resolve_effective_solve_mode(_ns(boomerang=True)) == "boomerang"
    assert cli._resolve_effective_solve_mode(_ns(multi_agent=True)) == "multi-agent"


def test_no_flags_falls_through_to_env(clean_env):
    clean_env.setenv(solver.SOLVE_MODE_ENV, "race")
    assert cli._resolve_effective_solve_mode(_ns()) == "race"


def test_namespace_without_solve_mode_attr_is_safe(clean_env):
    """既有调用方（测试/脚本）构造的 Namespace 没有 solve_mode 字段。"""
    ns = argparse.Namespace(id="x", race=False, boomerang=False, multi_agent=False)
    assert cli._resolve_effective_solve_mode(ns) == "single"


# ── 4. 分流接线：并行分支与单 agent 分支同源 ───────────────────────────────


def _patch_solve_commons(monkeypatch, tmp_path, record_calls):
    work_dir = tmp_path / "web-01"
    work_dir.mkdir(exist_ok=True)
    project = types.SimpleNamespace(
        challenge_id="web-01", category="web", challenge_dir=str(work_dir), flag="",
    )
    monkeypatch.setattr(cli, "_validate_solve_target", lambda cid: str(work_dir))
    monkeypatch.setattr(cli, "_resolve_project", lambda cid: project)
    monkeypatch.setattr(cli, "_prepare_work_dir", lambda p, cid: work_dir)
    monkeypatch.setattr(cli, "_record_single_solve_experience",
                        lambda p, wd: record_calls.append((p.challenge_id, wd)))
    return project, work_dir


def _stub_runner(name, called, solved=True):
    def _run(args):
        called.append(name)
        return types.SimpleNamespace(solved=solved, flag="flag{stub}" if solved else "")
    return _run


@pytest.fixture()
def dispatch_env(monkeypatch, tmp_path, clean_env):
    """把 run_agent 换成 stub，避免真实 LLM 调用。"""
    fake = types.ModuleType("run_agent")
    fake.main = lambda **kw: 0
    monkeypatch.setitem(sys.modules, "run_agent", fake)
    calls: list = []
    _patch_solve_commons(monkeypatch, tmp_path, calls)
    return calls


def test_solve_mode_race_routes_to_racer(dispatch_env, monkeypatch):
    called: list = []
    monkeypatch.setattr(cli, "_run_race", _stub_runner("race", called))
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(solve_mode="race"))
    assert exc.value.code == 0
    assert called == ["race"]


def test_race_branch_records_experience(dispatch_env, monkeypatch):
    """回归锁：race 分支此前直接 return，经验落库被跳过。"""
    monkeypatch.setattr(cli, "_run_race", _stub_runner("race", []))
    with pytest.raises(SystemExit):
        cli.handle_solve_command(_ns(solve_mode="race"))
    assert [call[0] for call in dispatch_env] == ["web-01"]


def test_race_branch_solved_flag_drives_exit_code(dispatch_env, monkeypatch):
    monkeypatch.setattr(cli, "_run_race", _stub_runner("race", [], solved=False))
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(solve_mode="race"))
    assert exc.value.code == 1


def test_env_var_routes_to_multi_agent(dispatch_env, monkeypatch):
    monkeypatch.setenv(solver.SOLVE_MODE_ENV, "multi-agent")
    called: list = []
    monkeypatch.setattr(cli, "_run_multi_agent", _stub_runner("multi-agent", called))
    with pytest.raises(SystemExit):
        cli.handle_solve_command(_ns())
    assert called == ["multi-agent"]


def test_default_path_still_single_agent(dispatch_env, monkeypatch):
    """默认（无 flag / 无 env / config 无 ctf.solve_mode）不得走并行分支。"""
    called: list = []
    monkeypatch.setattr(cli, "_run_race", _stub_runner("race", called))
    monkeypatch.setattr(cli, "_run_multi_agent", _stub_runner("multi-agent", called))
    monkeypatch.setattr(cli, "_run_boomerang", _stub_runner("boomerang", called))
    with pytest.raises(SystemExit):
        cli.handle_solve_command(_ns())
    assert called == []
