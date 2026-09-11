"""默认 solve 路径的轨迹日志测试：tee_solver_log + stdout 格式切步。

背景：``fulilian solve`` 默认单 agent 分支此前不落 solver.log，导致
replay 显示 steps=0、writeup 无关键命令。修复链路：

1. ``fulilian_ctf.solver.tee_solver_log`` — stdout/stderr 透传终端的同时
   tee 进 work_dir/solver.log（本文件用 mock 流验证，不跑真实 agent）
2. ``fulilian_ctf.trace._split_log_steps`` — run_agent stdout 含
   📞/✅ 工具进度行、不含 ``$ ``/``[N] `` 命令标记，需能切出
   command/output 步（agent/tool_executor.py 的真实打印格式）
"""

from __future__ import annotations

import io
import sys
import threading
import tempfile
from pathlib import Path

import pytest

from fulilian_ctf.solver import (
    SOLVER_LOG,
    SOLVER_LOG_MIRROR_ENV,
    solver_evidence_stream,
    tee_solver_log,
)
from fulilian_ctf.trace import (
    TRACE_FILENAME,
    build_trace,
    load_trace,
    replay_trace,
)
from fulilian_ctf.writeup import extract_key_commands


class _MemoryStream(io.StringIO):
    """内存流（模拟终端 stdout/stderr；StringIO 自带 write/flush）。"""


# ── tee_solver_log：透传 + 落盘 ───────────────────────────────────────────

def test_tee_captures_stdout_and_stderr(tmp_path, monkeypatch):
    out, err = _MemoryStream(), _MemoryStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    with tee_solver_log(tmp_path):
        print("hello solve")
        print("to stderr", file=sys.stderr)

    # 透传：终端原流仍收到内容（用户可见性不回退）
    assert "hello solve" in out.getvalue()
    assert "to stderr" in err.getvalue()
    # 落盘：solver.log 同时收到两路输出
    log = (tmp_path / SOLVER_LOG).read_text(encoding="utf-8")
    assert "hello solve" in log
    assert "to stderr" in log


def test_tee_returns_log_path_and_truncates_stale_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())
    (tmp_path / SOLVER_LOG).write_text("stale run\n", encoding="utf-8")

    with tee_solver_log(tmp_path) as log_path:
        print("fresh run")

    assert log_path == tmp_path / SOLVER_LOG
    log = log_path.read_text(encoding="utf-8")
    assert "stale run" not in log  # "w" 截断写，与 _run_solve_once 语义一致
    assert "fresh run" in log


def test_tee_flushes_immediately_for_mid_run_readers(tmp_path, monkeypatch):
    """stopper 在求解中途读 solver.log：每次 write 后须即时可见。"""
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())

    with tee_solver_log(tmp_path):
        print("in-flight line")
        assert "in-flight line" in (tmp_path / SOLVER_LOG).read_text(
            encoding="utf-8"
        )


def test_solver_evidence_stream_mirrors_to_outside_path(tmp_path, monkeypatch):
    """solver_evidence_stream：生产路径（_run_solve_once / _default_solver_impl）
    实际用的就是这个 helper，镜像由此生效。"""
    mirror = tmp_path / "outside" / "mirror.log"
    monkeypatch.setenv(SOLVER_LOG_MIRROR_ENV, str(mirror))

    with solver_evidence_stream(tmp_path / "work") as log:
        assert log is not None
        log.write("🔄 Making API call #1/50\n")
        log.flush()

    assert (tmp_path / "work" / SOLVER_LOG).read_text(encoding="utf-8") == \
        mirror.read_text(encoding="utf-8")


def test_solver_evidence_stream_without_mirror_writes_only_workdir(
    tmp_path, monkeypatch
):
    monkeypatch.delenv(SOLVER_LOG_MIRROR_ENV, raising=False)
    with solver_evidence_stream(tmp_path / "work") as log:
        log.write("hello\n")

    assert (tmp_path / "work" / SOLVER_LOG).read_text(encoding="utf-8") == "hello\n"
    assert not (tmp_path / "outside").exists()


def test_solver_evidence_stream_yields_none_when_unwritable(tmp_path, monkeypatch):
    """落盘失败 yield None：调用方退回原流，证据缺失不阻断求解。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    with solver_evidence_stream(blocker / "work") as log:
        assert log is None


def test_mirror_is_wired_into_both_production_entry_points():
    """接线回归锁 —— 这条是本改动第一次做错换来。

    镜像最初只加在 ``tee_solver_log`` 上，而它**没有生产调用点**：默认
    solve 路径走的是 ``cli._run_solve_once`` 与 ``solver._default_solver_impl``。
    结果测试全绿、机制却一次都不会触发。这条锁住那两处不许再裸开日志。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "fulilian_ctf"
    for fname, marker in (("cli.py", "_run_solve_once"),
                          ("solver.py", "_default_solver_impl")):
        src = (root / fname).read_text(encoding="utf-8")
        start = src.index(f"def {marker}")
        end = src.find("\ndef ", start + 1)
        body = src[start:end if end != -1 else len(src)]
        assert "solver_evidence_stream(" in body, (
            f"{fname}:{marker} 没有走 solver_evidence_stream —— "
            f"镜像日志在这条路径上不会生效"
        )
        assert 'open(log_path, "w"' not in body, (
            f"{fname}:{marker} 又出现了裸开 solver.log：镜像会被绕过"
        )


def test_tee_mirror_env_var_gets_same_bytes(tmp_path, monkeypatch):
    """镜像日志（FULILIAN_SOLVER_LOG_MIRROR）：两份内容必须逐字节一致。

    存在的理由：work_dir 是 agent 的地盘，它能用 write_file 把 solver.log
    覆盖掉（实测发生过，见 solver.tee_solver_log 类文档）。镜像给采集器
    留一份 agent 没理由去动的副本。
    """
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())
    work, mirror = tmp_path / "work", tmp_path / "outside" / "mirror.log"
    monkeypatch.setenv(SOLVER_LOG_MIRROR_ENV, str(mirror))

    with tee_solver_log(work):
        print("hello solve")
        print("to stderr", file=sys.stderr)

    assert (work / SOLVER_LOG).read_text(encoding="utf-8") == \
        mirror.read_text(encoding="utf-8")
    assert "hello solve" in mirror.read_text(encoding="utf-8")
    # 镜像的父目录不存在时自建，不要求调用方先 mkdir
    assert mirror.parent.is_dir()


def test_tee_mirror_absent_by_default(tmp_path, monkeypatch):
    """未设环境变量时行为与从前完全一致 —— 不落任何镜像。"""
    monkeypatch.delenv(SOLVER_LOG_MIRROR_ENV, raising=False)
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())

    assert tee_solver_log(tmp_path).mirror_path is None
    with tee_solver_log(tmp_path) as log_path:
        print("hello solve")

    assert log_path == tmp_path / SOLVER_LOG
    assert "hello solve" in log_path.read_text(encoding="utf-8")


def test_tee_mirror_survives_agent_truncating_solver_log(tmp_path, monkeypatch):
    """agent 覆盖 work_dir/solver.log 时，镜像仍保有完整运行日志。

    这是该机制存在的全部理由 —— 用真实形态复现：求解中途一份 write_file
    把 solver.log 截断成一份解题报告。
    """
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())
    work, mirror = tmp_path / "work", tmp_path / "mirror.log"
    monkeypatch.setenv(SOLVER_LOG_MIRROR_ENV, str(mirror))

    with tee_solver_log(work):
        print("🔄 Making API call #1/50")
        print("📞 Tool 1: terminal(grep chan=07 transfer.log) - exit 0")
        # agent 的 write_file：截断 + 写进一份解题报告
        (work / SOLVER_LOG).write_text("# Solution\n\n## Flag\n", encoding="utf-8")
        print("🔄 Making API call #2/50")

    # 主日志：被截断过，早于覆盖点的运行行**永久丢失**（tee 的 fd 停在原
    # 偏移，之后的写入落在 NUL 空洞之后 —— 文件既不完整也不再是合法日志）。
    main = (work / SOLVER_LOG).read_text(encoding="utf-8", errors="replace")
    assert "📞 Tool 1: terminal" not in main
    # 镜像：完整三段都在，且不含 agent 的 writeup
    kept = mirror.read_text(encoding="utf-8")
    assert "🔄 Making API call #1/50" in kept
    assert "📞 Tool 1: terminal" in kept
    assert "🔄 Making API call #2/50" in kept
    assert "# Solution" not in kept


def test_tee_mirror_failure_degrades_without_breaking_main_log(
    tmp_path, monkeypatch
):
    """镜像打不开只降级：主日志照常，求解不受影响。"""
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())
    # 用一个「父路径是文件」的目标，mkdir 必然失败
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setenv(SOLVER_LOG_MIRROR_ENV, str(blocker / "mirror.log"))

    out = _MemoryStream()
    monkeypatch.setattr(sys, "stdout", out)
    with tee_solver_log(tmp_path / "work"):
        print("hello solve")

    assert "hello solve" in out.getvalue()
    assert "hello solve" in (tmp_path / "work" / SOLVER_LOG).read_text(
        encoding="utf-8"
    )


def test_tee_restores_streams_on_success_and_exception(tmp_path, monkeypatch):
    out, err = _MemoryStream(), _MemoryStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    original = (sys.stdout, sys.stderr)

    with tee_solver_log(tmp_path):
        pass
    assert (sys.stdout, sys.stderr) == original

    with pytest.raises(RuntimeError):
        with tee_solver_log(tmp_path / "exception"):
            raise RuntimeError("agent crashed")
    assert (sys.stdout, sys.stderr) == original


def test_tee_restores_streams_after_agent_exception(tmp_path, monkeypatch):
    out, err = _MemoryStream(), _MemoryStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    original = (sys.stdout, sys.stderr)

    try:
        with tee_solver_log(tmp_path):
            print("partial output")
            raise RuntimeError("agent crashed")
    except RuntimeError:
        pass

    assert (sys.stdout, sys.stderr) == original  # 异常安全，不吞异常
    assert "partial output" in (tmp_path / SOLVER_LOG).read_text(
        encoding="utf-8"
    )


def test_tee_open_failure_degrades_to_passthrough(tmp_path, monkeypatch):
    """solver.log 打不开（如只读目录）时静默降级，不阻断求解。"""
    out, err = _MemoryStream(), _MemoryStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    original = (sys.stdout, sys.stderr)
    (tmp_path / SOLVER_LOG).mkdir()  # 目录占位：open("w") 必然 OSError

    with tee_solver_log(tmp_path):
        print("still runs")

    assert "still runs" in out.getvalue()  # 求解照常透传
    assert (sys.stdout, sys.stderr) == original


def test_tee_nested_usage(tmp_path, monkeypatch):
    out, err = _MemoryStream(), _MemoryStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    original = sys.stdout

    with tee_solver_log(tmp_path / "outer") as outer_log:
        print("outer")
        with tee_solver_log(tmp_path / "inner"):
            print("inner")
        print("outer again")

    assert sys.stdout is original
    # Nested tee output is still visible through the outer stream and is
    # therefore recorded by the outer log as well.
    assert "inner" in outer_log.read_text(encoding="utf-8")
    assert "inner" in (tmp_path / "inner" / SOLVER_LOG).read_text(
        encoding="utf-8"
    )
    # 内层退出后外层 tee 仍生效
    assert "outer again" in outer_log.read_text(encoding="utf-8")


def test_tee_thread_safe_writes(tmp_path, monkeypatch):
    """工具 worker 在线程池里打印：并发写入不丢行、不串行化错行。"""
    monkeypatch.setattr(sys, "stdout", _MemoryStream())
    monkeypatch.setattr(sys, "stderr", _MemoryStream())

    lines = [f"line-{i:03d}" for i in range(100)]

    def worker(chunk):
        for text in chunk:
            print(text)

    threads = [
        threading.Thread(target=worker, args=(lines[i::4],)) for i in range(4)
    ]
    with tee_solver_log(tmp_path):
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    log = (tmp_path / SOLVER_LOG).read_text(encoding="utf-8")
    for text in lines:
        assert text in log


# ── stdout 格式 solver.log 的切步（run_agent 真实打印格式） ──────────────

# 按 agent/tool_executor.py 非 verbose 路径的打印格式构造（脱敏）：
#   📞 Tool N: <tool>(<arg-keys>) - <args JSON 预览>
#   ✅ Tool N completed in <s>s - <结果预览>
STDOUT_FORMAT_LOG = (
    "🤖 AI Agent with Tool Calling\n"
    "==================================================\n"
    "\n"
    "📝 User Query: Solve the CTF challenge: mini-chall\n"
    "\n"
    "==================================================\n"
    "  📞 Tool 1: terminal(['command']) -"
    ' {"command": "ls -la /tmp/chall", "task_id": "default"}\n'
    '  ✅ Tool 1 completed in 0.14s - {"output": "total 48\\nREADME.txt", "exit_code": 0}\n'
    "\n"
    "  ⚡ Concurrent: 2 tool calls — read_file, search_files\n"
    "  📞 Tool 2: read_file(['path']) - {\"path\": \"README.txt\"}\n"
    "  ✅ Tool 2 completed in 0.10s - mentions secret.txt\n"
    "\n"
    "  📞 Tool 3: terminal(['command']) - {\"command\": \"cat secret.txt\"}\n"
    "  ✅ Tool 3 completed in 0.02s - flag{fll_e2e_ok}\n"
    "\n"
    "  📞 Tool 4: terminal(['command']) - {\"command\": \"grep -r fl\n"
    "  ✅ Tool 4 completed in 0.01s - preview cut\n"
    "\n"
    "📋 CONVERSATION SUMMARY\n"
    "✅ Completed: True\n"
    "👋 Agent execution completed!\n"
)


def test_split_log_steps_parses_stdout_tool_lines():
    trace = build_trace(_work_dir_with_log(STDOUT_FORMAT_LOG))
    kinds = [s.kind for s in trace.steps]
    assert "command" in kinds and "output" in kinds

    commands = [s.text for s in trace.steps if s.kind == "command"]
    # terminal 命令从参数预览 JSON 里解码出可读命令
    assert "ls -la /tmp/chall" in commands
    assert "cat secret.txt" in commands
    # 非 terminal 工具回退为 tool(args) - preview 原文
    assert any(c.startswith("read_file(['path'])") for c in commands)
    # 参数预览被截断时优雅降级（不抛异常、不丢步）
    assert any(c.startswith("terminal(['command'])") for c in commands)


def test_split_log_steps_does_not_misread_summary_emoji():
    """汇总区的 ``✅ Completed: True`` 不是工具完成行。"""
    steps = build_trace(_work_dir_with_log(STDOUT_FORMAT_LOG)).steps
    assert all("Completed: True" not in s.text or s.kind == "output"
               for s in steps)
    done_previews = [s.text for s in steps if s.kind == "output"]
    assert any("flag{fll_e2e_ok}" in t for t in done_previews)


def test_split_log_steps_verbose_call_line_without_preview():
    """verbose 模式调用行没有 ` - 预览` 尾巴，仍应切出 command 步。"""
    log = "  📞 Tool 1: terminal(['command'])\n  ✅ Tool 1 completed in 0.1s\n"
    steps = build_trace(_work_dir_with_log(log)).steps
    commands = [s.text for s in steps if s.kind == "command"]
    assert commands == ["terminal(['command'])"]


def test_split_log_steps_prefers_stdout_parser_over_blank_line_chunks():
    """含 📞 标记时走进度行切步，整块日志不再退化为单个 output 步。"""
    trace = build_trace(_work_dir_with_log(STDOUT_FORMAT_LOG))
    assert len(trace.steps) >= 8


def test_build_trace_from_stdout_log_feeds_replay_and_writeup():
    """端到端数据链路：stdout 格式 log → trace → replay 步数与 writeup 关键命令。"""
    work_dir = _work_dir_with_log(STDOUT_FORMAT_LOG)
    (work_dir / "FLAG").write_text("flag{fll_e2e_ok}\n", encoding="utf-8")

    trace = build_trace(work_dir)
    assert trace.flag == "flag{fll_e2e_ok}"

    text = replay_trace(trace)
    assert "steps=8" in text
    assert "cat secret.txt" in text
    assert "$ cat secret.txt" in text  # command 步以 $ 前缀回放
    assert "flag{fll_e2e_ok}" in text

    cmds = extract_key_commands(trace)
    assert any("cat secret.txt" in c for c in cmds)

    # 持久化：trace.json 可加载且回放一致
    loaded = load_trace(work_dir / TRACE_FILENAME)
    assert loaded is not None
    assert len(loaded.steps) == len(trace.steps)


def _work_dir_with_log(log_text: str):
    """Construct a persistent temporary challenge directory with solver.log."""
    work_dir = Path(tempfile.mkdtemp(prefix="fulilian-trace-test-"))
    (work_dir / SOLVER_LOG).write_text(log_text, encoding="utf-8")
    return work_dir

