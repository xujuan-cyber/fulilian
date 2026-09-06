"""多 Agent 协作 — 三省六部制简化版（F3-007 / F3-008 / F3-009）。

对应实施指南 09-P3-高级功能.md §9.3。组成：

- 4 个（可配）直接解题方向探索 agent（F3-007）：每个独立进程、独立
  子目录（solver.log/FLAG 隔离），从不同方向解同一题
- 异步同步工作记忆（F3-008）：``multiprocessing.Manager`` 共享 dict +
  父进程合并循环把各探索者黑板文件（blackboard.json）的新 Fact/死路
  持续并入中心黑板——一个 agent 的发现其他 agent 可见（stigmergy）
- 记忆上下文压缩 agent（F3-008）：后台线程周期性把中心黑板压缩为
  摘要 Hint（压缩函数可注入，默认启发式；LLM 可选）
- 幻觉指出和权重分析 agent（F3-009）：后台线程周期性扫描各探索者的
  FLAG 文件与 solver.log，候选 flag 全部过三重校验门，未确认的记为
  幻觉并发布到中心黑板；最终 flag 只取校验门 CONFIRMED 的

与指南的偏差：
- 指南用 ``multiprocessing.Process`` 跑压缩/幻觉检测；实测它们只读
  共享文件与 dict，线程足够且可注入测试（无网络也能测）。探索 agent
  保持进程隔离（指南语义，崩溃不影响其他）。
- 探索者子目录隔离与 racer 相同：同目录并行会互相覆盖 solver.log。
"""

from __future__ import annotations

import copy
import json
import multiprocessing
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    Hint,
    load_blackboard,
    save_blackboard,
)
from .monitor import scan_log_for_anomalies
from .racer import (
    _confirm_flag,
    _merge_board_into_parent,
    _stop_process,
    model_slug,
)
from .reasoner import Reasoner, TaskCategory
from .solver import FLAG_FILENAME, SOLVER_LOG, SolverResult, resolve_default_model, solver_worker
from .timebox import Timebox, difficulty_adjusted_budget
from .verify import (
    VerificationResult,
    extract_flag_candidates,
    verify_flag,
)

_SAFE_MP_CONTEXT = multiprocessing.get_context(
    "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
)

_POLL_INTERVAL = 1.0

# 默认探索方向（directions 未提供且黑板无 open Intent 时）
DEFAULT_DIRECTIONS = [
    "recon: enumerate the attack surface (ports, files, endpoints, params)",
    "fuzz and mutate inputs/parameters for anomalies",
    "inspect provided files/traffic for hidden or encoded data",
    "analyze crypto/encoding weaknesses of any secrets found",
]

# 记忆压缩触发阈值（中心黑板 Fact 数）
COMPRESS_THRESHOLD = 12


@dataclass
class ExplorerResult:
    """单个探索 agent 的结果。"""

    direction: str
    index: int = 0
    model: str = ""
    pid: int = 0
    ok: bool = False
    flag: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "index": self.index,
            "model": self.model,
            "pid": self.pid,
            "ok": self.ok,
            "flag": self.flag,
            "error": self.error,
        }


@dataclass
class MultiAgentResult:
    """多 Agent 协作汇总结果。"""

    flag: str = ""
    winner_index: int = -1
    explorers: list = field(default_factory=list)
    hallucinations: list = field(default_factory=list)   # 幻觉 flag 记录
    compressed_summaries: list = field(default_factory=list)  # 记忆压缩摘要
    alerts: list = field(default_factory=list)           # 对手监控告警
    facts_shared: int = 0                                # 共享记忆合并的 Fact 数

    @property
    def solved(self) -> bool:
        return bool(self.flag)

    def to_dict(self) -> dict:
        return {
            "flag": self.flag,
            "winner_index": self.winner_index,
            "solved": self.solved,
            "explorers": [e.to_dict() for e in self.explorers],
            "hallucinations": [dict(h) for h in self.hallucinations],
            "compressed_summaries": list(self.compressed_summaries),
            "alerts": [a.to_dict() for a in self.alerts],
            "facts_shared": self.facts_shared,
        }


# ── 异步同步工作记忆（F3-008）─────────────────────────────────────────────


class SharedMemory:
    """跨 agent 共享工作记忆（Manager dict + 中心黑板文件双通道）。

    - Manager dict（跨进程可见）：flag / 各探索者 fact 列表 / 幻觉记录
    - 中心黑板文件（work_dir/blackboard.json）：合并循环把各探索者黑板
      的新 Fact/死路并入，任何读黑板的一方（压缩器/幻觉检测器/人）可见
    """

    def __init__(self, manager=None):
        if manager is None:
            manager = _SAFE_MP_CONTEXT.Manager()
        self._manager = manager
        self.data = manager.dict()
        self.data["flag"] = ""
        self.data["winner_index"] = -1
        self.data["facts"] = manager.dict()      # explorer_index → [fact content]
        self.data["hallucinations"] = manager.list()
        self.stop_event = manager.Event()

    def publish_facts(self, explorer_index: int, contents: list[str]) -> None:
        bucket = dict(self.data["facts"])
        existing = list(bucket.get(explorer_index) or [])
        for c in contents:
            if c not in existing:
                existing.append(c)
        bucket[explorer_index] = existing
        self.data["facts"] = bucket

    def try_publish_flag(self, flag: str, explorer_index: int) -> bool:
        """发布 flag（先到先得）。返回是否本调用写入。"""
        if not flag or self.data.get("flag"):
            return False
        self.data["flag"] = flag
        self.data["winner_index"] = explorer_index
        self.stop_event.set()
        return True

    def add_hallucination(self, record: dict) -> None:
        self.data["hallucinations"].append(
            {k: str(v) for k, v in record.items()}
        )

    def snapshot(self) -> dict:
        return dict(self.data)

    def __getstate__(self):
        """Pickle 支持：排除不可 pickle 的 _manager，保留 proxy 对象。"""
        return {"data": self.data, "stop_event": self.stop_event}

    def __setstate__(self, state):
        self._manager = None
        self.data = state["data"]
        self.stop_event = state["stop_event"]


def merge_all_boards(
    explorer_dirs: list[Path], parent_board: Blackboard
) -> int:
    """把所有探索者黑板的新 Fact/死路并入中心黑板（返回新增 Fact 数）。

    合并前读中心黑板文件（可能已被其他循环更新），content 去重。
    """
    before = {f.content for f in parent_board.get_facts()}
    for d in explorer_dirs:
        _merge_board_into_parent(d, parent_board)
    added = len({f.content for f in parent_board.get_facts()} - before)
    return added


def default_compress(facts: list[str]) -> str:
    """启发式记忆压缩：保留最近事实，旧行合并为一条摘要。"""
    keep = facts[-4:]
    older = facts[:-4]
    lines = []
    if older:
        lines.append(f"earlier {len(older)} findings: " + "; ".join(x[:60] for x in older[:8]))
    lines.extend(keep)
    return "\n".join(f"- {x}" for x in lines)


class MemoryCompressor:
    """记忆上下文压缩 agent（F3-008 的压缩半边）。

    周期性检查中心黑板：Fact 数超过阈值 → 生成摘要写入 Hint
    （source="memory-compressor"）。黑板 append-only，旧 Fact 不删除，
    摘要作为协调层视图供后续读取方收敛上下文。
    """

    def __init__(
        self,
        board_path: str | Path,
        compress_fn: Optional[Callable[[list[str]], str]] = None,
        interval: float = 30.0,
        threshold: int = COMPRESS_THRESHOLD,
    ):
        self.board_path = Path(board_path)
        self.compress_fn = compress_fn or default_compress
        self.interval = max(5.0, float(interval))
        self.threshold = max(2, int(threshold))
        self.summaries: list[str] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="memory-compressor"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def tick_once(self) -> Optional[str]:
        """执行一轮压缩检查（供测试/手动触发）。"""
        board = load_blackboard(self.board_path)
        if board is None:
            return None
        facts = [f.content for f in board.get_facts()]
        if len(facts) < self.threshold:
            return None
        summary = self.compress_fn(facts)
        if not summary or not summary.strip():
            return None
        board.add_hint(Hint(content=summary, source="memory-compressor"))
        save_blackboard(board, self.board_path)
        self.summaries.append(summary)
        return summary

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001 — 压缩失败不阻断协作
                continue


# ── 幻觉检测 agent（F3-009）───────────────────────────────────────────────


def detect_hallucinations(
    explorer_dir: Path, explorer_index: int
) -> list[dict]:
    """对单个探索者目录做幻觉检测（候选 flag 全过三重校验门）。

    检查对象：FLAG 文件内容 + solver.log 中的 flag 候选。
    返回未通过校验门的候选记录（通过校验门的不是幻觉，不返回）。
    """
    records: list[dict] = []
    evidence = ""
    log_file = explorer_dir / SOLVER_LOG
    if log_file.is_file():
        evidence = log_file.read_text(encoding="utf-8", errors="replace")

    candidates: list[str] = []
    flag_file = explorer_dir / FLAG_FILENAME
    if flag_file.is_file():
        declared = flag_file.read_text(encoding="utf-8", errors="replace").strip()
        if declared:
            candidates.append(declared)
    try:
        candidates.extend(extract_flag_candidates(evidence or "", limit=10))
    except Exception:  # noqa: BLE001
        pass

    seen: set[str] = set()
    for cand in candidates:
        cand = (cand or "").strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        gate = verify_flag(cand, evidence=evidence or "", require_grounding=False)
        if gate is not VerificationResult.CONFIRMED:
            records.append(
                {
                    "explorer": explorer_index,
                    "candidate": cand[:120],
                    "verdict": gate.value,
                    "reason": "failed verification gate (三重校验门)",
                }
            )
    return records


class HallucinationDetector:
    """幻觉指出和权重分析 agent（F3-009）：周期扫描 + 记录 + 黑板公示。"""

    def __init__(
        self,
        explorer_dirs: list[Path],
        shared: SharedMemory,
        board_path: str | Path,
        interval: float = 15.0,
        on_hallucination: Optional[Callable[[dict], None]] = None,
    ):
        self.explorer_dirs = [Path(d) for d in explorer_dirs]
        self.shared = shared
        self.board_path = Path(board_path)
        self.interval = max(3.0, float(interval))
        self.on_hallucination = on_hallucination
        self.records: list[dict] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="hallucination-detector"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def tick_once(self) -> list[dict]:
        """执行一轮全量扫描（供测试/手动触发）。"""
        new_records: list[dict] = []
        for i, d in enumerate(self.explorer_dirs):
            for rec in detect_hallucinations(d, i):
                key = (rec["explorer"], rec["candidate"])
                if any((r["explorer"], r["candidate"]) == key for r in self.records):
                    continue
                self.records.append(rec)
                new_records.append(rec)
                self.shared.add_hallucination(rec)
                try:
                    board = load_blackboard(self.board_path) or Blackboard()
                    board.add_fact(
                        Fact(
                            content=(
                                f"HALLUCINATION: explorer-{rec['explorer']} candidate "
                                f"{rec['candidate']} rejected ({rec['verdict']})"
                            ),
                            source="hallucination-detector",
                        )
                    )
                    save_blackboard(board, self.board_path)
                except Exception:  # noqa: BLE001 — 公示失败不阻断检测
                    pass
                if self.on_hallucination:
                    try:
                        self.on_hallucination(rec)
                    except Exception:  # noqa: BLE001
                        pass
        return new_records

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001 — 检测失败不阻断协作
                continue


# ── 探索 agent（F3-007）───────────────────────────────────────────────────


def build_explorer_description(
    project, direction: str, shared_facts: Optional[list[str]] = None
) -> str:
    """构造探索者的题目描述：方向指令 + 共享发现（异步同步记忆注入）。"""
    parts = []
    if project.description:
        parts.append(project.description)
    parts.append(f"\n[Assigned direction] Focus on this attack direction: {direction}")
    if shared_facts:
        parts.append(
            "\n[Shared memory — findings from other agents, do not repeat]\n"
            + "\n".join(f"- {c}" for c in shared_facts[:15])
        )
    return "\n".join(parts)


def _explorer_target(
    solver_fn,
    project,
    work_dir: str,
    model: str,
    queue,
    shared: SharedMemory,
    explorer_index: int,
) -> None:
    """探索 agent 进程入口：停止事件感知 + 共享记忆回传。"""
    if shared.stop_event.is_set():
        try:
            queue.put(
                SolverResult(ok=False, exit_code=0, error="skipped: another agent solved")
            )
        except Exception:  # noqa: BLE001
            pass
        return
    # 启动时快照共享发现（异步同步记忆：晚启动者可见早发现）
    try:
        facts_map = dict(shared.data["facts"])
        shared_facts = [c for lst in facts_map.values() for c in (lst or [])]
    except Exception:  # noqa: BLE001
        shared_facts = []
    if shared_facts:
        project.description = (
            project.description
            + "\n[Shared memory — findings from other agents, do not repeat]\n"
            + "\n".join(f"- {c}" for c in shared_facts[:15])
        )
    try:
        solver_fn(project, work_dir, model, queue)
    except BaseException as e:  # noqa: BLE001 — 进程隔离
        try:
            queue.put(SolverResult(ok=False, exit_code=1, error=f"{type(e).__name__}: {e}"))
        except Exception:  # noqa: BLE001
            pass

    # 结束后回传：本地黑板 facts + flag（过校验门）
    work = Path(work_dir)
    try:
        board = load_blackboard(work / BLACKBOARD_FILENAME)
        if board:
            contents = [
                f.content
                for f in board.get_facts()
                if f.state.value in ("confirmed", "refuted")
                and not f.content.startswith("solver ")
            ]
            shared.publish_facts(explorer_index, contents)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .racer import _confirm_flag as _cf

        flag = _cf(work)
        if flag:
            shared.try_publish_flag(flag, explorer_index)
    except Exception:  # noqa: BLE001
        pass


# ── 主流程 ────────────────────────────────────────────────────────────────


def resolve_directions(
    directions: Optional[list], board_path: Optional[Path] = None
) -> list[str]:
    """解析探索方向：显式 > 中心黑板 open Intent > 通用默认。"""
    if isinstance(directions, str):
        directions = [d.strip() for d in directions.split(",") if d.strip()]
    if directions:
        return [str(d) for d in directions]
    if board_path is not None:
        board = load_blackboard(board_path)
        if board:
            goals = [
                i.goal or i.approach
                for i in board.get_open_intents()
                if (i.goal or i.approach)
            ]
            if goals:
                return goals
    return list(DEFAULT_DIRECTIONS)


def run_multi_agent(
    project,
    directions: Optional[list] = None,
    n_direct_explorers: int = 4,
    work_dir: Optional[str | Path] = None,
    timeout: int = 0,
    model: str = "",
    solver_fn: Optional[Callable] = None,
    memory_compressor: bool = True,
    hallucination_detector: bool = True,
    opponent_monitor: bool = True,
    quiet: bool = False,
    reasoner: Optional[Reasoner] = None,
) -> MultiAgentResult:
    """启动多 Agent 协作（F3-007/008/009）。

    Args:
        project: Project 对象
        directions: 探索方向列表；None 从黑板/Reasoner/默认解析
        n_direct_explorers: 直接解题方向探索 agent 数（默认 4）
        work_dir: 工作目录（默认 project.challenge_dir）
        timeout: 全局时间盒（秒）；0 用难度自适应预算
        model: 覆盖模型（空串用配置默认）
        solver_fn: 可注入求解实现（测试用）
        memory_compressor: 启用记忆压缩 agent
        hallucination_detector: 启用幻觉检测 agent
        opponent_monitor: 启用对手 Agent 监控（F3-013 集成）
        quiet: 静默输出
        reasoner: Reasoner 实例（提供时替代随机方向分配）

    Returns:
        MultiAgentResult
    """
    solver_fn = solver_fn or solver_worker
    mp_context = _SAFE_MP_CONTEXT
    n = max(1, int(n_direct_explorers))
    base_dir = Path(work_dir or project.challenge_dir or project.challenge_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    board_path = base_dir / BLACKBOARD_FILENAME

    dirs = resolve_directions(directions, board_path)
    # 如果提供了 Reasoner 且没有显式 directions，用 Reasoner 的任务分配
    if reasoner is not None and not directions:
        plan = reasoner.initial_plan(project, None)
        if plan and plan.tasks:
            reasoner_dirs = [t.description for t in plan.tasks]
            if reasoner_dirs:
                dirs = reasoner_dirs
    resolved_model = model or project.model or resolve_default_model()

    budget = timeout or difficulty_adjusted_budget(project.difficulty)
    timebox = Timebox(initial_budget=budget, incremental=False)
    timebox.start()

    shared = SharedMemory()
    parent_board = load_blackboard(board_path) or Blackboard(
        challenge_id=project.challenge_id
    )

    compressor: Optional[MemoryCompressor] = None
    detector: Optional[HallucinationDetector] = None
    if memory_compressor:
        compressor = MemoryCompressor(board_path)
        compressor.start()
    if hallucination_detector:
        detector = HallucinationDetector([], shared, board_path)
        detector.start()

    slots: list[dict] = []
    collected_alerts: list = []
    started = time.time()
    try:
        for i in range(n):
            direction = dirs[i % len(dirs)]
            exp_dir = base_dir / f"explore-{i}-{model_slug(direction)[:24]}"
            exp_dir.mkdir(parents=True, exist_ok=True)
            exp_project = copy.deepcopy(project)
            exp_project.model = resolved_model
            # 方向注入 description（solver_worker 的 build_solve_query 会带上）
            exp_project.description = build_explorer_description(
                project, direction
            )
            queue = mp_context.Queue()
            proc = mp_context.Process(
                target=_explorer_target,
                args=(
                    solver_fn, exp_project, str(exp_dir), resolved_model,
                    queue, shared, i,
                ),
                name=f"explorer-{i}",
            )
            proc.start()
            slots.append(
                {
                    "index": i,
                    "direction": direction,
                    "dir": exp_dir,
                    "proc": proc,
                    "queue": queue,
                    "result": ExplorerResult(
                        direction=direction, index=i, model=resolved_model, pid=proc.pid
                    ),
                }
            )
            if detector is not None:
                detector.explorer_dirs.append(exp_dir)
            if not quiet:
                print(
                    f"[multi-agent] {project.challenge_id}: explorer#{i} "
                    f"direction={direction[:60]} pid={proc.pid}",
                    flush=True,
                )

        winner: Optional[dict] = None
        while True:
            for s in slots:
                if not s["proc"].is_alive() and not s.get("reaped"):
                    s["reaped"] = True
                    s["proc"].join(timeout=3)
                    try:
                        if not s["queue"].empty():
                            res = s["queue"].get(timeout=1)
                            s["result"].ok = res.ok
                            s["result"].error = res.error
                    except Exception:  # noqa: BLE001
                        pass
                    s["result"].flag = _confirm_flag(s["dir"])
                    if not quiet:
                        print(
                            f"[multi-agent] explorer#{s['index']} finished "
                            f"flag={'yes' if s['result'].flag else 'no'}",
                            flush=True,
                        )
            # flag 判定：共享记忆（探测者回传）或已收割目录（过校验门的才认）
            if winner is None:
                if shared.data.get("flag"):
                    widx = shared.data.get("winner_index", -1)
                    winner = next((s for s in slots if s["index"] == widx), None)
                    if winner is None and slots:
                        winner = slots[0]
            if winner is None:
                for s in slots:
                    if s.get("reaped") and s["result"].flag:
                        winner = s
                        shared.try_publish_flag(s["result"].flag, s["index"])
                        break
            if winner is not None or all(s.get("reaped") for s in slots):
                break
            # 对手监控（F3-013）：扫描各探索者日志尾部，告警累积进结果
            if opponent_monitor:
                for s in slots:
                    log_file = s["dir"] / SOLVER_LOG
                    if not log_file.is_file():
                        continue
                    alerts = scan_log_for_anomalies(
                        _tail(log_file, 8000), source=f"explorer-{s['index']}"
                    )
                    for a in alerts:
                        known = {
                            (x.level, x.label, x.source, x.excerpt)
                            for x in collected_alerts
                        }
                        key = (a.level, a.label, a.source, a.excerpt)
                        if key not in known:
                            collected_alerts.append(a)
            if timebox.check():
                if not quiet:
                    print(f"[multi-agent] {project.challenge_id}: timebox expired", flush=True)
                break
            sentinels = [
                s["proc"].sentinel for s in slots if not s.get("reaped")
            ]
            if sentinels:
                multiprocessing.connection.wait(
                    sentinels,
                    timeout=min(_POLL_INTERVAL, max(0.1, timebox.remaining())),
                )
            else:
                time.sleep(0.05)
    finally:
        for s in slots:
            if s["proc"].is_alive():
                _stop_process(s["proc"])
        if compressor is not None:
            compressor.stop()
        if detector is not None:
            detector.stop()

    # 收尾扫描：循环 break 前的最后一轮日志变化也要纳入监控（F3-013）
    if opponent_monitor:
        for s in slots:
            log_file = s["dir"] / SOLVER_LOG
            if not log_file.is_file():
                continue
            for a in scan_log_for_anomalies(_tail(log_file, 8000), source=f"explorer-{s['index']}"):
                known = {
                    (x.level, x.label, x.source, x.excerpt) for x in collected_alerts
                }
                if (a.level, a.label, a.source, a.excerpt) not in known:
                    collected_alerts.append(a)

    # 最终 flag 判定：幻觉检测后仍 CONFIRMED 的优先
    result = MultiAgentResult(
        hallucinations=[dict(r) for r in (detector.records if detector else [])],
        compressed_summaries=list(compressor.summaries if compressor else []),
        alerts=[a.to_dict() for a in collected_alerts],
    )
    hallucinated = {
        r["candidate"] for r in result.hallucinations
    }
    for s in slots:
        result.explorers.append(s["result"])
        if winner is not None and s is winner and s["result"].flag:
            result.flag = s["result"].flag
            result.winner_index = s["index"]
    if not result.flag:
        # 兜底：任意探索者目录的 flag（过门），排除已知幻觉
        for s in slots:
            f = _confirm_flag(s["dir"])
            if f and f not in hallucinated:
                result.flag = f
                result.winner_index = s["index"]
                break
    if result.flag:
        parent_board.add_fact(
            Fact(
                content=(
                    f"multi-agent solved by explorer-{result.winner_index} "
                    f"({result.explorers[result.winner_index].direction[:60] if result.explorers else ''})"
                ),
                source="multi-agent",
            )
        )
        try:
            (base_dir / FLAG_FILENAME).write_text(result.flag + "\n", encoding="utf-8")
        except OSError:
            pass

    # 黑板合并 + 共享记忆统计
    explorer_dirs = [Path(s["dir"]) for s in slots]
    result.facts_shared = merge_all_boards(explorer_dirs, parent_board)
    save_blackboard(parent_board, board_path)
    result.explorers.sort(key=lambda e: e.index)
    if not quiet:
        if result.flag:
            print(
                f"[multi-agent] {project.challenge_id}: SOLVED by "
                f"explorer-{result.winner_index} — {result.flag}",
                flush=True,
            )
        else:
            print(
                f"[multi-agent] {project.challenge_id}: no flag "
                f"({round(time.time() - started, 1)}s, {n} explorers, "
                f"{len(result.hallucinations)} hallucination(s))",
                flush=True,
            )
    return result


def _tail(path: Path, nbytes: int) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def run_multi_agent_for_challenge(challenge_id: str, **kwargs) -> MultiAgentResult:
    """便捷入口：challenge_id（目录或注册表条目）→ Project → run_multi_agent。"""
    from .dispatcher import Project
    from .registry import challenge_to_project, load_challenges

    path = Path(challenge_id).expanduser()
    if path.is_dir():
        if (path / "challenge.json").is_file():
            project = challenge_to_project(
                json.loads(path.read_text(encoding="utf-8")), base_dir=path.parent
            )
        else:
            project = Project(challenge_id=path.name, challenge_dir=str(path))
    else:
        entries = [e for e in load_challenges(challenge_id) if e.get("id")]
        if entries:
            project = challenge_to_project(entries[0])
        else:
            project = Project(challenge_id=challenge_id, challenge_dir=challenge_id)
    return run_multi_agent(project, **kwargs)


def run_boomerang(project, *, max_rounds: int = 2, max_explorers: int = 4,
                  work_dir: Optional[str | Path] = None, **kwargs) -> MultiAgentResult:
    """Run bounded round-trip exploration (F4-009).

    Each completed fan-out is a checkpoint. OPEN blackboard intents become the
    next fan-out's directions; a confirmed flag ends the loop immediately.
    """
    base = Path(work_dir or project.challenge_dir or project.challenge_id)
    base.mkdir(parents=True, exist_ok=True)
    directions = kwargs.pop("directions", None)
    final = MultiAgentResult()
    seen: set[str] = set()
    for round_no in range(max(1, int(max_rounds))):
        round_dir = base / f"boomerang-round-{round_no}"
        result = run_multi_agent(
            project, directions=directions, n_direct_explorers=max_explorers,
            work_dir=round_dir, **kwargs,
        )
        final = result
        if result.solved:
            return result
        board = load_blackboard(round_dir / BLACKBOARD_FILENAME)
        if board is None:
            break
        directions = []
        for intent in board.get_open_intents():
            text = " ".join(
                part for part in (str(intent.goal).strip(), str(intent.approach).strip())
                if part
            )
            if text and text not in seen:
                seen.add(text)
                directions.append(text)
        if not directions:
            break
    return final


__all__ = [
    "COMPRESS_THRESHOLD",
    "DEFAULT_DIRECTIONS",
    "ExplorerResult",
    "HallucinationDetector",
    "MemoryCompressor",
    "MultiAgentResult",
    "SharedMemory",
    "build_explorer_description",
    "default_compress",
    "detect_hallucinations",
    "merge_all_boards",
    "resolve_directions",
    "run_multi_agent",
    "run_multi_agent_for_challenge",
    "run_boomerang",
]
