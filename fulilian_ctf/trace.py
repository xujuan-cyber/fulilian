"""追踪回放 — 解题轨迹记录 + 逐步回放（F3-014）。

对应实施指南 09-P3-高级功能.md 的 F3-014 与验收项
「追踪回放正确（命令 + 输出 + flag 验证结果完整记录）」。

数据来源（全部是步骤 05-07 已存在的产物，不侵入原生代码）：
- ``work_dir/solver.log`` — solver 全程 stdout/stderr（命令 + 输出）；
  既可以是 dispatcher/``_run_solve_once`` 的重定向落盘，也可以是默认
  solve 路径用 ``fulilian_ctf.solver.tee_solver_log`` 透传 tee 的 run_agent
  stdout（含 📞/✅ 工具进度行，``_split_log_steps`` 两种格式都认）
- ``work_dir/blackboard.json`` — Fact/Intent/死路（flag 验证结论的来源）
- ``work_dir/FLAG`` — 声明式提交的 flag

产出：``work_dir/trace.json``，结构见 ``Trace.to_dict``；``replay_trace``
按步回放，``build_trace`` 幂等（重复调用重新从产物构建）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .blackboard import BLACKBOARD_FILENAME, load_blackboard
from .solver import FLAG_FILENAME, SOLVER_LOG
from .verify import VerificationResult, verify_flag

TRACE_FILENAME = "trace.json"

# 单步输出上限（字符）：trace 是给人回放的，超长输出截断保存
MAX_STEP_CHARS = 2000
MAX_STEPS = 200

# solver.log 中工具调用/命令执行的常见标记行（用于切步）
_STEP_SPLIT = re.compile(
    r"\n(?=(?:\[\d+\]\s|执行的命令|Command:|\$\s|> ))", re.MULTILINE
)

# run_agent stdout 的工具进度行（默认 solve 的 tee 落盘与 dispatcher 的
# stdout 重定向同源）。示例（agent/tool_executor.py 的进度打印）：
#   📞 Tool 1: terminal(['command']) - {"command": "ls -la", "task_id": "default"}
#   ✅ Tool 1 completed in 0.14s - {"output": "total 48...", "exit_code": 0}
# verbose 模式下调用行没有 ` - 预览` 尾巴；display_index 缺省时无序号。
_TOOL_CALL_LINE = re.compile(
    r"^\s*📞\s*Tool\s*(?:\d+)?\s*:\s*(\S+?)\(([^)]*)\)(?:\s*-\s*(.*))?$"
)
_TOOL_DONE_LINE = re.compile(
    r"^\s*✅\s*Tool\s*\d+\s+completed(?:\s+in\s+[\d.]+s)?(?:\s*-\s*(.*))?$"
)
# 参数预览 JSON 里的 terminal 命令值（预览可能被截断，尽力而为）
_ARG_COMMAND_VALUE = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass
class TraceStep:
    """轨迹中的一步：一条命令/一段输出。"""

    index: int = 0
    kind: str = "output"   # "command" | "output"
    text: str = ""

    def to_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind, "text": self.text}


@dataclass
class Trace:
    """一次解题尝试的完整轨迹。"""

    challenge_id: str = ""
    model: str = ""
    category: str = ""
    difficulty: str = ""
    flag: str = ""
    flag_verified: str = ""     # 三重校验门结论（VerificationResult.value）
    steps: list = field(default_factory=list)     # list[TraceStep]
    facts: list = field(default_factory=list)     # 黑板 Fact content 列表
    dead_ends: list = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "challenge_id": self.challenge_id,
            "model": self.model,
            "category": self.category,
            "difficulty": self.difficulty,
            "flag": self.flag,
            "flag_verified": self.flag_verified,
            "steps": [s.to_dict() for s in self.steps],
            "facts": list(self.facts),
            "dead_ends": list(self.dead_ends),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": round(self.duration, 1),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        steps = [
            TraceStep(
                index=int(s.get("index", i)),
                kind=str(s.get("kind", "output")),
                text=str(s.get("text", "")),
            )
            for i, s in enumerate(d.get("steps") or [])
        ]
        return cls(
            challenge_id=str(d.get("challenge_id", "")),
            model=str(d.get("model", "")),
            category=str(d.get("category", "")),
            difficulty=str(d.get("difficulty", "")),
            flag=str(d.get("flag", "")),
            flag_verified=str(d.get("flag_verified", "")),
            steps=steps,
            facts=[str(f) for f in (d.get("facts") or [])],
            dead_ends=[str(x) for x in (d.get("dead_ends") or [])],
            started_at=float(d.get("started_at", 0.0) or 0.0),
            finished_at=float(d.get("finished_at", 0.0) or 0.0),
            duration=float(d.get("duration", 0.0) or 0.0),
        )


def _push_step(steps: list, text: str, kind: str) -> None:
    """追加一步（统一 strip / 截断 / 步号，空文本与超上限时跳过）。"""
    text = text.strip()
    if not text or len(steps) >= MAX_STEPS:
        return
    if len(text) > MAX_STEP_CHARS:
        text = text[:MAX_STEP_CHARS] + f"\n... (truncated, {len(text)} chars)"
    steps.append(TraceStep(index=len(steps) + 1, kind=kind, text=text))


def _command_text_from_tool_call(tool: str, arglist: str, preview: str) -> str:
    """从工具调用行提取可读命令文本。

    terminal 工具优先抠出参数预览 JSON 里的 ``command`` 值（预览被截断时
    尽力解码）；其余工具回退为 ``tool(args) - preview`` 原始内容。
    """
    m = _ARG_COMMAND_VALUE.search(preview or "")
    if m:
        try:
            return json.loads(f'"{m.group(1)}"')
        except ValueError:
            return m.group(1)
    raw = f"{tool}({arglist})"
    if preview:
        raw += f" - {preview}"
    return raw


def _split_stdout_steps(log_text: str) -> list[TraceStep]:
    """按 run_agent stdout 的工具进度行切步。

    📞 调用行 → command 步（terminal 命令优先），✅ 完成行 → 其输出预览
    作为 output 步，其余非空行聚成段按空行边界落为 output 步。纯启发式：
    agent 进度打印格式变化时最多退化为少切几步，不影响正确性。
    """
    steps: list[TraceStep] = []
    buf: list[str] = []

    def _flush_buf() -> None:
        text = "\n".join(buf)
        buf.clear()
        # Keep only meaningful preamble output. Headers and final summaries are
        # metadata, not solver steps.
        if text and "RECON" in text:
            _push_step(steps, text, "output")

    for line in log_text.splitlines():
        call = _TOOL_CALL_LINE.match(line)
        done = _TOOL_DONE_LINE.match(line)
        if call or done:
            _flush_buf()
            if call:
                _push_step(
                    steps,
                    _command_text_from_tool_call(
                        call.group(1), call.group(2), call.group(3) or ""
                    ),
                    "command",
                )
            else:
                _push_step(steps, done.group(1) or "", "output")
        else:
            if line.strip() and not line.lstrip().startswith(("⚡", "📋", "✅ Completed:", "👋")):
                buf.append(line)
    _flush_buf()
    return steps


def _split_log_steps(log_text: str) -> list[TraceStep]:
    """把 solver.log 切成回放步骤：命令行一步、其输出一步。

    run_agent stdout 格式（含 📞 工具进度行）优先按进度行切；否则按
    ``$ ``/``[N] `` 等命令标记行切块，块内第一行若是命令则拆出 command
    步，其余内容作为对应 output 步（无任何标记时整块按空行分段）。
    """
    if not log_text.strip():
        return []
    if "📞" in log_text:
        return _split_stdout_steps(log_text)

    chunks = _STEP_SPLIT.split(log_text)
    if len(chunks) <= 1:
        chunks = [c for c in re.split(r"\n\s*\n", log_text) if c.strip()]

    steps: list[TraceStep] = []

    for chunk in chunks[: MAX_STEPS * 2]:
        if not chunk.strip():
            continue
        lines = chunk.strip().splitlines()
        if lines and _looks_like_command(lines[0]):
            _push_step(steps, lines[0], "command")
            _push_step(steps, "\n".join(lines[1:]), "output")
        else:
            _push_step(steps, chunk, "output")
        if len(steps) >= MAX_STEPS:
            break
    return steps


def _looks_like_command(line: str) -> bool:
    return bool(
        re.match(r"^(?:\[\d+\]\s|\$\s|>\s)", line)
        or line.startswith(("Command:", "执行的命令"))
    )


def _read_flag_with_gate(work_dir: Path) -> tuple[str, str]:
    """读取 FLAG 文件并过三重校验门，返回 (flag, gate_value)。"""
    flag = ""
    flag_file = work_dir / FLAG_FILENAME
    if flag_file.is_file():
        flag = flag_file.read_text(encoding="utf-8", errors="replace").strip()
    if not flag:
        return "", ""
    gate = verify_flag(flag, evidence="", require_grounding=False)
    if gate is not VerificationResult.CONFIRMED:
        # 畸形/占位 flag 仍记录（回放要完整），但标注校验结论
        return flag, gate.value
    return flag, gate.value


def build_trace(work_dir: str | Path, project=None) -> Trace:
    """从工作目录的既有产物构建 trace（不要求 solver 仍在运行）。

    Args:
        work_dir: 挑战工作目录（含 solver.log / blackboard.json / FLAG）
        project: 可选 Project 对象（提供 category/difficulty/model 元信息）

    Returns:
        Trace（同时持久化到 work_dir/trace.json）
    """
    work_dir = Path(work_dir)

    flag, gate_value = _read_flag_with_gate(work_dir)

    log_text = ""
    log_file = work_dir / SOLVER_LOG
    if log_file.is_file():
        log_text = log_file.read_text(encoding="utf-8", errors="replace")

    steps = _split_log_steps(log_text)

    facts: list[str] = []
    dead_ends: list[str] = []
    board = load_blackboard(work_dir / BLACKBOARD_FILENAME)
    if board:
        facts = [f.content for f in board.get_facts()][:50]
        dead_ends = sorted(board.dead_ends)[:50]
        if not flag:
            # 兜底：黑板里若有「flag」字样的 Fact，记录其内容（校验门结论如实标注）
            for fact in board.get_facts():
                if "flag" in fact.content.lower():
                    flag, gate_value = fact.content, "unverified"
                    break

    trace = Trace(
        challenge_id=getattr(project, "challenge_id", "") or work_dir.name,
        model=getattr(project, "model", "") or "",
        category=getattr(project, "category", "") or "",
        difficulty=getattr(project, "difficulty", "") or "",
        flag=flag,
        flag_verified=gate_value,
        steps=steps,
        facts=facts,
        dead_ends=dead_ends,
        started_at=getattr(project, "started_at", 0.0) or 0.0,
        finished_at=getattr(project, "finished_at", 0.0) or 0.0,
        duration=(
            (getattr(project, "finished_at", 0.0) or 0.0)
            - (getattr(project, "started_at", 0.0) or 0.0)
        )
        if getattr(project, "finished_at", 0.0) and getattr(project, "started_at", 0.0)
        else 0.0,
    )
    save_trace(trace, work_dir / TRACE_FILENAME)
    return trace


def save_trace(trace: Trace, path: str | Path) -> Path:
    """持久化 trace.json（原子写）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(trace.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)
    return path


def load_trace(path: str | Path) -> Trace | None:
    """加载 trace.json；不存在返回 None。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return Trace.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def get_or_build_trace(work_dir: str | Path, project=None) -> Trace:
    """优先加载已有 trace.json，否则从产物构建。"""
    return load_trace(Path(work_dir) / TRACE_FILENAME) or build_trace(work_dir, project)


def replay_trace(
    trace: Trace, start_step: int = 1, as_json: bool = False
) -> str:
    """逐步回放轨迹（命令 + 输出 + flag 验证结果）。

    Args:
        trace: Trace 对象
        start_step: 起始步（1-based）
        as_json: 输出结构化 JSON（供 --json）

    Returns:
        str: 回放文本
    """
    if as_json:
        payload = trace.to_dict()
        payload["steps"] = [
            s.to_dict() for s in trace.steps if s.index >= max(1, start_step)
        ]
        return json.dumps(payload, indent=2, ensure_ascii=False)

    lines = [
        f"replay: {trace.challenge_id}"
        + (f" (model={trace.model})" if trace.model else "")
    ]
    lines.append(
        f"flag={trace.flag or '(none)'}"
        f" | verified={trace.flag_verified or 'n/a'}"
        f" | steps={len(trace.steps)}"
        + (f" | duration={int(trace.duration)}s" if trace.duration else "")
    )
    lines.append("-" * 60)
    shown = 0
    for step in trace.steps:
        if step.index < max(1, start_step):
            continue
        prefix = "$" if step.kind == "command" else ">"
        body = step.text if "\n" not in step.text else step.text.replace("\n", "\n  ")
        lines.append(f"[{step.index}] {prefix} {body}")
        shown += 1
    if shown == 0:
        lines.append("(no steps recorded)")
    return "\n".join(lines)


# ── F4-007 结构化轨迹（Coordinator 轨迹回读） ────────────────────────────

MAX_TRACE_OUTPUT = 500  # 工具输出截断字符数


@dataclass
class TraceEntry:
    """轨迹中的一条记录。"""

    timestamp: float = 0.0
    round: int = 0
    action: str = ""
    tool_call: str = ""
    tool_output: str = ""
    reasoning: str = ""
    conclusion: str = ""
    flag_found: bool = False
    error_type: str = ""

    def __post_init__(self) -> None:
        if len(self.tool_output) > MAX_TRACE_OUTPUT:
            self.tool_output = self.tool_output[:MAX_TRACE_OUTPUT] + "... (truncated)"

    def to_dict(self) -> dict:
        return {
            "timestamp": round(self.timestamp, 3),
            "round": self.round,
            "action": self.action,
            "tool_call": self.tool_call,
            "tool_output": self.tool_output,
            "reasoning": self.reasoning,
            "conclusion": self.conclusion,
            "flag_found": self.flag_found,
            "error_type": self.error_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TraceEntry":
        return cls(
            timestamp=float(d.get("timestamp", 0.0)),
            round=int(d.get("round", 0)),
            action=str(d.get("action", "")),
            tool_call=str(d.get("tool_call", "")),
            tool_output=str(d.get("tool_output", "")),
            reasoning=str(d.get("reasoning", "")),
            conclusion=str(d.get("conclusion", "")),
            flag_found=bool(d.get("flag_found", False)),
            error_type=str(d.get("error_type", "")),
        )


@dataclass
class SolverTrace:
    """一个 solver 的完整轨迹记录。"""

    solver_id: str = ""
    model: str = ""
    entries: list[TraceEntry] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    flag_found: bool = False
    score: int = 0

    def add_entry(self, entry: TraceEntry) -> None:
        """添加一条轨迹条目。"""
        self.entries.append(entry)

    def classify_failures(self) -> dict:
        """分析失败类型，返回分类统计。"""
        no_flag = [e for e in self.entries if not e.flag_found]
        errors = [e for e in no_flag if e.error_type]
        stalled = [e for e in no_flag if "stall" in e.error_type.lower()]
        timeout = [e for e in no_flag if "timeout" in e.error_type.lower()]
        tool_err = [e for e in no_flag if "tool" in e.error_type.lower() or "exec" in e.error_type.lower()]

        return {
            "total_entries": len(self.entries),
            "flag_found": self.flag_found,
            "error_entries": len(errors),
            "stalled": len(stalled),
            "timeout": len(timeout),
            "tool_error": len(tool_err),
            "error_types": sorted(set(e.error_type for e in errors if e.error_type)),
        }

    def summarize(self) -> str:
        """生成轨迹摘要。"""
        lines = [
            f"SolverTrace: {self.solver_id}",
            f"  Model: {self.model}",
            f"  Entries: {len(self.entries)}",
            f"  Duration: {max(0.0, self.end_time - self.start_time):.1f}s",
            f"  Flag found: {self.flag_found}",
        ]
        if self.entries:
            actions = sorted(set(e.action for e in self.entries if e.action))
            lines.append(f"  Actions: {', '.join(actions)}")
            failures = self.classify_failures()
            if failures["error_entries"]:
                lines.append(f"  Errors: {failures['error_entries']} ({', '.join(failures['error_types'])})")
        return "\n".join(lines)

    def save(self, path: str | Path) -> Path:
        """持久化到 JSON 文件。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "solver_id": self.solver_id,
            "model": self.model,
            "entries": [e.to_dict() for e in self.entries],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "flag_found": self.flag_found,
            "score": self.score,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "SolverTrace":
        """从 JSON 文件加载。"""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [TraceEntry.from_dict(e) for e in (data.get("entries") or [])]
        return cls(
            solver_id=str(data.get("solver_id", "")),
            model=str(data.get("model", "")),
            entries=entries,
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 0.0)),
            flag_found=bool(data.get("flag_found", False)),
            score=int(data.get("score", 0)),
        )


__all__ = [
    "TRACE_FILENAME",
    "MAX_TRACE_OUTPUT",
    "Trace",
    "TraceEntry",
    "TraceStep",
    "SolverTrace",
    "build_trace",
    "get_or_build_trace",
    "load_trace",
    "replay_trace",
    "save_trace",
]
