"""多模型竞速 + Coordinator LLM（F3-005 / F3-006）。

对应实施指南 09-P3-高级功能.md §9.1/§9.2。同一题 N 个 solver（不同模型）
并行跑，第一个找到 flag 的停止其他（指南验收第 1 条）。

与指南的偏差（以真实环境为准）：
1. 指南 ``RACE_MODELS`` 硬编码 3 个模型名（deepseek-v4-flash 等）。本机
   config 未必配置这些模型，硬编码会以空凭据/未知模型打 API 导致 400。
   默认模型列表改为：显式传入 > config ``ctf.race_models`` 列表 >
   配置默认模型（单模型退化为一次普通求解，不虚构模型 ID）。
2. 每个 racer 独立子目录 ``race-<i>-<model-slug>/``：solver_worker 写
   ``solver.log``（"w" 模式）与 FLAG 文件，同目录并行会互相覆盖证据。
   胜者的 FLAG/黑板合并回父工作目录，败者的死路并入父黑板免疫集。
3. 「其他读取后自行终止」依赖 solver 运行时轮询共享状态——为不侵入
   solver_worker（Phase 2 已验证代码），终止由父进程实现：哨兵轮询 +
   ``terminate()``（与 Dispatcher 时间盒中断同一模式）。

Coordinator LLM（F3-006）：读黑板状态生成方向建议，周期性把建议写入
黑板 Hint。LLM 调用可注入（测试离线）；默认走
``agent.auxiliary_client.call_llm``（低成本单轮调用），任何异常降级为
基于黑板状态的启发式建议，不阻断竞速。
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
from .solver import FLAG_FILENAME, SolverResult, resolve_default_model, solver_worker
from .timebox import Timebox, difficulty_adjusted_budget
from .verify import VerificationResult, verify_flag

_SAFE_MP_CONTEXT = multiprocessing.get_context(
    "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
)

# 竞速默认轮询间隔（秒）：与 Dispatcher 相同量级，保证响应性
_POLL_INTERVAL = 1.0

# Coordinator 默认调用间隔（秒）：指南「定期调用（如每 3 轮）」的秒化近似
COORDINATOR_INTERVAL = 120.0


@dataclass
class RacerResult:
    """单个 racer（模型）的结果。"""

    model: str
    index: int = 0
    pid: int = 0
    ok: bool = False
    flag: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "index": self.index,
            "pid": self.pid,
            "ok": self.ok,
            "flag": self.flag,
            "error": self.error,
        }


@dataclass
class RaceResult:
    """竞速汇总结果。"""

    flag: str = ""
    winner_model: str = ""
    results: list = field(default_factory=list)   # list[RacerResult]
    advice: list = field(default_factory=list)    # Coordinator 建议记录

    @property
    def solved(self) -> bool:
        return bool(self.flag)

    def to_dict(self) -> dict:
        return {
            "flag": self.flag,
            "winner_model": self.winner_model,
            "solved": self.solved,
            "racers": [r.to_dict() for r in self.results],
            "coordinator_advice": list(self.advice),
        }


def resolve_race_models(models=None) -> list[str]:
    """解析竞速模型列表（显式 > config ``ctf.race_models`` > 默认模型）。

    Args:
        models: 显式模型列表（或逗号分隔字符串）

    Returns:
        list[str]: 去重非空的模型列表（直接传给 run_agent 的 model 参数）

    Raises:
        ValueError: 解析不出任何可用模型
    """
    if isinstance(models, str):
        models = [m.strip() for m in models.split(",") if m.strip()]
    if models:
        resolved = [str(m) for m in models]
    else:
        resolved = []
        try:
            from fulilian_cli.config import load_config

            cfg_models = ((load_config() or {}).get("ctf") or {}).get(
                "race_models"
            )
            if isinstance(cfg_models, str):
                cfg_models = [m.strip() for m in cfg_models.split(",") if m.strip()]
            resolved = [str(m) for m in (cfg_models or []) if str(m).strip()]
        except Exception:  # noqa: BLE001 — 配置读取失败回退默认模型
            resolved = []
    if not resolved:
        default_model = resolve_default_model()
        if default_model:
            resolved = [default_model]
    if not resolved:
        raise ValueError(
            "race: no models available — pass models, set ctf.race_models in "
            "config, or configure model.default"
        )
    # 去重保序
    seen: set[str] = set()
    unique = []
    for m in resolved:
        if m and m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def model_slug(model: str) -> str:
    """模型名 → 目录安全 slug。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "model"


# ── Coordinator LLM（F3-006）──────────────────────────────────────────────


def _default_llm(prompt: str) -> str:
    """默认 LLM 封装：低成本单轮调用（auxiliary_client.call_llm）。"""
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning
    from fulilian_cli.models import parse_model_input

    raw = resolve_default_model()
    provider, model = parse_model_input(raw, "") if raw else ("", "")
    kwargs: dict = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
    }
    if provider:
        kwargs["provider"] = provider
    if model:
        kwargs["model"] = model
    resp = call_llm(**kwargs)
    return extract_content_or_reasoning(resp).strip()


def _heuristic_advice(blackboard_data: dict) -> str:
    """离线启发式建议（LLM 不可用时的降级路径）。"""
    intents = blackboard_data.get("intents") or []
    dead = blackboard_data.get("dead_ends") or []
    facts = blackboard_data.get("facts") or {}
    lines = []
    open_intents = [
        (i.get("goal") or i.get("approach", ""))
        for i in intents
        if isinstance(i, dict) and i.get("state") in (None, "", "open")
    ]
    if open_intents:
        lines.append(f"继续推进待探索方向：{'；'.join(x for x in open_intents if x)[:200]}")
    if dead:
        lines.append(f"避开已证死路（{len(dead)} 条）：{dead[0]}")
    if facts:
        lines.append(f"已有 {len(facts)} 条确认发现，围绕它们收敛攻击面")
    if not lines:
        lines.append("黑板为空：先做基础侦察（端口/文件类型/编码特征）")
    return "\n".join(f"- {ln}" for ln in lines)


def json_safe(obj, limit: int = 1200) -> str:
    """黑板数据 → 短 JSON 字符串（prompt 用）。"""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(obj)
    return text if len(text) <= limit else text[:limit] + "…"


def coordinator_advice(
    blackboard_data: dict, llm_fn: Optional[Callable[[str], str]] = None
) -> str:
    """根据黑板状态生成下一步方向建议（F3-006）。

    Args:
        blackboard_data: 黑板 dict（Blackboard.to_dict() 的输出）
        llm_fn: 可注入 LLM（prompt → 文本）；None 走默认低成本调用

    Returns:
        str: 建议文本（中文，逐条）；LLM 失败降级为启发式建议
    """
    facts = blackboard_data.get("facts") or {}
    intents = blackboard_data.get("intents") or []
    dead_ends = blackboard_data.get("dead_ends") or []

    prompt = (
        "你是 CTF 解题协调器。根据以下黑板状态，给出 3 条下一步方向建议"
        "（中文，每条一行，以 - 开头）：\n\n"
        f"已确认的发现：{json_safe(facts)}\n"
        f"待探索方向：{json_safe(intents)}\n"
        f"已证死路：{json_safe(dead_ends)}\n"
    )
    fn = llm_fn or _default_llm
    try:
        advice = fn(prompt)
        if advice and advice.strip():
            return advice.strip()
    except Exception:  # noqa: BLE001 — LLM 失败必须降级，不阻断竞速
        pass
    return _heuristic_advice(blackboard_data)


def coordinator_analyze_traces(
    traces: list,
    blackboard: Optional[Blackboard] = None,
    enable_llm: bool = True,
    llm_fn: Optional[Callable[[str], str]] = None,
) -> str:
    """分析多个 solver 的轨迹，生成汇总分析与方向建议（F4-007）。

    Args:
        traces: list[SolverTrace] — 各 solver 的轨迹
        blackboard: 可选的 Blackboard（提供线索和排他路径）
        enable_llm: 是否尝试 LLM 分析（False 直接走启发式）
        llm_fn: 可注入 LLM（prompt → 文本）；None 走默认低成本调用

    Returns:
        str: 分析报告
    """
    lines: list[str] = []
    # 1. 汇总每个 solver 的进展
    lines.append("## Solver Trace Analysis")
    lines.append("")
    lines.append(f"### Overview ({len(traces)} solver(s))")
    for t in traces:
        solver_id = getattr(t, "solver_id", "?")
        model = getattr(t, "model", "?")
        entries = getattr(t, "entries", [])
        flag_found = getattr(t, "flag_found", False)
        summary = {
            "solver_id": solver_id,
            "model": model,
            "entries": len(entries),
            "flag_found": flag_found,
        }
        lines.append(f"- {solver_id} ({model}): {len(entries)} entries, {'✅ flag' if flag_found else '❌ no flag'}")
        # 每个 solver 的失败分类
        if hasattr(t, "classify_failures"):
            failures = t.classify_failures()
            if failures["error_entries"]:
                lines.append(f"  - Errors: {failures['error_entries']} ({', '.join(failures['error_types'])})")
    lines.append("")

    # 2. 提取黑板线索和排他路径
    if blackboard:
        facts = blackboard.get_facts()
        lines.append(f"### Blackboard State")
        lines.append(f"- Facts: {len(facts)}")
        if facts:
            for f in facts[:10]:
                lines.append(f"  - {f.content[:100]}")
        exclusions = blackboard.get_exclusions()
        lines.append(f"- Exclusions: {len(exclusions)}")
        if exclusions:
            for e in sorted(exclusions)[:10]:
                lines.append(f"  - {e}")
        lines.append("")

    # 3. 对比分析互补路径
    if len(traces) >= 2:
        lines.append("### Cross-Solver Comparison")
        # 找不同 solver 使用的不同工具/动作
        all_actions: dict[str, set[str]] = {}
        for t in traces:
            sid = str(getattr(t, "solver_id", "?"))
            actions = set()
            for e in getattr(t, "entries", []):
                if e.action:
                    actions.add(e.action)
            all_actions[sid] = actions
        if len(all_actions) >= 2:
            solver_ids = list(all_actions.keys())
            unique_actions = all_actions[solver_ids[0]] ^ all_actions[solver_ids[1]]
            if unique_actions:
                lines.append(f"Complementary actions: {', '.join(sorted(unique_actions))}")
            else:
                lines.append("All solvers used similar actions")
        lines.append("")

    # 4. LLM 分析（可选）
    if enable_llm:
        prompt = (
            "You are a CTF coordinator analyzing solver traces. "
            "Based on the following trace summary, provide:\n"
            "1. What each solver tried and why\n"
            "2. Complementary approaches worth combining\n"
            "3. 2-3 specific next steps\n\n"
        )
        for t in traces:
            if hasattr(t, "summarize"):
                trace_summary = t.summarize()
                prompt += trace_summary + "\n\n"
        if blackboard:
            prompt += f"Blackboard: {len(blackboard.get_facts())} facts, {len(blackboard.get_exclusions())} exclusions\n"
        fn = llm_fn or _default_llm
        try:
            analysis = fn(prompt)
            if analysis and analysis.strip():
                lines.append("### LLM Analysis")
                lines.append("")
                lines.append(analysis.strip())
                return "\n".join(lines)
        except Exception:  # noqa: BLE001 — LLM 失败降级
            pass

    # 5. 启发式降级
    if blackboard:
        heuristic = _heuristic_advice(blackboard.to_dict())
        lines.append("### Heuristic Advice")
        lines.append("")
        lines.append(heuristic)
    else:
        lines.append("### Summary")
        lines.append("")
        lines.append("No blackboard available. Review individual solver traces for details.")

    return "\n".join(lines)


class CoordinatorLoop:
    """Coordinator 周期循环：读黑板 → 生成建议 → 写回黑板 Hint。

    后台线程运行；``stop()`` 结束。建议同时记录到 ``advices`` 供竞速
    汇总输出。黑板文件不存在时跳过本轮（竞速子目录各自有黑板，父目录
    的黑板是合并视图——建议写到父黑板即可全局可见）。
    """

    def __init__(
        self,
        board_path: str | Path,
        interval: float = COORDINATOR_INTERVAL,
        llm_fn: Optional[Callable[[str], str]] = None,
        on_advice: Optional[Callable[[str], None]] = None,
    ):
        self.board_path = Path(board_path)
        self.interval = max(5.0, float(interval))
        self.llm_fn = llm_fn
        self.on_advice = on_advice
        self.advices: list[str] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=_run_coordinator_loop, args=(self,), daemon=True, name="coordinator"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def tick_once(self) -> Optional[str]:
        """执行一轮建议生成（供测试与手动触发）。"""
        board = load_blackboard(self.board_path)
        if board is None:
            return None
        advice = coordinator_advice(board.to_dict(), llm_fn=self.llm_fn)
        board.add_hint(Hint(content=advice, source="coordinator"))
        save_blackboard(board, self.board_path)
        self.advices.append(advice)
        if self.on_advice:
            try:
                self.on_advice(advice)
            except Exception:  # noqa: BLE001
                pass
        return advice


def _run_coordinator_loop(loop: "CoordinatorLoop") -> None:
    while not loop._stop.wait(loop.interval):
        try:
            loop.tick_once()
        except Exception:  # noqa: BLE001 — 建议失败不阻断竞速
            continue


# ── 竞速主流程（F3-005）───────────────────────────────────────────────────


def _race_target(solver_fn, project, work_dir: str, model: str, queue) -> None:
    """racer 进程入口：异常安全包装（崩溃不影响其他 racer）。"""
    try:
        solver_fn(project, work_dir, model, queue)
    except BaseException as e:  # noqa: BLE001 — 进程隔离
        try:
            queue.put(SolverResult(ok=False, exit_code=1, error=f"{type(e).__name__}: {e}"))
        except Exception:  # noqa: BLE001
            pass


def _reap_racer(queue) -> Optional[SolverResult]:
    try:
        if not queue.empty():
            return queue.get(timeout=1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _stop_process(proc: multiprocessing.Process) -> None:
    try:
        proc.terminate()
        proc.join(timeout=5)
    except Exception:  # noqa: BLE001
        pass
    if proc.is_alive():
        try:
            proc.kill()
            proc.join(timeout=2)
        except Exception:  # noqa: BLE001
            pass


def _confirm_flag(work_dir: Path) -> str:
    """racer 目录内的 flag 判定：FLAG 文件过校验门，再兜底扫 solver.log。"""
    from .solver import scan_log_for_flag

    declared = ""
    flag_file = work_dir / FLAG_FILENAME
    if flag_file.is_file():
        declared = flag_file.read_text(encoding="utf-8", errors="replace").strip()
    if declared and verify_flag(
        declared, evidence="", require_grounding=False
    ) is VerificationResult.CONFIRMED:
        return declared
    return scan_log_for_flag(work_dir)


def _merge_board_into_parent(
    child_dir: Path, parent_board: Blackboard, facts_only: bool = False
) -> None:
    """把子目录黑板的死路（及可选 Fact）并入父黑板（stigmergy 合并）。"""
    board = load_blackboard(child_dir / BLACKBOARD_FILENAME)
    if board is None:
        return
    for d in board.dead_ends:
        parent_board.mark_dead_end(d)
    if facts_only:
        return
    existing = {f.content for f in parent_board.get_facts()}
    for f in board.get_facts():
        if f.content.startswith("solver ") or f.content in existing:
            continue
        try:
            parent_board.add_fact(Fact(content=f.content, source=f.source or "race"))
            existing.add(f.content)
        except ValueError:
            pass  # append-only：重复内容忽略


def run_race(
    project,
    models: Optional[list] = None,
    race_dir: Optional[str | Path] = None,
    timeout: int = 0,
    solver_fn: Optional[Callable] = None,
    coordinator: bool = True,
    coordinator_interval: float = COORDINATOR_INTERVAL,
    quiet: bool = False,
) -> RaceResult:
    """启动多模型竞速（F3-005）。

    Args:
        project: Project 对象（fulilian_ctf.dispatcher.Project）
        models: 竞速模型列表；None 走 resolve_race_models 默认解析
        race_dir: 竞速工作目录（默认 project.challenge_dir）
        timeout: 全局时间盒（秒）；0 用难度自适应预算
        solver_fn: 可注入求解实现（测试用）；None 走真实 solver_worker
        coordinator: 是否启用 Coordinator LLM 建议循环（F3-006）
        coordinator_interval: Coordinator 调用间隔（秒）
        quiet: 静默输出

    Returns:
        RaceResult: 胜者 flag + 每个 racer 的结果
    """
    solver_fn = solver_fn or solver_worker
    mp_context = _SAFE_MP_CONTEXT
    models = resolve_race_models(models)
    base_dir = Path(race_dir or project.challenge_dir or project.challenge_id)
    base_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    budget = timeout or difficulty_adjusted_budget(project.difficulty)
    timebox = Timebox(initial_budget=budget, incremental=False)
    timebox.start()

    coordinator_loop: Optional[CoordinatorLoop] = None
    parent_board_path = base_dir / BLACKBOARD_FILENAME
    if coordinator:
        coordinator_loop = CoordinatorLoop(parent_board_path, interval=coordinator_interval)
        coordinator_loop.start()

    slots: list[dict] = []
    try:
        for i, model in enumerate(models):
            racer_dir = base_dir / f"race-{i}-{model_slug(model)}"
            racer_dir.mkdir(parents=True, exist_ok=True)
            racer_project = copy.deepcopy(project)
            racer_project.model = model
            queue = mp_context.Queue()
            proc = mp_context.Process(
                target=_race_target,
                args=(solver_fn, racer_project, str(racer_dir), model, queue),
                name=f"race-{i}-{model_slug(model)}",
            )
            proc.start()
            slots.append(
                {
                    "model": model,
                    "index": i,
                    "dir": racer_dir,
                    "proc": proc,
                    "queue": queue,
                    "result": RacerResult(model=model, index=i, pid=proc.pid),
                }
            )
            if not quiet:
                print(
                    f"[race] {project.challenge_id}: racer#{i} model={model} pid={proc.pid}",
                    flush=True,
                )

        winner: Optional[dict] = None
        while True:
            # 哨兵轮询：任意 racer 结束 → 收割判定
            for s in slots:
                if not s["proc"].is_alive() and not s.get("reaped"):
                    s["reaped"] = True
                    s["proc"].join(timeout=3)
                    res = _reap_racer(s["queue"])
                    rr: RacerResult = s["result"]
                    if res:
                        rr.ok = res.ok
                        rr.error = res.error
                    rr.flag = _confirm_flag(s["dir"])
                    if not quiet:
                        print(
                            f"[race] {project.challenge_id}: racer#{s['index']} "
                            f"({s['model']}) finished flag={'yes' if rr.flag else 'no'}"
                            + (f" err={rr.error}" if rr.error else ""),
                            flush=True,
                        )
                    if rr.flag and winner is None:
                        winner = s
            if winner is not None:
                break  # 第一个找到 flag → 停止其他（finally 统一终止）
            if all(s.get("reaped") for s in slots):
                break  # 全部结束且无人解出
            if timebox.check():
                if not quiet:
                    print(f"[race] {project.challenge_id}: timebox expired", flush=True)
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
        # 终止所有仍在运行的 racer（含已解出后的其余 racer）
        for s in slots:
            if s["proc"].is_alive():
                _stop_process(s["proc"])
        if coordinator_loop is not None:
            coordinator_loop.stop()

    # 汇总：胜者 flag 回写父工作目录，黑板合并（胜者 facts + 全部死路）
    result = RaceResult(advice=list(coordinator_loop.advices) if coordinator_loop else [])
    parent_board = load_blackboard(parent_board_path) or Blackboard(
        challenge_id=project.challenge_id
    )
    for s in slots:
        rr = s["result"]
        _merge_board_into_parent(
            s["dir"], parent_board, facts_only=(winner is not None and s is not winner)
        )
        result.results.append(rr)
        if winner is not None and s is winner:
            result.flag = rr.flag
            result.winner_model = s["model"]
    if result.flag:
        parent_board.add_fact(
            Fact(content=f"race won by model {result.winner_model} with flag", source="racer")
        )
        try:
            (base_dir / FLAG_FILENAME).write_text(result.flag + "\n", encoding="utf-8")
        except OSError:
            pass
    save_blackboard(parent_board, parent_board_path)
    result.results.sort(key=lambda r: r.index)
    if not quiet:
        if result.flag:
            print(
                f"[race] {project.challenge_id}: SOLVED by {result.winner_model} — {result.flag}",
                flush=True,
            )
        else:
            print(
                f"[race] {project.challenge_id}: no flag "
                f"({round(time.time() - started, 1)}s, {len(models)} racers)",
                flush=True,
            )
    return result


def run_race_for_challenge(challenge_id: str, models: Optional[list] = None, **kwargs) -> RaceResult:
    """便捷入口：challenge_id（目录或注册表条目）→ Project → run_race。"""
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
    return run_race(project, models=models, **kwargs)


__all__ = [
    "COORDINATOR_INTERVAL",
    "CoordinatorLoop",
    "RaceResult",
    "RacerResult",
    "coordinator_advice",
    "coordinator_analyze_traces",
    "model_slug",
    "resolve_race_models",
    "run_race",
    "run_race_for_challenge",
]
