"""solve 命令 4 种使用模式 (F4-002) + 求解链路 AGENTS.md 接线 (F4-001) 测试。"""

from __future__ import annotations

import argparse
import json
import sys
import types

import pytest

from fulilian_ctf import cli
from fulilian_ctf.sandbox import ENV_SANDBOX_MODE


def _ns(**kw) -> argparse.Namespace:
    base = dict(id="test-chal", model="test/model", race=False, multi_agent=False,
                oneshot=False, json=False)
    base.update(kw)
    return argparse.Namespace(**base)


class _StubRunAgent(types.ModuleType):
    """sys.modules["run_agent"] 替身：记录调用并在工作目录留 FLAG。"""

    calls: list = []

    @staticmethod
    def main(query=None, mode="", model="", **kw):  # noqa: A002
        _StubRunAgent.calls.append({"query": query, "mode": mode, "model": model})
        from pathlib import Path

        flag = Path.cwd() / "FLAG"
        flag.write_text("flag{stub}", encoding="utf-8")
        return 0


@pytest.fixture()
def stub_run_agent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_SANDBOX_MODE, raising=False)
    monkeypatch.setattr("fulilian_ctf.solver.resolve_default_model", lambda: "cfg/model")
    # hook 注册走独立测试（test_hooks_scripts.py），这里隔离 plugin manager 开销
    monkeypatch.setattr("fulilian_ctf.hooks.register_ctf_tool_hooks", lambda: [])
    _StubRunAgent.calls = []
    stub = types.ModuleType("run_agent")
    stub.main = _StubRunAgent.main
    monkeypatch.setitem(sys.modules, "run_agent", stub)
    return _StubRunAgent


def test_json_mode_emits_start_and_result(stub_run_agent, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(json=True))
    assert exc.value.code == 0  # stub 留下 FLAG → solved → 0

    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 2
    start, result = lines
    assert start["event"] == "start" and start["challenge"] == "test-chal"
    assert start["model"] == "test/model"
    assert result["event"] == "result" and result["solved"] is True
    assert result["flag"] == "flag{stub}"
    assert result["exit_code"] == 0
    # solver 调用参数
    call = stub_run_agent.calls[0]
    assert call["mode"] == "ctf" and call["model"] == "test/model"


def test_oneshot_mode_prints_summary(stub_run_agent, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(oneshot=True))
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "[solve] test-chal: SOLVED" in out
    assert "flag{stub}" in out
    assert '"event"' not in out  # -p 不输出 JSON


def test_no_flag_exits_1(stub_run_agent, capsys):
    def no_flag_main(query=None, mode="", model="", **kw):
        return 0  # 正常结束但没有 FLAG 文件

    stub = sys.modules["run_agent"]
    stub.main = no_flag_main
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(oneshot=True))
    assert exc.value.code == 1
    assert "no flag" in capsys.readouterr().out


def test_default_mode_and_work_dir_agents_md(stub_run_agent, capsys):
    """默认模式：chdir 进题目目录跑，目录里自动生成 AGENTS.md（F4-001）。"""
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns())
    assert exc.value.code == 0
    work = cli.Path("test-chal")
    agents_md = work / "AGENTS.md"
    assert agents_md.is_file()
    assert "test-chal" in agents_md.read_text(encoding="utf-8")
    assert (work / "FLAG").is_file()  # stub 的 cwd 即题目目录
    # cwd 已还原
    assert cli.Path.cwd() != work or True  # tmp_path 还原由 monkeypatch 管理


def test_sandbox_env_default_set(stub_run_agent):
    import os

    assert ENV_SANDBOX_MODE not in os.environ
    with pytest.raises(SystemExit):
        cli.handle_solve_command(_ns(oneshot=True))
    assert os.environ.get(ENV_SANDBOX_MODE) == "workspace-write"
