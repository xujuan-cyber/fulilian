"""单题 Solver 进程（F2-001 的 worker 侧）。

每个 solver 是一个独立进程（进程隔离：崩溃不影响其他），复用 Hermes 的
``run_agent.main(mode="ctf")`` 核心。通过 multiprocessing.Queue 上报结果。

流程：
1. 读取 RELAY.md（若存在）→ 从「下一步」续接，不重复侦察
2. 构造 CTF 查询（含挑战元信息 + 声明式提交指令）
3. chdir 到挑战工作目录，调用 run_agent 核心（stdout/stderr 重定向到 solver.log
   作为证据来源，供调度器 check_output_for_flag 扫描）
4. 读取 FLAG 文件（声明式提交），连同结果经 Queue 上报
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .relay import read_relay_file
from .sandbox import ENV_SANDBOX_MODE, SandboxMode
from .verify import check_output_for_flag

FLAG_FILENAME = "FLAG"
SOLVER_LOG = "solver.log"


@dataclass
class SolverResult:
    """solver 进程的最终结果。"""

    ok: bool
    exit_code: int = 0
    error: str = ""
    flag: str = ""


def build_solve_query(project, relay_text: Optional[str] = None) -> str:
    """构造发给 solver 的 CTF 查询（含知识卡自动注入）。"""
    from .knowledge import get_knowledge_card

    lines = [f"Solve the CTF challenge: {project.challenge_id}"]
    if project.title:
        lines.append(f"Title: {project.title}")
    meta = []
    if project.category:
        meta.append(f"category={project.category}")
    if project.difficulty:
        meta.append(f"difficulty={project.difficulty}")
    if project.target_host:
        port = f":{project.target_port}" if project.target_port else ""
        meta.append(f"target={project.target_host}{port}")
    if meta:
        lines.append("Meta: " + ", ".join(meta))
    if project.description:
        lines.append(f"\nChallenge description:\n{project.description}")
    lines.append(
        "\nWork directly in the challenge directory. "
        "When you find the flag, write it to the FLAG file in that directory "
        "(declarative submission — only the FLAG file is submitted)."
    )
    if relay_text:
        lines.append(
            "\nA previous session left this relay — resume from [下一步] "
            "without redoing recon:\n" + relay_text
        )

    query = "\n".join(lines)

    # 自动注入知识卡
    if project.category:
        card = get_knowledge_card(project.category)
        if card:
            query = query + "\n\n---\n\n" + card

    # 注入历史教训（F3-003/F3-004）：avoid list 拼在知识卡之后（末尾）
    if project.category:
        try:
            from .experiential_learning import get_avoid_list
            avoid = get_avoid_list(project.category)[:10]
        except Exception:  # noqa: BLE001 — 经验查询失败不阻断解题
            avoid = []
        if avoid:
            query += (
                "\n\n## 历史教训（avoid list — 别再犯）\n"
                + "\n".join(f"- {t}" for t in avoid)
            )

    return query


def read_flag_file(work_dir: str | Path) -> str:
    """读取工作目录的 FLAG 文件（声明式提交）。"""
    flag_file = Path(work_dir) / FLAG_FILENAME
    if flag_file.exists():
        return flag_file.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def resolve_default_model() -> str:
    """从 Hermes 配置解析默认模型（config.yaml 的 model.default）。

    run_agent 在 model 为空时不会自动回退到配置默认值（会以空模型名请求
    API 导致 400），因此 solver 必须显式解析。解析失败返回空串。
    """
    try:
        from fulilian_cli.config import load_config

        cfg = load_config() or {}
        return str(((cfg.get("model") or {}).get("default") or "")).strip()
    except Exception:  # noqa: BLE001
        return ""


def scan_log_for_flag(work_dir: str | Path) -> str:
    """扫描 solver.log 中的 flag（走三重校验门），供调度器兜底检测。"""
    log_file = Path(work_dir) / SOLVER_LOG
    if log_file.exists():
        text = log_file.read_text(encoding="utf-8", errors="replace")
        return check_output_for_flag(text) or ""
    return ""


def bootstrap_blackboard(project, work_dir: str | Path, relay_text: Optional[str]) -> None:
    """solver 侧黑板接线（07 指南集成步骤 1 的 solver 半边）。

    加载（或创建）工作目录的 blackboard.json，把接力块的死路/已达成原语
    注入黑板，并发布 attempt 开始 Fact。保证真实链路上黑板文件存在——
    调度器的无产出/变体止损维度与 RELAY→黑板注入都依赖它。

    幂等：原语按 content 去重（Fact 每次 new uuid，按 id 去重无效），
    运行时元信息行（"solver ran ..."）不是原语，不注入。
    """
    from .blackboard import (
        BLACKBOARD_FILENAME,
        Blackboard,
        Fact,
        load_blackboard,
        save_blackboard,
    )
    from .relay import parse_relay

    work_dir = Path(work_dir)
    board = load_blackboard(work_dir / BLACKBOARD_FILENAME) or Blackboard(
        challenge_id=project.challenge_id
    )
    existing = {f.content for f in board.get_facts()}
    if relay_text:
        relay = parse_relay(relay_text)
        for d in relay["dead_ends"]:
            board.mark_dead_end(d)
        for p in relay["achieved_primitives"]:
            if p.startswith("solver ran ") or p in existing:
                continue
            board.add_fact(Fact(content=p, source="relay"))
            existing.add(p)
    board.add_fact(
        Fact(
            content=f"solver attempt {project.attempts} started (pid {os.getpid()})",
            source="solver",
        )
    )
    save_blackboard(board, work_dir / BLACKBOARD_FILENAME)


def publish_result_fact(project, work_dir: str | Path, result: "SolverResult") -> None:
    """把 attempt 结束状态发布到黑板（跨尝试续接上下文，次数受 attempts 上限约束）。"""
    from .blackboard import (
        BLACKBOARD_FILENAME,
        Blackboard,
        Fact,
        load_blackboard,
        save_blackboard,
    )

    work_dir = Path(work_dir)
    board = load_blackboard(work_dir / BLACKBOARD_FILENAME) or Blackboard(
        challenge_id=project.challenge_id
    )
    board.add_fact(
        Fact(
            content=(
                f"solver attempt {project.attempts} finished "
                f"ok={result.ok} flag={'yes' if result.flag else 'no'}"
                f"{' err=' + result.error if result.error else ''}"
            ),
            source="solver",
        )
    )
    save_blackboard(board, work_dir / BLACKBOARD_FILENAME)


def _default_solver_impl(project, work_dir: Path, query: str) -> int:
    """真实求解：复用 Hermes run_agent 核心（CTF 模式），stdout/stderr 进 solver.log。"""
    from run_agent import main as run_agent_main

    log_path = work_dir / SOLVER_LOG
    old_cwd = os.getcwd()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        os.chdir(work_dir)
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            sys.stdout, sys.stderr = log, log
            code = run_agent_main(
                query=query,
                mode="ctf",
                model=project.model or "",
                max_turns=30,
            )
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        os.chdir(old_cwd)
    return int(code or 0)


def solver_worker(project, work_dir: str, model: str, queue, solver_impl=None) -> None:
    """solver 进程入口（multiprocessing.Process target）。

    Args:
        project: Project 对象（含挑战元信息）
        work_dir: 挑战工作目录
        model: 覆盖模型（空串用配置默认模型）
        queue: multiprocessing.Queue，结束时报 SolverResult
        solver_impl: 可注入的求解实现（测试用）；None 走真实 run_agent
    """
    work_dir = Path(work_dir)
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        # F4-001：题目目录自动生成 AGENTS.md（chdir 后由 _load_agents_md 注入）
        try:
            from .agents_md import ensure_agents_md

            ensure_agents_md(work_dir, project)
        except Exception:  # noqa: BLE001 — AGENTS.md 缺失只降级上下文注入，不阻断解题
            pass
        # F4-004：solver 侧默认 workspace-write 沙箱档（hooks 读取）
        os.environ.setdefault(ENV_SANDBOX_MODE, "workspace-write")
        # F4-003/F4-004：worker 进程内注册 CTF hooks（不写 ~/.hermes 配置）
        try:
            from .hooks import register_ctf_tool_hooks

            register_ctf_tool_hooks()
        except Exception:  # noqa: BLE001 — hook 注册失败只降级安全检查，不阻断解题
            pass
        # 模型解析：显式覆盖 > manifest 指定 > 配置默认（run_agent 不会自动回退）
        if not project.model:
            project.model = model or resolve_default_model()
        relay_text = read_relay_file(work_dir)
        try:
            bootstrap_blackboard(project, work_dir, relay_text)
        except Exception:  # noqa: BLE001 — 黑板接线失败只降级止损精度，不阻断解题
            pass
        query = build_solve_query(project, relay_text)
        print(f"[solver:{project.challenge_id}] start pid={os.getpid()} model={project.model}", flush=True)

        if solver_impl is None:
            code = _default_solver_impl(project, work_dir, query)
        else:
            code = solver_impl(project, work_dir, query)

        result = SolverResult(ok=(code == 0), exit_code=int(code or 0))
    except SystemExit as e:  # run_agent 以 sys.exit 退出
        result = SolverResult(ok=False, exit_code=int(e.code or 1), error=f"SystemExit: {e.code}")
    except Exception as e:  # noqa: BLE001 — 进程隔离：任何异常都不影响其他 solver
        result = SolverResult(ok=False, exit_code=1, error=f"{type(e).__name__}: {e}")

    # 声明式提交：读 FLAG 文件（存在即上报）
    try:
        result.flag = read_flag_file(work_dir)
    except OSError:
        result.flag = ""

    print(
        f"[solver:{project.challenge_id}] end ok={result.ok} "
        f"flag={'yes' if result.flag else 'no'}{' err=' + result.error if result.error else ''}",
        flush=True,
    )
    try:
        publish_result_fact(project, work_dir, result)
    except Exception:  # noqa: BLE001 — 黑板接线失败不掩盖结果上报
        pass
    try:
        queue.put(result)
    except Exception:  # noqa: BLE001 — 上报失败不掩盖结果
        pass


def switch_solver_model(agent, new_model: str, new_provider: str = "") -> None:
    """运行时切换 solver 模型（F4-005，卡题时换强模型）。

    复用 Hermes 原生 ``switch_model()``；黑板上下文在题目目录
    blackboard.json 文件里，换模型不受影响。交互会话中直接用原生
    ``/model`` 命令即可（run_agent 内置，等价路径）。
    """
    from agent.agent_runtime_helpers import switch_model

    switch_model(agent, new_model, new_provider)


__all__ = [
    "FLAG_FILENAME",
    "SOLVER_LOG",
    "SolverResult",
    "bootstrap_blackboard",
    "build_solve_query",
    "publish_result_fact",
    "read_flag_file",
    "scan_log_for_flag",
    "solver_worker",
    "switch_solver_model",
]
