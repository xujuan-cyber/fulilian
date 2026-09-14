"""run_script（计划书 P1.1）回归测试。

设计动机（§1.2 的测量）：模型只做到 1.12 次工具调用/轮，PARALLEL_TOOL_CALL_GUIDANCE
的劝说没有生效 —— 得靠工具形态压往返，不能靠劝说。

本测试锁：
  (a) 工具注册在 ctf_solve 工具集（toolsets 耦合锁反向依赖这条）；
  (b) 复用 terminal_tool 而不是自己起子进程 —— 沙箱/cwd/危险命令拦截
      必须与模型直调 terminal 同一条路径（批量化不等于绕过防线）；
  (c) stop_on_error 语义（默认遇错即停）；
  (d) 单命令输出截断 + 总预算超限丢最老（后面的命令通常更接近答案）；
  (e) 上限 12 条。

实现注记：_run_script_impl 在函数体内 ``from tools.terminal_tool import
terminal_tool``，所以 patch ``tools.terminal_tool.terminal_tool`` 属性即可。
"""

from __future__ import annotations

import json

import pytest

import tools.ctf_solve as ctf_solve  # noqa: F401 — import 触发注册
from tools.registry import registry
from tools.terminal_tool import terminal_tool as _real_terminal_tool


def _fake_terminal(monkeypatch, script):
    """按 (command) -> (exit_code, output) 表替换 terminal_tool。

    返回记录调用参数的列表，供断言顺序与透传（workdir/timeout）。
    """

    calls = []

    def fake(command, **kwargs):
        calls.append({"command": command, **kwargs})
        code, out = script(command)
        return json.dumps({"output": out, "exit_code": code, "error": "",
                           "status": "done"})

    monkeypatch.setattr("tools.terminal_tool.terminal_tool", fake)
    return calls


def test_registered_in_ctf_solve_toolset():
    entry = registry.get_entry("run_script")
    assert entry is not None
    assert entry.toolset == "ctf_solve"


def test_reuses_terminal_tool_not_own_subprocess(monkeypatch):
    """批量化必须走 terminal_tool 同一条路径（沙箱/拦截不因批量而绕过）。"""

    seen = {"terminal": False}

    def fake(command, **kwargs):
        seen["terminal"] = True
        assert command == "echo hi"
        return json.dumps({"output": "hi", "exit_code": 0, "error": ""})

    monkeypatch.setattr("tools.terminal_tool.terminal_tool", fake)
    raw = ctf_solve._run_script_impl(["echo hi"])
    assert seen["terminal"]
    data = json.loads(raw)
    assert data["results"][0]["output"] == "hi"


def test_sequential_execution_and_workdir_passthrough(monkeypatch):
    script = {"a": (0, "out-a"), "b": (0, "out-b")}
    calls = _fake_terminal(monkeypatch, lambda c: script[c])
    data = json.loads(ctf_solve._run_script_impl(
        ["a", "b"], workdir="/tmp/wd", timeout=9))
    assert [c["command"] for c in calls] == ["a", "b"]
    assert calls[0]["workdir"] == "/tmp/wd"
    assert calls[0]["timeout"] == 9
    assert data["summary"] == {"ran": 2, "ok": 2, "failed": 0, "stopped_at": None}


def test_stop_on_error_default_stops(monkeypatch):
    calls = _fake_terminal(monkeypatch, lambda c: (1, "boom") if c == "bad"
                           else (0, "ok"))
    data = json.loads(ctf_solve._run_script_impl(["good", "bad", "after"]))
    assert [c["command"] for c in calls] == ["good", "bad"]
    assert data["summary"]["stopped_at"] == 1
    assert data["summary"]["failed"] == 1


def test_stop_on_error_false_continues(monkeypatch):
    calls = _fake_terminal(monkeypatch, lambda c: (1, "boom") if c == "bad"
                           else (0, "ok"))
    data = json.loads(ctf_solve._run_script_impl(
        ["bad", "after"], stop_on_error=False))
    assert [c["command"] for c in calls] == ["bad", "after"]
    assert data["summary"]["stopped_at"] is None
    assert data["summary"]["failed"] == 1


def test_per_command_output_trimmed(monkeypatch):
    big = "x" * 20_000
    _fake_terminal(monkeypatch, lambda c: (0, big))
    data = json.loads(ctf_solve._run_script_impl(["one"]))
    out = data["results"][0]["output"]
    assert len(out) < 10_000
    assert "trimmed" in out


def test_total_budget_drops_oldest(monkeypatch):
    # 默认总预算 30,000 放不下两条 6,000 的触发条件 —— 把预算压到 10,000，
    # 两条 6,000 = 12,000 超限 → 最老的一条被降级为指针。
    monkeypatch.setattr(ctf_solve, "RUN_SCRIPT_TOTAL_BUDGET_CHARS", 10_000)
    _fake_terminal(monkeypatch, lambda c: (0, "y" * 6_000))
    data = json.loads(ctf_solve._run_script_impl(
        ["old", "new"], stop_on_error=False))
    first = data["results"][0]
    assert "dropped" in first and "old" in first["command"]
    assert data["results"][1]["output"] == "y" * 6_000


def test_max_commands_cap():
    raw = ctf_solve._run_script_impl([f"echo {i}"
                                      for i in range(
                                          ctf_solve.RUN_SCRIPT_MAX_COMMANDS + 1)])
    assert "at most" in raw


def test_empty_and_invalid_input():
    assert "requires a non-empty" in ctf_solve._run_script_impl([])
    # 纯空白字符串 → 过滤后无可用命令，走的是 "no usable command" 分支。
    assert "no usable command" in ctf_solve._run_script_impl("   ")
    assert "no usable command" in ctf_solve._run_script_impl(["", "  "])


def test_real_terminal_tool_still_importable():
    """上面所有测试都在 patch terminal_tool —— 这条确认真身没被顶掉。"""
    assert callable(_real_terminal_tool)
