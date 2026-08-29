"""自动 Writeup（F3-010）与追踪回放（F3-014）测试。

覆盖：
- 轨迹构建：solver.log 切步 + 黑板 facts + FLAG 过校验门（F3-014 验收：
  命令 + 输出 + flag 验证结果完整记录）
- 回放输出与 JSON 模式
- Writeup 包含题目描述/解题思路/关键命令/flag/验证结果/耗时（F3-010 验收）
- 历史轨迹（TRACES_DIR 格式）兼容
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    save_blackboard,
)
from fulilian_ctf.dispatcher import Project
from fulilian_ctf.trace import (
    TRACE_FILENAME,
    Trace,
    build_trace,
    get_or_build_trace,
    load_trace,
    replay_trace,
)
from fulilian_ctf.writeup import (
    extract_key_commands,
    generate_writeup,
    save_writeup,
    writeup_to_format,
)


@pytest.fixture()
def solved_work_dir(tmp_path):
    """一个已解出题的工作目录：solver.log + 黑板 + FLAG。"""
    d = tmp_path / "web-777"
    d.mkdir()
    (d / "solver.log").write_text(
        "[1] $ nmap -sV 10.10.10.5\n"
        "PORT   STATE SERVICE\n"
        "80/tcp open  http\n"
        "\n"
        "[2] $ curl http://10.10.10.5/admin\n"
        "<html>login form</html>\n"
        "\n"
        "[3] $ sqlmap -u http://10.10.10.5/admin --dump\n"
        "found flag{race_condition_99} in users table\n",
        encoding="utf-8",
    )
    board = Blackboard(challenge_id="web-777")
    board.add_fact(Fact(content="port 80 open (nginx)", source="nmap"))
    board.add_fact(Fact(content="found flag{race_condition_99} in users table", source="sqlmap"))
    board.mark_dead_end("brute-force login")
    save_blackboard(board, d / BLACKBOARD_FILENAME)
    (d / "FLAG").write_text("flag{race_condition_99}\n", encoding="utf-8")
    return d


# ── F3-014 追踪回放 ───────────────────────────────────────────────────────

def test_build_trace_records_steps_facts_flag(solved_work_dir):
    trace = build_trace(solved_work_dir)

    assert trace.challenge_id == "web-777"
    # 命令 + 输出都有记录
    kinds = [s.kind for s in trace.steps]
    assert "command" in kinds
    assert any(s.kind == "output" for s in trace.steps)
    # 命令步骤可还原命令行
    commands = " ".join(s.text for s in trace.steps if s.kind == "command")
    assert "nmap" in commands
    assert "sqlmap" in commands
    # 输出步骤可还原 flag 所在输出
    outputs = " ".join(s.text for s in trace.steps if s.kind == "output")
    assert "flag{race_condition_99}" in outputs
    # 黑板 facts 与死路
    assert "port 80 open (nginx)" in trace.facts
    assert "brute-force login" in trace.dead_ends
    # flag 验证结果记录
    assert trace.flag == "flag{race_condition_99}"
    assert trace.flag_verified == "confirmed"
    # 持久化
    assert (solved_work_dir / TRACE_FILENAME).is_file()


def test_trace_roundtrip(solved_work_dir):
    trace = build_trace(solved_work_dir)
    loaded = load_trace(solved_work_dir / TRACE_FILENAME)
    assert loaded.to_dict() == trace.to_dict()


def test_replay_text_contains_verification(solved_work_dir):
    trace = build_trace(solved_work_dir)
    text = replay_trace(trace)
    assert "web-777" in text
    assert "flag{race_condition_99}" in text
    assert "confirmed" in text
    assert "$" in text  # 命令步前缀
    assert "[1]" in text  # 步号


def test_replay_start_step_and_json(solved_work_dir):
    trace = build_trace(solved_work_dir)
    partial = replay_trace(trace, start_step=2)
    assert "[1]" not in partial
    assert "[2]" in partial

    payload = json.loads(replay_trace(trace, start_step=2, as_json=True))
    assert payload["flag"] == "flag{race_condition_99}"
    assert all(s["index"] >= 2 for s in payload["steps"])


def test_get_or_build_trace_reuses_existing(solved_work_dir):
    t1 = build_trace(solved_work_dir)
    # 手动污染 trace.json：get_or_build 应读缓存而不是重建
    data = json.loads((solved_work_dir / TRACE_FILENAME).read_text())
    data["model"] = "cached-model"
    (solved_work_dir / TRACE_FILENAME).write_text(json.dumps(data))
    t2 = get_or_build_trace(solved_work_dir)
    assert t2.model == "cached-model"
    del t1


def test_build_trace_empty_dir(tmp_path):
    trace = build_trace(tmp_path)
    assert trace.flag == ""
    assert trace.steps == []
    assert trace.flag_verified == ""


# ── F3-010 自动 Writeup ───────────────────────────────────────────────────

def test_generate_writeup_contains_required_sections(solved_work_dir):
    project = Project(
        challenge_id="web-777",
        title="Baby SQLi",
        category="web",
        difficulty="easy",
        description="Find the hidden admin panel and dump users.",
    )
    md = generate_writeup("web-777", solved_work_dir, project=project)

    assert "# Writeup: Baby SQLi" in md
    assert "Find the hidden admin panel and dump users." in md
    assert "## 解题思路" in md
    assert "port 80 open (nginx)" in md          # 黑板事实成为思路
    assert "## 关键命令" in md
    assert "nmap -sV 10.10.10.5" in md           # 关键命令
    assert "flag{race_condition_99}" in md       # flag
    assert "confirmed" in md                     # 验证结果
    assert "brute-force login" in md             # 死路


def test_extract_key_commands_dedup(solved_work_dir):
    trace = build_trace(solved_work_dir)
    cmds = extract_key_commands(trace)
    assert len(cmds) == len(set(cmds))
    assert any("nmap" in c for c in cmds)


def test_writeup_polish_fn_injected(solved_work_dir):
    md = generate_writeup(
        "web-777", solved_work_dir, polish_fn=lambda text: "POLISHED\n" + text
    )
    assert md.startswith("POLISHED")


def test_writeup_polish_fn_failure_falls_back(solved_work_dir):
    def boom(text):
        raise RuntimeError("llm down")

    md = generate_writeup("web-777", solved_work_dir, polish_fn=boom)
    assert "# Writeup:" in md  # 回退模板


def test_writeup_to_format_html_and_json(solved_work_dir):
    md = generate_writeup("web-777", solved_work_dir)
    html = writeup_to_format(md, "html")
    assert html.startswith("<!doctype html>")
    assert "<h1>" in html

    payload = json.loads(writeup_to_format(md, "json"))
    assert payload["writeup"] == md


def test_save_writeup_extension(solved_work_dir, tmp_path):
    md = generate_writeup("web-777", solved_work_dir)
    out = save_writeup(md, "markdown", tmp_path / "out" / "writeup")
    assert out.suffix == ".md"
    assert out.read_text() == md


def test_writeup_unsolved(tmp_path):
    d = tmp_path / "misc-1"
    d.mkdir()
    (d / "solver.log").write_text("ran out of ideas\n", encoding="utf-8")
    md = generate_writeup("misc-1", d)
    assert "（未解出）" in md
