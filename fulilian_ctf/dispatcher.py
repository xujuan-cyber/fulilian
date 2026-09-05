"""多题并行调度器 + 自动调度 + 收割轮 + 时间盒 + 探针（F2-001/002/003/007/008/010）。

确定性调度（非 LLM 驱动）：
1. 新题优先（按 score 降序）
2. 无新题 → 收割轮：按 EV 排序回退已放弃/超时的题
3. 分配前探活（可解性探针）→ INFRA_BLOCKED 跳过
4. 每个 solver 独立进程（崩溃不影响其他），时间盒到期自动中断并输出接力块

状态机：NEW →(探针)→ IN_PROGRESS → SOLVED / ABANDONED / TIMEOUT；探针失败 → INFRA_BLOCKED
收割轮会重跑 ABANDONED / TIMEOUT 的题（attempts 递增，超过 max_attempts 不再回收）。

EV 公式（收割轮排序）：EV = score * difficulty_factor * attempts_penalty
难度因子 easy=1.0 / medium=0.7 / hard=0.4；每次尝试惩罚 20%（下限 0.2）。
"""

from __future__ import annotations

import functools
import json
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .blackboard import BLACKBOARD_FILENAME, Fact, State, load_blackboard, save_blackboard
from .probe import ProbeResult, probe_challenge
from .relay import (
    atomic_write_text,
    build_relay,
    is_relay_meta_text,
    parse_relay,
    read_relay_file,
    relay_worthy_fact,
    write_relay_file,
)
from .solver import SOLVER_LOG, SolverResult, read_flag_file, scan_log_for_flag, solver_worker
from .verify import VerificationResult, check_output_for_flag, verify_flag
from .stopper import (
    DEFAULT_MAX_NO_OUTPUT_ROUNDS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_VARIANT_FAILURES,
    STOP_REASONS,
    Stopper,
    TokenCounter,
    count_variant_failures,
    estimate_tokens_from_log,
)
from .timebox import Timebox, difficulty_adjusted_budget


class ChallengeStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    ABANDONED = "abandoned"
    TIMEOUT = "timeout"
    SOLVED = "solved"
    INFRA_BLOCKED = "infra_blocked"


# 收割轮可回收的状态（已放弃/超时，等待按 EV 重评）
HARVESTABLE = (ChallengeStatus.ABANDONED, ChallengeStatus.TIMEOUT)

# P0-3：收割轮 respawn 升级路由（(status, stop_reason_key) → 升级动作）。
# stop_reason 前缀匹配 "STOPPED: <KEY>"（_interrupt_stopped 写入）；
# 时间盒自然超时（_interrupt 写 "timebox expired ..."）无 STOPPED 前缀 → key=None。
ESCALATION_ROUTES = {
    ("*", "HYPOTHESIS_REPEATED"): "switch_attack_class",
    ("*", "NO_OUTPUT"): "extend_timebox",
    ("*", "BUDGET_EXCEEDED"): "switch_model",
    (ChallengeStatus.TIMEOUT.value, None): "switch_approach",
}
DEFAULT_ROUTE = "plain_retry"  # 无匹配 → 现状行为（同模型同 prompt 重试）

# 难度因子（EV 计算用）：越难的题回收价值越低
DIFFICULTY_FACTORS = {"easy": 1.0, "medium": 0.7, "hard": 0.4}

# 探针并行数上限（同时探活的题数）
PROBE_CONCURRENCY = 4


def _safe_target(solver_fn: Callable, project: Project, work_dir: str,
                 model: str, queue) -> None:
    """solver 进程的异常安全包装：任何异常都上报 SolverResult，不裸崩。

    真实 solver（solver_worker）自身已捕获异常；此包装兜底 fake/第三方
    solver_fn，保证「崩溃不影响其他」的进程隔离语义。
    """
    try:
        solver_fn(project, work_dir, model, queue)
    except BaseException as e:  # noqa: BLE001 — 进程隔离：任何异常都不影响其他 solver
        try:
            queue.put(SolverResult(ok=False, exit_code=1, error=f"{type(e).__name__}: {e}"))
        except Exception:  # noqa: BLE001
            pass


@dataclass
class Project:
    """一道 CTF 题的完整上下文（solver project）。"""

    challenge_id: str
    challenge_dir: str = ""
    target_host: str = ""
    target_port: int = 0
    difficulty: str = "medium"
    title: str = ""
    category: str = ""
    description: str = ""
    score: int = 0
    status: ChallengeStatus = ChallengeStatus.NEW
    attempts: int = 0
    ev_score: float = 0.0
    stop_reason: str = ""
    flag: str = ""
    model: str = ""
    timebox_override: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    last_tier: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.challenge_id,
            "title": self.title,
            "category": self.category,
            "difficulty": self.difficulty,
            "score": self.score,
            "status": self.status.value,
            "attempts": self.attempts,
            "ev_score": round(self.ev_score, 3),
            "stop_reason": self.stop_reason,
            "flag": self.flag,
            "target_host": self.target_host,
            "target_port": self.target_port,
            "challenge_dir": self.challenge_dir,
            "model": self.model,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_tier": self.last_tier,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # noqa: F841
        return cls(
            challenge_id=str(d.get("id", "")),
            challenge_dir=str(d.get("challenge_dir", "")),
            target_host=str(d.get("target_host", "")),
            target_port=int(d.get("target_port", 0) or 0),
            difficulty=str(d.get("difficulty", "medium")).lower(),
            title=str(d.get("title", "")),
            category=str(d.get("category", "")).lower(),
            description=str(d.get("description", "")),
            score=int(d.get("score", 0) or 0),
            status=ChallengeStatus(str(d.get("status", "new"))),
            attempts=int(d.get("attempts", 0)),
            ev_score=float(d.get("ev_score", 0.0)),
            stop_reason=str(d.get("stop_reason", "")),
            flag=str(d.get("flag", "")),
            model=str(d.get("model", "")),
            timebox_override=int(d.get("timebox_override", 0) or 0),
            started_at=float(d.get("started_at", 0.0) or 0.0),
            finished_at=float(d.get("finished_at", 0.0) or 0.0),
            last_tier=str(d.get("last_tier", "")),
        )


class Dispatcher:
    """确定性调度器，非 LLM 驱动。"""

    def __init__(
        self,
        max_workers: int = 3,
        model: str = "",
        probe_timeout: int = 60,
        max_attempts: int = 3,
        timebox_override: int = 0,
        solver_fn: Optional[Callable] = None,
        quiet: bool = False,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_no_output_rounds: int = DEFAULT_MAX_NO_OUTPUT_ROUNDS,
        max_variant_failures: int = DEFAULT_MAX_VARIANT_FAILURES,
        stop_loss: bool = True,
        token_counter: Optional[TokenCounter] = None,
        no_output_round_seconds: int = 60,
    ):
        self.max_workers = max(1, int(max_workers))
        self.model = model
        self.probe_timeout = max(1, int(probe_timeout))
        self.max_attempts = max(1, int(max_attempts))
        self.timebox_override = int(timebox_override)
        self._solver_fn = solver_fn or solver_worker
        self.quiet = quiet
        # 止损治理器（F2-004 / F2-011，步骤 07）
        self.stop_loss = bool(stop_loss)
        self.stopper = Stopper(
            max_tokens=max_tokens,
            max_no_output_rounds=max_no_output_rounds,
            max_variant_failures=max_variant_failures,
        )
        # 无产出的「一轮」= 这么多秒无任何进展（新 Fact 或 solver.log 增长）。
        # 调度器轮询间隔不固定，轮数按停滞时长折算，避免高频轮询误杀活跃 solver。
        self.no_output_round_seconds = max(1, int(no_output_round_seconds))
        self.token_counter = token_counter  # 可注入精确 token 计数器；None 走日志估算
        self.projects: dict[str, Project] = {}
        self._running: dict[str, dict] = {}  # challenge_id → slot
        self._spawns = 0
        # P1-2 / M-3：_spawns / attempts 的读改写发生在 _spawn_candidates
        # 的线程池并发上下文中，+= 非原子——计数器读写统一走此锁。
        self._counters_lock = threading.Lock()

    # ── 项目管理 ────────────────────────────────────────────────────────

    def add_project(self, project: Project) -> None:
        self.projects[project.challenge_id] = project

    # ── 调度决策（确定性，非 LLM）────────────────────────────────────────

    def schedule(self, available: int) -> list[Project]:
        """调度决策：1. 新题优先（score 降序） 2. 无新题 → 收割轮（EV 排序）。"""
        if available <= 0:
            return []
        new = [
            p for p in self.projects.values() if p.status == ChallengeStatus.NEW
        ]
        new.sort(key=lambda p: p.score, reverse=True)
        if new:
            return new[:available]
        return self.harvest_cycle()[:available]

    def harvest_cycle(self) -> list[Project]:
        """收割轮：按 EV 排序，回退已放弃/超时的题（attempts 未达上限的）。

        EV = score * difficulty_factor * (1 - attempts * 0.2)
        """
        abandoned = [
            p for p in self.projects.values()
            if p.status in HARVESTABLE and p.attempts < self.max_attempts
            # 预算耗尽是硬止损：token 估算不随重跑下降，重跑必在首次轮询再撞墙，
            # 只会空耗 attempts 配额，故排除出收割轮
            and "BUDGET_EXCEEDED" not in p.stop_reason
        ]
        for p in abandoned:
            df = DIFFICULTY_FACTORS.get(p.difficulty, 0.5)
            penalty = max(0.2, 1.0 - p.attempts * 0.2)
            p.ev_score = (p.score * df) * penalty
        abandoned.sort(key=lambda p: p.ev_score, reverse=True)
        return abandoned

    # ── 主循环 ──────────────────────────────────────────────────────────

    def run(self, limit: Optional[int] = None) -> dict:
        """执行调度主循环，直到所有题进入终态（SOLVED/INFRA_BLOCKED/放弃到上限）。

        Args:
            limit: 最多启动的 solver 次数（含收割轮重跑）；None 不限

        Returns:
            dict: 汇总报告（totals + 每题状态），供 CLI 输出/持久化
        """
        started = time.time()
        try:
            while True:
                self._reap_finished()
                self._check_timeboxes()
                self._check_stop_loss()

                if not self._running:
                    if limit is not None and self._spawns >= limit:
                        break  # 达到启动上限，不再分配
                    available = self.max_workers - len(self._running)
                    candidates = self.schedule(available)
                    if not candidates:
                        break
                    self._spawn_candidates(candidates, limit)
                    if not self._running:
                        # 全部候选被探针拦下（INFRA_BLOCKED）→ 无题可跑
                        continue
                    continue

                # 等待：到最近的档位边界或任意 solver 结束（≤5s 轮询，保证响应）
                wait = min(slot["timebox"].remaining() for slot in self._running.values())
                wait = max(0.1, min(wait, 5.0))
                sentinels = [slot["process"].sentinel for slot in self._running.values()]
                multiprocessing.connection.wait(sentinels, timeout=wait)
        except BaseException:
            self.stop_all()
            raise

        return {
            "started_at": started,
            "finished_at": time.time(),
            "duration": round(time.time() - started, 1),
            "max_workers": self.max_workers,
            "spawns": self._spawns,
            "escalations": getattr(self, "escalations", 0),
            "projects": [p.to_dict() for p in self.projects.values()],
            "totals": self._totals(),
        }

    def _totals(self) -> dict:
        counts: dict[str, int] = {s.value: 0 for s in ChallengeStatus}
        for p in self.projects.values():
            counts[p.status.value] += 1
        return counts

    # ── 内部：探针 + 分配 ───────────────────────────────────────────────

    def _probe_and_maybe_spawn(self, project: Project,
                               limit: Optional[int] = None) -> bool:
        """探活单个候选；可达则分配 solver，不可达标记 INFRA_BLOCKED。"""
        if project.target_host:
            if not self.quiet:
                print(
                    f"[probe] {project.challenge_id} → "
                    f"{project.target_host}:{project.target_port or ''}"
                )
            result = probe_challenge(
                project.target_host, project.target_port, timeout=self.probe_timeout
            )
            if result == ProbeResult.INFRA_BLOCKED:
                project.status = ChallengeStatus.INFRA_BLOCKED
                project.stop_reason = "probe: infra blocked"
                if not self.quiet:
                    print(f"[probe] {project.challenge_id}: INFRA_BLOCKED — skipped")
                return False
            if result == ProbeResult.UNKNOWN:
                if not self.quiet:
                    print(f"[probe] {project.challenge_id}: UNKNOWN — proceeding anyway")
        return self._spawn(project, limit)

    def _spawn_candidates(self, candidates: list[Project], limit: Optional[int]) -> None:
        """并行探活候选（≤4 并发），可达的分配 solver。"""
        remaining_limit = limit - self._spawns if limit is not None else None
        if remaining_limit is not None and remaining_limit <= 0:
            return
        targets = candidates[:remaining_limit] if remaining_limit is not None else candidates
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=min(PROBE_CONCURRENCY, self.max_workers)) as ex:
            # P1-2 / M-3：limit 透传到 _spawn，名额在锁内原子消耗
            # （remaining_limit 只是启发式预过滤，硬上限由锁内判断保证）
            reachable = list(
                ex.map(
                    functools.partial(self._probe_and_maybe_spawn, limit=limit),
                    targets,
                )
            )
        # ex.map 已按序完成探活+分配；返回 False 的已被标记 INFRA_BLOCKED

    def _escalation_for(self, project: Project) -> tuple[str, str]:
        """P0-3：收割轮 respawn 升级决策。返回 (route, stop_reason 原文)。

        必须在 project.status 被重置为 IN_PROGRESS 之前调用（_spawn 开头、
        注入与预算计算之前），否则 (status, stop_reason) 快照失真。
        """
        sr = project.stop_reason or ""
        key = None
        for k in STOP_REASONS:
            if f"STOPPED: {k}" in sr:
                key = k
                break
        status_name = project.status.value if project.status else ""
        route = ESCALATION_ROUTES.get((status_name, key)) \
            or ESCALATION_ROUTES.get(("*", key), DEFAULT_ROUTE)
        return route, sr

    def _inject_block(self, project: Project, marker: str, block: str) -> None:
        """剥旧注新注入指令块（与 [Specialist Prompt] 同款 marker 模式）。

        从 marker 首次出现处截断，再在末尾追加新块——块不随重试累积。
        """
        base_desc = project.description or ""
        prev = base_desc.find(marker)
        if prev != -1:
            base_desc = base_desc[:prev]
        project.description = base_desc + marker + block

    def _apply_escalation(self, project: Project, route: str, detail: str) -> None:
        """P0-3：按路由执行升级动作。

        v1 边界（契约 4）：只做 prompt 级升级 + timebox 1.5× 调整 + model
        换名；不在调度主循环同步调用 run_boomerang / race 多进程机制。
        """
        if route == "switch_attack_class":
            block = (
                "上一轮因假设空间重复被止损：\n"
                f"{detail}\n"
                "本轮强制换攻击类：\n"
                "- 禁止重复黑板 dead_ends / RELAY.md「已证死路」清单中已证死路的方法；\n"
                "- 先读 RELAY.md 与黑板，选一条本轮未尝试的攻击路线；\n"
                "- 若 10 个工具调用内仍无新 Fact，立即换下一路线，不要死磕。\n"
                "（多方向并行探索可参考 boomerang 模式；多模型竞赛可参考 racer 模式。）"
            )
            self._inject_block(project, "\n\n[Escalation]\n", block)
        elif route == "switch_approach":
            block = (
                "上一轮时间盒自然到期，本轮换路线重试：\n"
                f"{detail}\n"
                "- 上一轮路线未在时限内产出 flag，必须换一条差异化路线；\n"
                "- 禁止重复 RELAY.md「已证死路」与黑板 dead_ends 中已尝试的攻击类；\n"
                "- 开局先规划本轮路线与时间分配，不要重复上一轮的侦察步骤。"
            )
            self._inject_block(project, "\n\n[Escalation]\n", block)
        elif route == "extend_timebox":
            # 1.5 倍延长：只对本次 respawn 生效（_spawn 消费后复位）
            self._timebox_multiplier = 1.5
        elif route == "switch_model":
            try:
                from .racer import resolve_race_models

                models = [
                    m for m in resolve_race_models()
                    if m != (project.model or self.model)
                ]
                if models:
                    project.model = models[0]
                else:
                    route = DEFAULT_ROUTE  # 取不到备选 → 退化为现状重试
            except Exception:  # noqa: BLE001 — racer 不可用 → 退化为现状重试
                route = DEFAULT_ROUTE
        if route != DEFAULT_ROUTE:
            self.escalations = getattr(self, "escalations", 0) + 1
            if not self.quiet:
                print(
                    f"[dispatch] {project.challenge_id}: "
                    f"escalate({detail[:60]}) → {route}"
                )

    def _try_consume_spawn_slot(self, limit: Optional[int]) -> bool:
        """原子消耗一个 spawn 名额（P1-2 / M-3）；达到 limit 返回 False。

        limit 判断与自增在同一临界区内完成；锁粒度只包计数器读写，
        proc.start() / 网络 IO 一律在锁外（性能红线）。
        """
        with self._counters_lock:
            if limit is not None and self._spawns >= limit:
                return False
            self._spawns += 1
            return True

    def _spawn(self, project: Project, limit: Optional[int] = None) -> bool:
        """启动一个 solver 独立进程。返回 False 表示达到 limit 未启动。"""
        # P1-2 / M-3：名额在进程创建前原子消耗——达到 limit 不再 spawn，
        # 对外语义与原 run() 层的 limit 判断一致（此处是最终收口）。
        if not self._try_consume_spawn_slot(limit):
            return False
        work_dir = Path(project.challenge_dir or project.challenge_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        # F4-001：spawn 时即生成 AGENTS.md（solver_worker 内 ensure 幂等兜底）
        try:
            from .agents_md import ensure_agents_md

            ensure_agents_md(work_dir, project)
        except Exception:  # noqa: BLE001 — 生成失败不阻断调度
            pass
        # P0-3：升级决策在状态重置前读取快照（status 此时仍为 ABANDONED/TIMEOUT）
        route, detail = self._escalation_for(project)
        if route != DEFAULT_ROUTE:
            self._apply_escalation(project, route, detail)
        budget = (
            project.timebox_override
            or self.timebox_override
            or difficulty_adjusted_budget(project.difficulty)
        )
        # P0-3：extend_timebox 路由的 1.5× 延长，只对本次 respawn 生效
        multiplier = getattr(self, "_timebox_multiplier", 1.0)
        if multiplier != 1.0:
            budget = int(budget * multiplier)
            self._timebox_multiplier = 1.0
        incremental = not (project.timebox_override or self.timebox_override)
        tb = Timebox(initial_budget=budget, incremental=incremental)
        tb.start()
        queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target=_safe_target,
            args=(self._solver_fn, project, str(work_dir), self.model or project.model, queue),
            name=f"solver-{project.challenge_id}",
        )
        proc.start()
        project.status = ChallengeStatus.IN_PROGRESS
        with self._counters_lock:
            project.attempts += 1
        project.started_at = time.time()
        project.last_tier = tb.tier_label
        # P1-2 / M-3：_spawns 已在 _spawn 入口经 _try_consume_spawn_slot
        # 原子消耗，此处不再自增。
        # 续接注入：RELAY.md 的死路/已达成原语 → 黑板（07 指南集成步骤 1）
        self._inject_relay_into_board(work_dir)
        board = load_blackboard(work_dir / BLACKBOARD_FILENAME)
        self._running[project.challenge_id] = {
            "project": project,
            "process": proc,
            "timebox": tb,
            "queue": queue,
            "work_dir": work_dir,
            # 止损状态（F2-004）：无产出轮数 / 最近一次黑板 Fact 计数
            "no_output_rounds": 0,
            "last_fact_count": (
                len(
                    [
                        f
                        for f in board.facts.values()
                        if f.state in (State.CONFIRMED, State.REFUTED)
                    ]
                )
                if board
                else 0
            ),
            # P0-2 增量扫描状态（H-1）：止损轮询只扫 solver.log 新增字节、
            # 黑板按 mtime 缓存，语义与全量扫描等价（见 _stop_reason_for）
            "scan_offset": 0,     # solver.log 已扫描到的字节 offset
            "scan_tail": "",      # 上次扫描末尾残留（候选跨块时拼接用）
            "board_cache": None,  # ((mtime_ns, size), Board) 缓存对
        }
        if not self.quiet:
            print(
                f"[dispatch] {project.challenge_id}: spawn "
                f"(pid={proc.pid}, tier0={budget}s, workers={len(self._running)}/{self.max_workers})"
            )

    def _inject_relay_into_board(self, work_dir: Path) -> None:
        """续接时把 RELAY.md 的死路/已达成原语注入黑板（07 指南集成步骤 1）。

        存在 RELAY.md（上次时间盒/止损留下）且黑板已持久化时：死路进免疫集，
        已达成原语进 Fact（source=\"relay\"）。使黑板状态与接力块一致，供
        新 solver / 其他 solver 读取，不重复侦察。
        """
        relay_text = read_relay_file(work_dir)
        board_path = work_dir / BLACKBOARD_FILENAME
        if not relay_text or not board_path.is_file():
            return
        board = load_blackboard(board_path)
        if board is None:
            return
        relay = parse_relay(relay_text)
        for d in relay["dead_ends"]:
            board.mark_dead_end(d)
        # 原语按 content 幂等注入：接力块在多次重跑间反复存在，按 id 去重无效
        # （Fact 每次 new uuid）；运行时元信息行（"solver ran ..."）不是原语，不注入。
        existing = {f.content for f in board.get_facts()}
        for p in relay["achieved_primitives"]:
            # P1-3 / A-4：回注通道与 _write_relay 用同一谓词口径，防滚雪球
            if is_relay_meta_text(p) or p in existing:
                continue
            try:
                board.add_fact(Fact(content=p, source="relay"))
                existing.add(p)
            except ValueError:
                pass  # append-only：重复 id 忽略
        save_blackboard(board, board_path)

    # ── 内部：收割与中断 ────────────────────────────────────────────────

    def _reap_finished(self) -> None:
        """收割已结束的 solver 进程，判定 SOLVED / ABANDONED。"""
        for cid, slot in list(self._running.items()):
            if not slot["process"].is_alive():
                self._reap(cid, slot)

    def _reap(self, cid: str, slot: dict) -> None:
        project: Project = slot["project"]
        proc: multiprocessing.Process = slot["process"]
        queue = slot["queue"]
        work_dir: Path = slot["work_dir"]
        self._running.pop(cid, None)
        proc.join(timeout=3)

        result: Optional[SolverResult] = None
        try:
            if not queue.empty():
                result = queue.get(timeout=1)
        except Exception:  # noqa: BLE001
            result = None

        project.finished_at = time.time()
        flag = ""
        gate_note = ""
        declared = (result.flag if result else "") or ""
        if declared:
            # 声明式 FLAG 文件内容同样要过三重校验门：agent 可能绕过
            # submit_flag 直接写 FLAG 文件，占位/畸形内容不得判 SOLVED
            gate = verify_flag(declared, evidence="", require_grounding=False)
            if gate is VerificationResult.CONFIRMED:
                flag = declared
            else:
                gate_note = f"flag file rejected by gate: {gate.value}"
        if not flag:
            flag = scan_log_for_flag(work_dir)  # 兜底：扫描 solver.log（走三重校验门）
        if flag:
            project.status = ChallengeStatus.SOLVED
            project.flag = flag
            try:
                (work_dir / "FLAG").write_text(flag + "\n", encoding="utf-8")
            except OSError:
                pass
        else:
            project.status = ChallengeStatus.ABANDONED
            project.stop_reason = (
                (result.error if result and result.error else "")
                or f"solver exit={result.exit_code if result else 'crash'}"
            )
            if gate_note:
                project.stop_reason = f"{gate_note}; {project.stop_reason}"
        if not self.quiet:
            detail = f" flag={flag}" if flag else f" reason={project.stop_reason}"
            print(f"[dispatch] {project.challenge_id}: {project.status.value}{detail}")

        # 经验落库（F3-003/F3-004）：SOLVED / ABANDONED 都落，best-effort
        board = load_blackboard(work_dir / BLACKBOARD_FILENAME)
        fact_contents = (
            [
                f.content[:120]
                for f in board.get_facts()
                if f.state in (State.CONFIRMED, State.REFUTED)
            ][:20]
            if board
            else []
        )
        try:
            from .experiential_learning import record_solve_outcome
            record_solve_outcome(
                challenge_id=project.challenge_id,
                category=project.category or "misc",
                success=(project.status is ChallengeStatus.SOLVED),
                key_commands=fact_contents,
                flag=project.flag,
            )
        except Exception:  # noqa: BLE001 — 经验落库失败不影响调度
            pass

    def _check_timeboxes(self) -> None:
        """检查运行中的时间盒：档位升级（继续）或最终超时（中断+接力块）。"""
        for cid, slot in list(self._running.items()):
            tb: Timebox = slot["timebox"]
            if tb.check():
                self._interrupt(cid, slot)

    # ── 内部：止损治理（F2-004 / F2-011，步骤 07）──────────────────────────

    def _check_stop_loss(self) -> None:
        """对每个运行中的 solver 执行 4 维止损检查；命中即终止并写接力块。

        维度（见 stopper.Stopper）：预算超限 / 无产出 / 不可达目标 /
        假设空间重复；多 flag 链临门不弃放大预算。无黑板文件时无产出与
        变体维度无法判定（跳过，不误杀未启用黑板的流程）。
        """
        if not self.stop_loss:
            return
        for cid, slot in list(self._running.items()):
            reason = self._stop_reason_for(slot)
            if reason:
                self._interrupt_stopped(cid, slot, reason)

    def _incremental_flag_scan(self, slot: dict, work_dir: Path) -> bool:
        """只扫 solver.log 新增字节（P0-2 / H-1）；返回本轮是否检出过三门 flag。

        语义等价于 ``scan_log_for_flag(work_dir)`` 的布尔结果，成本 O(增量)。
        日志被截断重写（新尝试 ``open(..., "w")``）时 size < offset，自动
        重置 offset 从头扫。``scan_tail`` 保留末尾 1024 字符做跨块拼接
        （候选正则上限 256 内容字符 + 前缀，余量充足）。
        """
        log_file = work_dir / SOLVER_LOG
        try:
            size = log_file.stat().st_size if log_file.is_file() else 0
        except OSError:
            return False
        offset = slot.get("scan_offset", 0)
        if size < offset:  # 截断重写 → 从头扫
            offset = 0
            slot["scan_offset"] = 0
            slot["scan_tail"] = ""
        if size == offset:
            return False
        try:
            with open(log_file, "rb") as f:
                f.seek(offset)
                chunk = f.read()
        except OSError:
            return False
        slot["scan_offset"] = size
        text = slot.get("scan_tail", "") + chunk.decode("utf-8", errors="replace")
        slot["scan_tail"] = text[-1024:]
        return check_output_for_flag(text) is not None

    def _cached_board(self, slot: dict, work_dir: Path):
        """mtime 缓存的黑板加载（P0-2 / H-1）：未变复用对象，变了才重载。

        缓存 key 为 (mtime_ns, size)，黑板写入是 tmp+replace 原子写，
        落盘必引起 mtime/size 变化，不会读到旧数据。文件缺失返回 None
        （与 load_blackboard 直调语义一致）。
        """
        board_path = work_dir / BLACKBOARD_FILENAME
        try:
            st = board_path.stat()
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            return None
        cached = slot.get("board_cache")
        if cached is not None and cached[0] == key:
            return cached[1]
        board = load_blackboard(board_path)
        slot["board_cache"] = (key, board)
        return board

    def _budget_tokens(self, work_dir: Path, token_counter) -> int:
        """运行中预算判定值（P1-1 / H-3）。

        = usage.json（已完成尝试累计，可能缺失）+ solver.log 估算（当前
        尝试）。两口径相加而非互斥取一：usage.json 只在尝试结束后写，
        运行中只有 log 估算覆盖当前尝试，相加才是总消耗。尝试结束瞬间
        可能双计一次（窗口 <1s），只会提前触发预算止损（安全侧），不
        去重——任何情况下判定值不低于修复前。注入计数器仍最高优先。
        """
        if token_counter is not None:
            return int(token_counter(work_dir) or 0)
        # usage.json 精确口径依赖 stopper.usage_tokens（旧版 stopper 无此
        # 函数）：缺失时退化为纯 log 估算（修复前行为，仍满足"只早不晚"）。
        try:
            from .stopper import usage_tokens
        except ImportError:  # pragma: no cover - 旧版 stopper 兼容
            usage_tokens = None
        exact = usage_tokens(work_dir) if usage_tokens is not None else None
        est = estimate_tokens_from_log(work_dir)
        return (exact or 0) + est

    def _stop_reason_for(self, slot: dict) -> Optional[str]:
        """计算单个 solver 的止损原因（无命中返回 None）。"""
        project: Project = slot["project"]
        work_dir: Path = slot["work_dir"]

        # 维度 1 — 预算超限：token 计数。优先级：注入计数器 > （usage.json
        # 已完成尝试累计 + solver.log 当前尝试估算）相加（P1-1 / H-3，见
        # _budget_tokens）。solver.log 每次尝试被截断重写，只反映当前尝试。
        tokens = self._budget_tokens(work_dir, self.token_counter)

        # 维度 2/4 — 无产出 / 假设空间重复：需要黑板数据源
        # （P0-2：mtime 缓存，未变时复用上次反序列化对象，语义等同重载）
        board = self._cached_board(slot, work_dir)
        if board is None:
            rounds_without_fact = 0
            variant_failures = 0
        else:
            fact_count = len(
                [f for f in board.facts.values() if f.state in (State.CONFIRMED, State.REFUTED)]
            )
            try:
                log_size = (
                    (work_dir / SOLVER_LOG).stat().st_size
                    if (work_dir / SOLVER_LOG).is_file()
                    else 0
                )
            except OSError:
                log_size = 0
            # 进展 = 新 Fact 或 solver.log 增长/重写（新尝试）。轮数按停滞时长折算
            # （1 轮 = no_output_round_seconds 秒无进展），与轮询频率解耦，避免误杀。
            progressed = (
                fact_count > slot.get("last_fact_count", 0)
                or log_size != slot.get("last_log_size", -1)
            )
            now = time.time()
            if progressed:
                slot["last_fact_count"] = fact_count
                slot["last_log_size"] = log_size
                slot["last_progress_time"] = now
                slot["no_output_rounds"] = 0
            else:
                last_progress = slot.get("last_progress_time") or now
                slot["no_output_rounds"] = int(
                    (now - last_progress) // self.no_output_round_seconds
                )
            rounds_without_fact = slot["no_output_rounds"]
            variant_failures = count_variant_failures(board)

        # 临门不弃（F2-011）：FLAG 文件内容过校验门，或 solver.log 检出 flag。
        # 占位/畸形 FLAG 不算「已拿到 flag」（与 _reap 的声明式提交口径一致）。
        declared = read_flag_file(work_dir)
        if declared and verify_flag(
            declared, evidence="", require_grounding=False
        ) is not VerificationResult.CONFIRMED:
            declared = ""
        # P0-2：日志改增量扫描（offset + tail 拼接），布尔语义与全量一致；
        # FLAG 文件极小且低频写，保留全量读取。
        has_partial_flag = bool(declared) or self._incremental_flag_scan(slot, work_dir)

        return self.stopper.check(
            project_tokens=tokens,
            rounds_without_new_fact=rounds_without_fact,
            variant_failures=variant_failures,
            is_infra_blocked=project.status == ChallengeStatus.INFRA_BLOCKED,
            has_partial_flag=has_partial_flag,
        )

    def _interrupt_stopped(self, cid: str, slot: dict, reason: str) -> None:
        """止损命中：终止 solver 进程，标记 ABANDONED（可收割轮换方向重试），写接力块。"""
        project: Project = slot["project"]
        proc: multiprocessing.Process = slot["process"]
        tb: Timebox = slot["timebox"]
        work_dir: Path = slot["work_dir"]
        self._running.pop(cid, None)

        proc.terminate()
        try:
            proc.join(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2)

        project.finished_at = time.time()
        project.status = ChallengeStatus.ABANDONED
        project.last_tier = tb.tier_label
        project.stop_reason = (
            f"STOPPED: {reason} ({self.stopper.describe(reason)}) "
            f"after {int(tb.elapsed)}s at tier '{tb.tier_label}'"
        )
        self._write_relay(project, tb, work_dir, reason=reason)
        if not self.quiet:
            print(
                f"[dispatch] {project.challenge_id}: STOPPED ({reason}) — RELAY.md written"
            )

    def _interrupt(self, cid: str, slot: dict) -> None:
        """时间盒最终超时：终止 solver 进程，标记 TIMEOUT，输出接力块。"""
        project: Project = slot["project"]
        proc: multiprocessing.Process = slot["process"]
        tb: Timebox = slot["timebox"]
        work_dir: Path = slot["work_dir"]
        self._running.pop(cid, None)

        proc.terminate()
        try:
            proc.join(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2)

        project.finished_at = time.time()
        project.status = ChallengeStatus.TIMEOUT
        project.last_tier = tb.tier_label
        project.stop_reason = (
            f"timebox expired at tier '{tb.tier_label}' after {int(tb.elapsed)}s "
            f"(budget {tb.current_budget}s)"
        )
        self._write_relay(project, tb, work_dir)
        if not self.quiet:
            print(
                f"[dispatch] {project.challenge_id}: TIMEOUT "
                f"(tier={tb.tier_label}, elapsed={int(tb.elapsed)}s) — RELAY.md written"
            )

    def _write_relay(self, project: Project, tb: Timebox, work_dir: Path,
                     reason: Optional[str] = None) -> None:
        """把当前状态沉淀为接力块（三段式续接契约）。

        时间盒到期（reason=None）或止损命中（reason 为 STOP_REASONS 键）时调用。
        若黑板已持久化，把 facts 并入「已达成原语」、dead_ends 并入「已证死路」，
        保证续接时从「下一步」开始、不重复侦察（07 指南 7.2）。
        """
        achieved = [
            f"solver ran {int(tb.elapsed)}s at tier '{tb.tier_label}' "
            f"(budget {tb.current_budget}s); progress log: {work_dir / 'solver.log'}"
        ]
        dead_ends: list[str] = []
        board = load_blackboard(work_dir / BLACKBOARD_FILENAME)
        if board:
            # P1-3 / A-4：过滤 source=="solver" 与 "solver attempt " 元 Fact，
            # 防止运行时垃圾随重试线性膨胀进 RELAY 与回注 prompt
            achieved.extend(
                f.content for f in board.get_facts() if relay_worthy_fact(f)
            )
            dead_ends = sorted(board.dead_ends)

        hint = "read solver.log for progress and continue from where it stopped"
        if reason:
            hint = f"stop-loss '{reason}' ({self.stopper.describe(reason)}); {hint}"
        relay_text = build_relay(
            achieved_primitives=achieved,
            dead_ends=dead_ends,
            next_steps=[
                f"RESUME {project.challenge_id}: re-run solver with a fresh agent; {hint}"
            ],
        )
        write_relay_file(work_dir, relay_text)

    # ── 停止 ────────────────────────────────────────────────────────────

    def stop_all(self) -> None:
        """终止所有运行中的 solver（Ctrl-C / 异常时清理）。"""
        for cid, slot in list(self._running.items()):
            proc = slot["process"]
            try:
                proc.terminate()
                proc.join(timeout=3)
            except Exception:  # noqa: BLE001
                pass
            if proc.is_alive():
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._running.clear()

    # ── 状态持久化（供后续 status 命令复用）─────────────────────────────

    def save_state(self, summary: dict, path: str | Path) -> None:
        # P1-3：原子写，中断不留截断 JSON
        atomic_write_text(Path(path), json.dumps(summary, indent=2, ensure_ascii=False))


__all__ = [
    "ChallengeStatus",
    "Project",
    "Dispatcher",
    "HARVESTABLE",
    "DIFFICULTY_FACTORS",
]
