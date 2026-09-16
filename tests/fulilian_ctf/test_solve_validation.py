"""``fulilian solve`` 目标前置校验测试（handle_solve_command 的 exit 2 快速失败）。

校验规则见 ``fulilian_ctf.cli._validate_solve_target``：与 ``_resolve_project`` /
``_resolve_writeup_inputs`` 的解析顺序一致，无效目标在启动 agent 前秒级拒绝
（exit 2，stderr 报错），绝不触发真实 LLM 调用（run_agent 全程用 stub 替换）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path

import pytest

from fulilian_ctf import cli
from fulilian_ctf.sandbox import ENV_SANDBOX_MODE


def _ns(**kw) -> argparse.Namespace:
    base = dict(id="test-chal", model="test/model", race=False, multi_agent=False,
                oneshot=False, json=False)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture()
def stub_run_agent(monkeypatch, tmp_path):
    """sys.modules["run_agent"] 替身：只记录调用，绝不触发真实 LLM/API。

    返回 calls 列表；每次调用记录 query/mode/model 与调用时的 cwd。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_SANDBOX_MODE, raising=False)
    monkeypatch.setattr("fulilian_ctf.solver.resolve_default_model", lambda: "cfg/model")
    # hook 注册走独立测试（test_hooks_scripts.py），这里隔离 plugin manager 开销
    monkeypatch.setattr("fulilian_ctf.hooks.register_ctf_tool_hooks", lambda: [])

    calls: list = []

    def _main(query=None, mode="", model="", **kw):  # noqa: A002
        calls.append({"query": query, "mode": mode, "model": model,
                      "cwd": os.getcwd()})
        (Path.cwd() / "FLAG").write_text("flag{stub}", encoding="utf-8")
        return 0

    stub = types.ModuleType("run_agent")
    stub.main = _main
    monkeypatch.setitem(sys.modules, "run_agent", stub)
    return calls


# ── 无效目标：秒级 exit 2，绝不起 agent ─────────────────────────────────────


def test_missing_absolute_path_exits_2_without_agent(stub_run_agent, tmp_path, capsys):
    """核心 bug 场景：不存在的绝对路径必须秒级 exit 2，不建目录、不调 agent。"""
    target = tmp_path / "definitely-not-exist"
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(target)))
    assert exc.value.code == 2
    assert stub_run_agent == []  # agent 从未启动
    assert not target.exists()  # 也没有偷偷 mkdir

    err = capsys.readouterr().err
    assert str(target) in err  # 指出检查过的路径
    assert "does not exist" in err
    assert "ctfd sync" in err  # usage 提示：先同步平台挑战


def test_missing_relative_path_exits_2(stub_run_agent, tmp_path, capsys):
    """带分隔符的相对路径不存在 → 同样拒绝（否则会在 cwd 下 mkdir 空目录）。"""
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id="chals/missing-chal"))
    assert exc.value.code == 2
    assert stub_run_agent == []
    assert not (tmp_path / "chals").exists()
    assert "chals/missing-chal" in capsys.readouterr().err


def test_existing_non_manifest_file_rejected(stub_run_agent, tmp_path, capsys):
    """存在的普通文件（非清单）不是合法挑战目标。"""
    notes = tmp_path / "notes.txt"
    notes.write_text("not a challenge", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(notes)))
    assert exc.value.code == 2
    assert stub_run_agent == []
    assert "not a usable challenge" in capsys.readouterr().err


def test_corrupt_challenge_json_rejected(stub_run_agent, tmp_path):
    """目录里有损坏的 challenge.json → 无法解析，拒绝而不是带着 agent 裸奔。"""
    d = tmp_path / "broken-chal"
    d.mkdir()
    (d / "challenge.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(d)))
    assert exc.value.code == 2
    assert stub_run_agent == []


def test_blank_id_rejected_with_id_message(stub_run_agent, capsys):
    """空白 id 与路径类错误使用不同的提示文案（需求：两类错误信息区分）。"""
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=""))
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "cannot resolve challenge id" in err
    assert "does not exist" not in err  # 与「路径不存在」文案区分开


def test_race_branch_validated_before_dispatch(monkeypatch, stub_run_agent, tmp_path):
    """--race 分支也在校验之后：无效目标必须先被拦截，_run_race 不得执行。"""

    def _boom(args):
        raise AssertionError("_run_race must not run for an invalid target")

    monkeypatch.setattr(cli, "_run_race", _boom)
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(tmp_path / "nope"), race=True))
    assert exc.value.code == 2
    assert stub_run_agent == []


def test_multi_agent_branch_validated_before_dispatch(monkeypatch, stub_run_agent, tmp_path):
    """--multi-agent 分支同理：校验在分流之前统一生效。"""

    def _boom(args):
        raise AssertionError("_run_multi_agent must not run for an invalid target")

    monkeypatch.setattr(cli, "_run_multi_agent", _boom)
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(tmp_path / "nope"), multi_agent=True))
    assert exc.value.code == 2
    assert stub_run_agent == []


# ── 合法目标：原样放行（校验返回本会使用的 work_dir）────────────────────────


def test_existing_plain_directory_passes(stub_run_agent, tmp_path):
    """存在的真实目录 → 放行，agent 在该目录内运行（work_dir = 目录本身）。"""
    d = tmp_path / "chal-a"
    d.mkdir()
    assert Path(cli._validate_solve_target(str(d))) == d
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(d)))
    assert exc.value.code == 0
    assert len(stub_run_agent) == 1
    assert Path(stub_run_agent[0]["cwd"]) == d  # 确实在题目目录里求解


def test_existing_directory_with_challenge_json_passes(stub_run_agent, tmp_path):
    """含 challenge.json 的目录 → 放行；校验返回的 work_dir 必须与实际求解目录一致。"""
    d = tmp_path / "platform" / "chal-b"
    d.mkdir(parents=True)
    (d / "challenge.json").write_text(
        json.dumps({"id": "chal-b", "title": "B"}), encoding="utf-8"
    )
    work_dir = cli._validate_solve_target(str(d))
    assert work_dir is not None
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(d)))
    assert exc.value.code == 0
    assert len(stub_run_agent) == 1
    # 校验结果与真实管线（_resolve_project → _prepare_work_dir）实际使用的目录一致
    assert Path(work_dir) == Path(stub_run_agent[0]["cwd"])


def test_manifest_file_passes_and_uses_entry_dir(stub_run_agent, tmp_path):
    """平台清单文件 → 放行，按条目 dir 解析 work_dir（CTFd sync 产物的单题用法）。"""
    (tmp_path / "web-01").mkdir()
    manifest = tmp_path / "platform.json"
    manifest.write_text(
        json.dumps({"challenges": [{"id": "web-01", "dir": "web-01"}]}),
        encoding="utf-8",
    )
    work_dir = cli._validate_solve_target(str(manifest))
    assert Path(work_dir) == tmp_path / "web-01"
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id=str(manifest)))
    assert exc.value.code == 0
    assert Path(stub_run_agent[0]["cwd"]) == tmp_path / "web-01"


def test_bare_relative_id_passes_and_creates_work_dir(stub_run_agent, tmp_path):
    """裸相对 id（web-01 形态）→ 放行：既有机制在 cwd 下建同名工作目录。

    这是 test_solve_modes.test_default_mode_and_work_dir_agents_md 固化的行为，
    校验不得误杀；同时验证校验本身无副作用（不提前 mkdir）。
    """
    prospective = tmp_path / "chal-01"
    work_dir = cli._validate_solve_target("chal-01")
    assert Path(work_dir) == prospective
    assert not prospective.exists()  # 校验是纯只读检查
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id="chal-01"))
    assert exc.value.code == 0
    assert (prospective / "AGENTS.md").is_file()  # 照常生成 AGENTS.md
    assert Path(stub_run_agent[0]["cwd"]) == prospective


def test_bare_id_with_historical_trace_passes(stub_run_agent, tmp_path, monkeypatch):
    """历史会话 id（FULILIAN_HOME/traces/<id>.json）→ 与 writeup/replay 同源放行。"""
    home = tmp_path / "fulilian-home"
    traces = home / "traces"
    traces.mkdir(parents=True)
    (traces / "chal-01.json").write_text(
        json.dumps({"challenge_id": "chal-01", "key_commands": []}),
        encoding="utf-8",
    )
    # _load_historical_trace 在调用时经 fulilian_constants.get_fulilian_home() 解析（C0-1）
    import fulilian_constants

    monkeypatch.setattr(fulilian_constants, "get_fulilian_home", lambda: home)

    work_dir = cli._validate_solve_target("chal-01")
    assert work_dir is not None
    with pytest.raises(SystemExit) as exc:
        cli.handle_solve_command(_ns(id="chal-01"))
    assert exc.value.code == 0
    assert len(stub_run_agent) == 1


# ── 路径启发式 ───────────────────────────────────────────────────────────────


def test_looks_like_path_heuristic():
    """路径形态（分隔符 / ./ ~/ 前缀 / 后缀）与裸挑战 id 的区分。"""
    for path_like in ("/tmp/x", "a/b", "./x", "../x", "~/x", "notes.txt", ".."):
        assert cli._looks_like_path(path_like), path_like
    for bare_id in ("web-01", "chal_02", "Crypto100", "misc"):
        assert not cli._looks_like_path(bare_id), bare_id
