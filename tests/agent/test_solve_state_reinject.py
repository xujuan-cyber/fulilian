"""P0.2 solve-state 账本（压缩边界确定性抽取 + 重注入）回归测试。

病（计划书 §3.B）：压缩摘要是意译，summarizer 会把「跑过什么命令、结果
如何」逐字丢掉；模型靠提示词纪律记录经常不遵守 → 压缩后重跑 robots.txt×3
这类已做过的推导。

修法：runtime 在压缩边界上从**被压缩的 turns** 确定性抽取事实（terminal
命令+退出码 / run_script 批量 summary / write_file 路径），作为 Solve State
块追加进 summary —— 与 ``_reinject_pruned_skill_markers`` 同一条确定性重
注入先例，不需要每轮 hook（被压缩的 turns 本身就是完整抽取源）。

本测试锁：
  (a) env 关 → summary 原样（默认行为零变化，效果未 A/B 前不给默认）；
  (b) env 开 + terminal 调用 → 命令 + exit_code + 首行进账本；
  (c) 同一命令重复 → 记 ×N 而不是丢（重复本身就是 §3.B 要暴露的信号）；
  (d) 超上限保最新；
  (e) write_file / run_script 各自的抽取形态；
  (f) 无工具调用 → 不追加空块；
  (g) 接线锁：两个 summary 生产点都必须调用重注入 —— 测试绿 ≠ 接上了线
      （镜像日志的教训），按函数体断言两处不许再裸奔。
"""

from __future__ import annotations

import json

import pytest

import agent.context_compressor as cc


def _terminal_call(cid, command):
    return {"id": cid, "type": "function", "function": {
        "name": "terminal",
        "arguments": json.dumps({"command": command}),
    }}


def _tool_result(cid, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return {"role": "tool", "tool_call_id": cid, "content": content}


def _turns_terminal(*specs):
    """specs: [(cid, command, result_payload|str)] → OpenAI wire 消息列表。"""
    msgs = []
    for cid, cmd, payload in specs:
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [_terminal_call(cid, cmd)]})
        msgs.append(_tool_result(cid, payload))
    return msgs


@pytest.fixture()
def env_on(monkeypatch):
    monkeypatch.setenv(cc.SOLVE_STATE_ENV, "1")


def test_env_off_summary_untouched(monkeypatch):
    monkeypatch.delenv(cc.SOLVE_STATE_ENV, raising=False)
    turns = _turns_terminal(("c1", "grep -r robots.txt /var/www",
                             {"output": "found", "exit_code": 0}))
    summary = "original summary"
    assert cc._reinject_solve_state_section(summary, turns) == summary


def test_terminal_command_exit_and_first_line(env_on):
    turns = _turns_terminal(
        ("c1", "grep -ri robots.txt /var/www",
         {"output": "3 matches\nmore lines", "exit_code": 0}))
    out = cc._reinject_solve_state_section("S", turns)
    assert cc._SOLVE_STATE_HEADING in out
    assert "grep -ri robots.txt /var/www" in out
    assert "exit=0" in out and "3 matches" in out
    assert "Do NOT re-run" in out


def test_duplicate_command_counted_not_dropped(env_on):
    turns = _turns_terminal(
        ("c1", "cat robots.txt", {"output": "a", "exit_code": 0}),
        ("c2", "cat robots.txt", {"output": "a", "exit_code": 0}),
        ("c3", "cat robots.txt", {"output": "a", "exit_code": 0}),
    )
    entries = cc._extract_solve_state_entries(turns)
    assert entries == ["cat robots.txt → exit=0 | a ×3"]


def test_nonzero_exit_visible(env_on):
    turns = _turns_terminal(("c1", "nmap -sV host",
                             {"output": "", "exit_code": 1, "error": "denied"}))
    entries = cc._extract_solve_state_entries(turns)
    assert "exit=1" in entries[0] and "denied" in entries[0]


def test_cap_keeps_newest(env_on):
    specs = [(f"c{i}", f"cmd-{i:03d}", {"output": f"o{i}", "exit_code": 0})
             for i in range(cc._SOLVE_STATE_MAX_ENTRIES + 10)]
    entries = cc._extract_solve_state_entries(_turns_terminal(*specs))
    assert len(entries) == cc._SOLVE_STATE_MAX_ENTRIES
    assert "cmd-000" not in entries[0]  # 最老的被挤掉
    assert f"cmd-{cc._SOLVE_STATE_MAX_ENTRIES + 9:03d}" in entries[-1]


def test_write_file_entry(env_on):
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "w1", "type": "function", "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "/tmp/exp.py",
                                         "content": "print(1)"})}}]},
        _tool_result("w1", "written"),
    ]
    entries = cc._extract_solve_state_entries(msgs)
    assert entries == ["write_file: /tmp/exp.py → ok"]


def test_run_script_summary_entry(env_on):
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "type": "function", "function": {
                "name": "run_script",
                "arguments": json.dumps({"commands": ["id", "uname -a"]})}}]},
        _tool_result("r1", {"summary": {"ran": 2, "ok": 2, "failed": 0,
                                        "stopped_at": None}}),
    ]
    entries = cc._extract_solve_state_entries(msgs)
    assert entries == ["id; uname -a → ran=2 ok=2 failed=0 stopped_at=None"]


def test_no_tool_calls_no_block(env_on):
    turns = [{"role": "user", "content": "solve it"},
             {"role": "assistant", "content": "thinking..."}]
    assert cc._reinject_solve_state_section("S", turns) == "S"


def test_non_json_result_first_line(env_on):
    turns = _turns_terminal(("c1", "search_files pattern=flag", "5 files matched"))
    entries = cc._extract_solve_state_entries(turns)
    assert entries[0].startswith("search_files pattern=flag → 5 files matched")


def test_wiring_both_summary_sites():
    """接线锁：fallback 与 LLM 两条 summary 生产路径都必须调用重注入。"""
    import inspect
    fallback_src = inspect.getsource(cc.ContextCompressor._build_static_fallback_summary)
    llm_src = inspect.getsource(cc.ContextCompressor._generate_summary)
    assert "_reinject_solve_state_section" in fallback_src
    assert "_reinject_solve_state_section" in llm_src
