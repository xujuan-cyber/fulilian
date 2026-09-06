"""CTF CLI handlers — dispatched from the FuLiLian command tree.

- Phase 1: ``solve`` 单题解题（CTF 模式 agent 运行）
- Phase 2: ``solve-all`` 批量解题（调度引擎：并行 + 探针 + 时间盒 + 收割轮）
- Phase 3: ``writeup`` / ``replay`` / ``knowledge``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from fulilian_ctf.sandbox import ENV_SANDBOX_MODE, SandboxMode


def _resolve_project(challenge_id: str):
    """challenge id（目录 / manifest 条目 / 裸 id）→ Project。"""
    from fulilian_ctf.dispatcher import Project
    from fulilian_ctf.registry import challenge_to_project, load_challenges

    path = Path(challenge_id).expanduser()
    if path.is_dir():
        if (path / "challenge.json").is_file():
            project = challenge_to_project(
                json.loads((path / "challenge.json").read_text(encoding="utf-8")),
                base_dir=path.parent,
            )
        else:
            project = Project(challenge_id=path.name, challenge_dir=str(path))
        return project
    try:
        entries = [e for e in load_challenges(challenge_id) if e.get("id")]
    except (ValueError, OSError):
        entries = []
    if entries:
        return challenge_to_project(entries[0])
    # 裸 id：在 cwd 下建同名工作目录
    return Project(challenge_id=challenge_id, challenge_dir=challenge_id)


def _run_race(args) -> "RaceResult":
    """--race 多模型竞速（F3-005/006）。"""
    from fulilian_ctf.racer import run_race

    project = _resolve_project(args.id)
    return run_race(
        project,
        models=getattr(args, "race_models", None) or None,
        quiet=False,
    )


def _run_multi_agent(args) -> "MultiAgentResult":
    """--multi-agent 多 Agent 协作（F3-007/008/009）。"""
    from fulilian_ctf.multi_agent import run_multi_agent

    project = _resolve_project(args.id)
    return run_multi_agent(
        project,
        directions=getattr(args, "directions", None) or None,
        n_direct_explorers=getattr(args, "explorers", None) or 4,
        model=args.model or "",
        quiet=False,
    )


def _run_boomerang(args) -> "MultiAgentResult":
    from fulilian_ctf.multi_agent import run_boomerang
    return run_boomerang(
        _resolve_project(args.id),
        max_rounds=getattr(args, "max_rounds", 2),
        max_explorers=getattr(args, "explorers", None) or 4,
        directions=getattr(args, "directions", None) or None,
        model=args.model or "",
        quiet=False,
    )


def _prepare_work_dir(project, challenge_id: str) -> Optional[Path]:
    """保证题目工作目录存在并自动生成 AGENTS.md（F4-001），返回工作目录。

    清单文件形态（challenge_id 指向 .json 且无独立 challenge_dir）返回 None，
    此时在当前目录求解、不生成 AGENTS.md。失败降级为 None，不阻断解题。
    """
    from fulilian_ctf.agents_md import ensure_agents_md

    raw = Path(project.challenge_dir or challenge_id).expanduser()
    if raw.suffix and not raw.is_dir():
        return None
    try:
        raw.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    # 绝对路径：chdir 之后相对路径不再指向原位置
    raw = raw.absolute()
    ensure_agents_md(raw, project)
    return raw


def _run_solve_once(project, work_dir: Optional[Path], query: str, model: str,
                    oneshot: bool, as_json: bool,
                    architect_model: str = "", executor_model: str = "") -> int:
    """非交互求解一次（F4-002：``-p`` / ``--json``）。

    agent 输出重定向进工作目录 solver.log（与 solver_worker 同一证据来源），
    结束后按声明式提交读取 FLAG 文件、并扫 log 兜底（走三重校验门）。

    Returns:
        进程退出码：解出（flag 非空）0，否则 1。
    """
    from fulilian_ctf.solver import SOLVER_LOG, read_flag_file
    from fulilian_ctf.verify import check_output_for_flag

    if as_json:
        print(json.dumps({
            "event": "start",
            "challenge": project.challenge_id,
            "model": model,
            "work_dir": str(work_dir) if work_dir else str(Path.cwd()),
        }, ensure_ascii=False), flush=True)

    from run_agent import main as solver_main

    base_dir = work_dir or Path.cwd()
    log_path = base_dir / SOLVER_LOG
    old_cwd = os.getcwd()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        if work_dir is not None:
            os.chdir(work_dir)
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            sys.stdout, sys.stderr = log, log
            code = int(solver_main(
                query=query,
                mode="ctf",
                model=model,
                architect_model=architect_model or "",
                executor_model=executor_model or "",
            ) or 0)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        os.chdir(old_cwd)

    flag = ""
    try:
        flag = read_flag_file(base_dir)
    except OSError:
        flag = ""
    if not flag:
        try:
            flag = check_output_for_flag(
                log_path.read_text(encoding="utf-8", errors="replace")
            ) or ""
        except OSError:
            flag = ""
    solved = bool(flag)

    if as_json:
        print(json.dumps({
            "event": "result",
            "challenge": project.challenge_id,
            "ok": code == 0,
            "solved": solved,
            "flag": flag,
            "exit_code": code,
            "log": str(log_path),
        }, ensure_ascii=False), flush=True)
    else:
        status = "SOLVED" if solved else ("OK (no flag found)" if code == 0 else "FAILED")
        print(f"[solve] {project.challenge_id}: {status}"
              + (f" flag={flag}" if solved else f" (log: {log_path})"))

    return 0 if solved else 1


def _looks_like_path(challenge_id: str) -> bool:
    """启发式：输入是否「看起来像路径」（区别于 web-01 这类裸挑战 id）。"""
    if os.sep in challenge_id or (os.altsep and os.altsep in challenge_id):
        return True
    if challenge_id.startswith((".", "~")):
        return True
    return Path(challenge_id).suffix != ""


def _solve_work_dir_for(project, challenge_id: str) -> str:
    """纯读镜像 ``_prepare_work_dir`` 的目录选择（不落盘、不 mkdir）。

    清单文件形态（challenge_id 指向 .json 且无独立 challenge_dir）在 cwd 求解，
    其余返回 challenge_dir（expanduser + absolute 规范化）。
    """
    raw = Path(project.challenge_dir or challenge_id).expanduser()
    if raw.suffix and not raw.is_dir():
        return str(Path.cwd())
    return str(raw.absolute())


def _validate_solve_target(challenge_id: str) -> Optional[str]:
    """solve 目标前置校验：合法返回将要使用的 work_dir（规范化字符串），否则 None。

    解析顺序与 ``_resolve_project`` 保持一致（历史轨迹对齐 writeup/replay 的
    ``_resolve_writeup_inputs``），避免误杀合法输入：

    1. 存在的目录（裸挑战目录 / 含 challenge.json / 平台清单目录）→ 该目录
    2. 平台清单文件（``load_challenges`` 可解析出挑战）→ 条目的 challenge_dir
    3. 历史轨迹 ``FULILIAN_HOME/traces/<id>.json`` → solve 将新建的 cwd/<id> 目录
    4. 相对裸 id（如 web-01）→ 既有机制：在 cwd 下建同名工作目录（见
       ``_resolve_project`` 尾分支），放行

    其余（不存在的路径形态输入、不可解析的非清单文件、空白 id）→ None：
    放行只会让 ``_prepare_work_dir`` 在任意位置 mkdir 空目录并启动 agent
    空烧 API token。纯只读检查，不创建任何目录。
    """
    if not challenge_id or not challenge_id.strip():
        return None
    path = Path(challenge_id).expanduser()
    if path.is_dir():
        # 目录本身就是挑战（含 challenge.json 的题目目录同样放行）
        challenge_json = path / "challenge.json"
        if not challenge_json.is_file():
            return str(path.absolute())
        try:
            from fulilian_ctf.registry import challenge_to_project

            project = challenge_to_project(
                json.loads(challenge_json.read_text(encoding="utf-8")),
                base_dir=path.parent,
            )
        except (OSError, ValueError, KeyError, TypeError):
            # 损坏的 challenge.json：目标无效，拒绝并给出清晰报错
            return None
        return _solve_work_dir_for(project, challenge_id)
    # 平台清单文件 / 其它 load_challenges 可解析形态
    try:
        from fulilian_ctf.registry import challenge_to_project, load_challenges

        entries = [e for e in load_challenges(challenge_id) if e.get("id")]
    except (ValueError, OSError, KeyError, TypeError):
        entries = []
    if entries:
        return _solve_work_dir_for(challenge_to_project(entries[0]), challenge_id)
    # 历史轨迹（与 writeup/replay 同源，record_solve_outcome 写入）
    if _load_historical_trace(challenge_id) is not None:
        return str(path.absolute())
    # 相对裸 id：cwd 下建同名工作目录是既有机制，放行
    if not _looks_like_path(challenge_id):
        return str(path.absolute())
    return None


def _report_invalid_solve_target(challenge_id: str) -> None:
    """打印 solve 目标无效的 stderr 详情（风格对齐 handle_replay_command 的 exit 2）。"""
    if challenge_id and _looks_like_path(challenge_id):
        path = Path(challenge_id).expanduser()
        if path.exists():
            print(
                f"solve: '{challenge_id}' exists but is not a usable challenge "
                "directory or platform manifest",
                file=sys.stderr,
            )
        else:
            print(
                f"solve: challenge path does not exist: '{challenge_id}'",
                file=sys.stderr,
            )
        print(
            "  (refusing to start the agent: it would explore an empty/wrong "
            "work dir and burn API tokens)",
            file=sys.stderr,
        )
    else:
        print(
            f"solve: cannot resolve challenge id: '{challenge_id}'",
            file=sys.stderr,
        )
    print(
        "  checked: existing directory, platform manifest "
        "(platform.json / manifest.json / challenges.json / challenge.json), "
        "historical trace (FULILIAN_HOME/traces/<id>.json)",
        file=sys.stderr,
    )
    print(
        "  usage: pass an existing challenge directory, or sync platform "
        "challenges first (`fulilian ctfd sync <base_url> <out_dir>`) "
        "and solve a challenge directory under <out_dir>",
        file=sys.stderr,
    )


def handle_solve_command(args: argparse.Namespace) -> None:
    """Solve a single CTF challenge in CTF mode.

    - 默认：``run_agent.main(mode="ctf")`` 单 agent 求解（Phase 1 语义，
      知识卡注入），在题目工作目录内运行（自动加载 AGENTS.md）
    - ``-p``：非交互单次求解，打印结果后退出（F4-002）
    - ``--json``：输出结构化 JSON 事件流供脚本消费（F4-002）
    - ``--race``：多模型竞速（Phase 3, F3-005/006）
    - ``--multi-agent``：多 Agent 协作（Phase 3, F3-007/008/009）
    - 目标前置校验：challenge id/路径无法解析时在启动 agent 前秒级报错
      退出（exit 2），不发生任何 LLM API 调用
    """
    challenge_id = args.id
    if getattr(args, "rpc", False):
        from .solve_rpc import serve
        sys.exit(serve())
    # 前置校验：目标无效时秒级退出（exit 2），绝不启动 agent / 发 API 请求。
    # --race / --multi-agent / 默认单 agent 三分支共用同一 args.id，统一在此拦截。
    if _validate_solve_target(challenge_id) is None:
        _report_invalid_solve_target(challenge_id)
        sys.exit(2)

    if getattr(args, "race", False):
        result = _run_race(args)
        sys.exit(0 if result.solved else 1)

    if getattr(args, "boomerang", False):
        result = _run_boomerang(args)
        sys.exit(0 if result.solved else 1)

    if getattr(args, "multi_agent", False):
        result = _run_multi_agent(args)
        sys.exit(0 if result.solved else 1)

    query = f"Solve the CTF challenge: {challenge_id}"

    # Phase 3 知识注入：从 challenge id 猜测分类（如 web-01 → web）。
    # inject_ctf_context = playbook + 知识卡 + 历史教训 + 相似 WP 检索，
    # 全程 best-effort（失败静默降级）；无猜测分类时仍注入 playbook。
    from fulilian_ctf.knowledge import inject_ctf_context

    guessed_category = _guess_category_from_id(challenge_id)
    try:
        query = inject_ctf_context(guessed_category, query, query=challenge_id)
    except Exception as exc:  # noqa: BLE001 — 知识注入失败不阻断解题
        print(f"[solve] knowledge injection skipped: {exc}", file=sys.stderr)

    # Phase 1 模型解析：显式 --model 优先，否则配置默认（run_agent 不自动回退）
    from fulilian_ctf.solver import resolve_default_model

    model = args.model or resolve_default_model()

    # F4-004：CTF 求解默认 workspace-write（环境变量可覆盖为 read-only/full）
    os.environ.setdefault(ENV_SANDBOX_MODE, "workspace-write")

    # F4-003/F4-004：进程内注册 CTF 危险命令拦截 + flag 检测 hooks
    # （不写 ~/.fulilian 任何配置/白名单；FULILIAN_SAFE_MODE=1 时自动跳过）
    try:
        os.environ["FULILIAN_CTF_MODE"] = "1"
        from fulilian_ctf.hooks import register_ctf_tool_hooks

        register_ctf_tool_hooks()
    except Exception:  # noqa: BLE001 — hook 注册失败只降级安全检查，不阻断解题
        pass

    # F4-001：题目工作目录 + AGENTS.md（chdir 后由 _load_agents_md 自动加载）
    project = _resolve_project(challenge_id)
    work_dir = _prepare_work_dir(project, challenge_id)
    if work_dir is not None:
        os.environ["FULILIAN_CTF_WORK_DIR"] = str(work_dir.resolve())

    # F4-002：-p / --json 非交互模式
    oneshot = bool(getattr(args, "oneshot", False))
    as_json = bool(getattr(args, "json", False))
    if oneshot or as_json:
        sys.exit(_run_solve_once(
            project, work_dir, query, model, oneshot, as_json,
            architect_model=getattr(args, "architect_model", "") or "",
            executor_model=getattr(args, "executor_model", "") or "",
        ))

    from run_agent import main as solver_main
    from fulilian_ctf.solver import resolve_max_turns_from_env

    old_cwd = os.getcwd()
    try:
        if work_dir is not None:
            os.chdir(work_dir)
        solver_main(
            query=query,
            mode="ctf",
            model=model,
            # 轮数上限：FULILIAN_CTF_MAX_TURNS 显式设置才限制；未设 =
            # 不限轮数（与 solve-all 子进程路径语义一致）
            max_turns=resolve_max_turns_from_env(),
            architect_model=str(getattr(args, "architect_model", "") or ""),
            executor_model=str(getattr(args, "executor_model", "") or ""),
        )
    finally:
        os.chdir(old_cwd)
    sys.exit(0)


def _guess_category_from_id(challenge_id: str) -> str:
    """从 challenge id 猜测分类（简单启发：id 前缀含 web/crypto/reverse/pwn/forensics/misc）。"""
    cid = challenge_id.lower()
    for cat in ("forensics", "crypto", "reverse", "pwn", "web", "misc"):
        if cid.startswith(cat) or f"-{cat}" in cid or f"_{cat}" in cid:
            return cat
    return ""


def handle_solve_all_command(args: argparse.Namespace) -> None:
    """Batch-solve challenges on a platform (Phase 2 — 调度引擎).

    ``fulilian solve-all <platform> [--workers N] [--timebox S] ...``

    platform 可以是：平台清单 JSON 文件，或包含 challenge.json 子目录的平台目录。
    调度确定性（非 LLM 驱动）：新题优先 → 探针跳过不可达 → 时间盒中断输出接力块
    → 无新题时收割轮按 EV 回退已放弃的题。
    """
    from fulilian_ctf.dispatcher import Dispatcher
    from fulilian_ctf.registry import challenge_to_project, load_challenges

    platform = args.platform
    base = Path(platform).expanduser()
    try:
        entries = load_challenges(platform)
    except (ValueError, OSError) as e:
        print(f"solve-all: {e}", file=sys.stderr)
        sys.exit(2)

    projects = [
        challenge_to_project(e, base_dir=base if base.is_dir() else None)
        for e in entries
    ]
    projects = [p for p in projects if p.challenge_id]

    limit = getattr(args, "limit", None)
    if limit is not None and limit > 0:
        projects = projects[:limit]

    if not projects:
        print("solve-all: no challenges to solve", file=sys.stderr)
        sys.exit(0)

    workers = getattr(args, "workers", None) or 3
    # --max-turns：显式指定才限制 solver 轮数（经环境变量传给 solver 子
    # 进程）；0/未设 = 不限轮数（题目一直解到出 flag，靠进展型止损兜底）
    max_turns_override = getattr(args, "max_turns", None) or 0
    if max_turns_override:
        os.environ["FULILIAN_CTF_MAX_TURNS"] = str(int(max_turns_override))
    dispatcher = Dispatcher(
        max_workers=workers,
        model=getattr(args, "model", "") or "",
        probe_timeout=getattr(args, "probe_timeout", None) or 60,
        max_attempts=getattr(args, "max_attempts", None) or 5,
        timebox_override=getattr(args, "timebox", None) or 0,
        max_tokens=getattr(args, "max_tokens", None),
        max_no_output_rounds=getattr(args, "max_no_output_rounds", None) or 7,
        max_variant_failures=getattr(args, "max_variant_failures", None) or 7,
        stop_loss=not getattr(args, "no_stop_loss", False),
        warmup=not getattr(args, "no_warmup", False),
    )
    for p in projects:
        dispatcher.add_project(p)

    print(
        f"solve-all: {len(projects)} challenge(s), {workers} worker(s) — "
        + ", ".join(p.challenge_id for p in projects)
    )
    try:
        summary = dispatcher.run(limit=limit)
    except KeyboardInterrupt:
        dispatcher.stop_all()
        print("\nsolve-all: interrupted by user — stopped all solvers", file=sys.stderr)
        sys.exit(130)

    # 持久化状态（供 status / replay 等后续命令复用）
    try:
        state_path = base / "dispatcher-state.json" if base.is_dir() else Path(
            "dispatcher-state.json"
        )
        dispatcher.save_state(summary, state_path)
    except OSError:
        pass

    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        _print_solve_all_summary(summary)

    totals = summary["totals"]
    sys.exit(0 if totals.get("solved", 0) else 1)


def _print_solve_all_summary(summary: dict) -> None:
    """文本汇总表。"""
    print()
    header = f"{'ID':<24} {'diff':<8} {'tier':<9} {'att':<4} {'status':<14} flag"
    print(header)
    print("-" * len(header))
    for p in summary["projects"]:
        flag = p.get("flag") or ""
        line = (
            f"{p['id']:<24} {p['difficulty']:<8} {p.get('last_tier', ''):<9} "
            f"{p['attempts']:<4} {p['status']:<14} {flag}"
        )
        # 未解出时附加止损/超时原因（截断保持对齐）
        reason = p.get("stop_reason") or ""
        if not flag and reason:
            line += f"  [{reason[:40]}]"
        print(line)
    t = summary["totals"]
    print("-" * len(header))
    print(
        f"Totals: {t.get('solved', 0)} solved, {t.get('timeout', 0)} timeout, "
        f"{t.get('abandoned', 0)} abandoned, {t.get('infra_blocked', 0)} infra_blocked "
        f"({summary['duration']}s, {summary['spawns']} solver spawns)"
    )


def _resolve_writeup_inputs(challenge_id: str):
    """writeup/replay 共用：解析 (project, work_dir)。

    目录 → 本身；manifest 条目 → 其 challenge_dir；裸 id → 先查
    FULILIAN_HOME/traces（历史轨迹），再回退 cwd/<id>。
    """
    from fulilian_ctf.dispatcher import Project

    path = Path(challenge_id).expanduser()
    if path.is_dir():
        if (path / "challenge.json").is_file():
            from fulilian_ctf.registry import challenge_to_project

            project = challenge_to_project(
                json.loads((path / "challenge.json").read_text(encoding="utf-8")),
                base_dir=path.parent,
            )
        else:
            project = Project(challenge_id=path.name, challenge_dir=str(path))
        return project, path

    # manifest 条目
    from fulilian_ctf.registry import challenge_to_project, load_challenges

    try:
        entries = [e for e in load_challenges(challenge_id) if e.get("id")]
    except (ValueError, OSError):
        entries = []
    if entries:
        project = challenge_to_project(entries[0])
        work_dir = Path(project.challenge_dir or challenge_id)
        if work_dir.is_dir():
            return project, work_dir

    # 历史轨迹（dispatcher record_solve_outcome 写入的 TRACES_DIR）或裸 id 目录
    project = Project(challenge_id=challenge_id, challenge_dir=challenge_id)
    work_dir = Path(challenge_id)
    if not work_dir.is_dir():
        try:
            from fulilian_constants import FULILIAN_HOME

            trace_file = FULILIAN_HOME / "traces" / f"{challenge_id}.json"
        except Exception:  # noqa: BLE001
            trace_file = None
        if trace_file and trace_file.is_file():
            return project, None  # 只有历史 trace，无工作目录
    return project, work_dir if work_dir.is_dir() else None


def _load_historical_trace(challenge_id: str) -> Optional[dict]:
    """读取 FULILIAN_HOME/traces/{id}.json（record_solve_outcome 的历史轨迹）。"""
    try:
        from fulilian_constants import FULILIAN_HOME

        trace_file = FULILIAN_HOME / "traces" / f"{challenge_id}.json"
        if trace_file.is_file():
            return json.loads(trace_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ImportError):
        pass
    return None


def handle_writeup_command(args: argparse.Namespace) -> None:
    """Auto-generate a CTF writeup (Phase 3 — F3-010)."""
    from fulilian_ctf.writeup import generate_writeup, save_writeup, writeup_to_format

    project, work_dir = _resolve_writeup_inputs(args.id)
    fmt = getattr(args, "format", "markdown") or "markdown"

    trace = None
    if work_dir is None:
        # 无工作目录：从 TRACES_DIR 历史轨迹构造最小 writeup
        hist = _load_historical_trace(args.id)
        if hist is None:
            print(
                f"writeup: no work dir or historical trace found for '{args.id}'",
                file=sys.stderr,
            )
            sys.exit(2)
        from fulilian_ctf.trace import Trace, TraceStep

        trace = Trace(
            challenge_id=str(hist.get("challenge_id", args.id)),
            category=str(hist.get("category", "")),
            flag=str(hist.get("flag", "")),
            steps=[
                TraceStep(index=i + 1, kind="command", text=str(c))
                for i, c in enumerate(hist.get("key_commands") or [])
            ],
        )
        work_dir_path = None
    else:
        work_dir_path = work_dir

    writeup_md = generate_writeup(
        challenge_id=args.id,
        work_dir=work_dir_path or (Path.cwd()),
        project=project,
        trace=trace,
    )
    output_text = writeup_to_format(writeup_md, fmt, trace=trace)

    output = getattr(args, "output", None)
    if output:
        path = save_writeup(output_text, fmt, output)
        print(f"writeup: saved to {path}")
    else:
        print(output_text)
    sys.exit(0)


def handle_replay_command(args: argparse.Namespace) -> None:
    """Replay a challenge trajectory (Phase 3 — F3-014)."""
    from fulilian_ctf.trace import get_or_build_trace, replay_trace

    project, work_dir = _resolve_writeup_inputs(args.id)

    if work_dir is not None:
        trace = get_or_build_trace(work_dir, project)
    else:
        hist = _load_historical_trace(args.id)
        if hist is None:
            print(
                f"replay: no work dir or historical trace found for '{args.id}'",
                file=sys.stderr,
            )
            sys.exit(2)
        from fulilian_ctf.trace import Trace, TraceStep

        trace = Trace(
            challenge_id=str(hist.get("challenge_id", args.id)),
            category=str(hist.get("category", "")),
            flag=str(hist.get("flag", "")),
            steps=[
                TraceStep(index=i + 1, kind="command", text=str(c))
                for i, c in enumerate(hist.get("key_commands") or [])
            ],
        )

    print(
        replay_trace(
            trace,
            start_step=getattr(args, "step", None) or 1,
            as_json=bool(getattr(args, "json", False)),
        )
    )
    sys.exit(0)


def handle_ctfd_command(args: argparse.Namespace) -> None:
    """CTFd platform integration (Phase 3 — F3-011/F3-012).

    ``fulilian ctfd list <base_url> [--api-key K]``
    ``fulilian ctfd submit <base_url> <id> <flag> [--api-key K]``
    ``fulilian ctfd sync <base_url> <out_dir> [--api-key K]``
    ``fulilian ctfd poll <base_url> <platform_dir> [--api-key K]``
    ``fulilian ctfd poll-job <base_url> <platform_dir> [--schedule S]``
    ``fulilian ctfd serve-mcp [--base-url U] [--api-key K]``
    """
    from fulilian_ctf.ctfd_adapter import (
        ENV_CTFD_API_KEY,
        ENV_CTFD_BASE_URL,
        CTFdAdapter,
        create_poll_job,
        poll_new_challenges,
        serve_mcp,
        sync_challenges,
    )

    action = getattr(args, "ctfd_action", None)
    if not action:
        print("ctfd: use one of list / submit / sync / poll / poll-job / serve-mcp")
        sys.exit(2)

    if action == "serve-mcp":
        # MCP server：stdout 只输出协议消息，配置经参数或环境变量
        import os

        if getattr(args, "base_url", None):
            os.environ[ENV_CTFD_BASE_URL] = args.base_url
        if getattr(args, "api_key", None):
            os.environ[ENV_CTFD_API_KEY] = args.api_key
        sys.exit(serve_mcp())

    if action == "poll-job":
        job = create_poll_job(
            base_url=args.base_url,
            api_key=getattr(args, "api_key", None) or "",
            platform_dir=args.platform_dir,
            schedule=getattr(args, "schedule", None) or "every 5m",
        )
        print(f"ctfd: cron job created id={job.get('id')} next_run={job.get('next_run_at')}")
        print("ctfd: note — cron jobs fire while the gateway process is running")
        sys.exit(0)

    adapter = CTFdAdapter(
        args.base_url, getattr(args, "api_key", None) or None
    )

    if action == "list":
        items = adapter.list_challenges()
        print(f"ctfd: {len(items)} challenge(s) on {args.base_url}")
        for item in items:
            print(
                f"  [{item.get('id', '?'):>4}] {item.get('name', '')}"
                f"  ({item.get('category', '')}, {item.get('value', 0)} pts)"
            )
        sys.exit(0)

    if action == "submit":
        result = adapter.submit_flag(args.challenge_id, args.flag)
        data = result.get("data", result)
        status = data.get("status", result.get("success", "?"))
        message = data.get("message", "")
        print(f"ctfd: submit challenge={args.challenge_id} → {status}"
              + (f" ({message})" if message else ""))
        sys.exit(0 if status == "correct" else 1)

    if action == "sync":
        entries = sync_challenges(adapter, args.out_dir)
        print(
            f"ctfd: synced {len(entries)} challenge(s) → "
            f"{Path(args.out_dir) / 'manifest.json'}"
        )
        print(f"ctfd: run `fulilian solve-all {args.out_dir}` to batch-solve")
        sys.exit(0)

    if action == "poll":
        state_file = Path(args.platform_dir).expanduser() / "poll-state.json"
        new = poll_new_challenges(adapter, state_file)
        if new:
            print(f"ctfd: {len(new)} new challenge(s):")
            for item in new:
                print(f"  [{item.get('id', '?'):>4}] {item.get('name', '')}")
        else:
            print("ctfd: no new challenges")
        sys.exit(0)


def handle_knowledge_command(args: argparse.Namespace) -> None:
    """Manage the CTF knowledge base (Phase 3 — F3-001/F3-002/F3-003).

    ``fulilian knowledge import [--source KB]`` — 把 Des-CTF-Knowledge 导入 FTS5
    ``fulilian knowledge query <terms> [--limit N] [--category C]`` — 检索历史 WP
    ``fulilian knowledge list [--category C]`` — 列出知识卡 / 索引统计
    ``fulilian knowledge stats`` — 跨题学习统计
    ``fulilian knowledge cards-sync`` — 从经验库筛「建议加入知识卡」的技巧
    """
    action = getattr(args, "knowledge_action", None)

    if action == "query":
        _knowledge_query(args)
    elif action == "import":
        _knowledge_import(args)
    elif action == "list":
        _knowledge_list(args)
    elif action == "stats":
        _knowledge_stats()
    elif action == "cards-sync":
        _knowledge_cards_sync()
    else:
        print(
            "knowledge: use one of import / query / list / stats / cards-sync "
            "(try `fulilian knowledge --help`)"
        )


def _knowledge_import(args: argparse.Namespace) -> None:
    """导入 Des-CTF-Knowledge 到 FTS5。"""
    from fulilian_ctf.knowledge_retriever import build_index, get_index_stats

    force = getattr(args, "force", False)
    print(f"[knowledge] importing Des-CTF-Knowledge (force={force}) ...")
    count = build_index(force=force)
    stats = get_index_stats()
    print(f"[knowledge] imported {count} writeups into FTS5")
    print(f"[knowledge] db: {stats['db_path']}")
    if stats["by_category"]:
        print("[knowledge] by category: " + ", ".join(
            f"{cat}={n}" for cat, n in stats["by_category"].items()
        ))


def _knowledge_query(args: argparse.Namespace) -> None:
    """FTS5 检索历史 WP。"""
    from fulilian_ctf.knowledge_retriever import search

    query = " ".join(args.query)
    category = getattr(args, "category", None)
    limit = getattr(args, "limit", 5)

    results = search(query=query, category=category, limit=limit)
    if not results:
        print(f"knowledge: no results for '{query}'")
        return

    print(f"knowledge: {len(results)} result(s) for '{query}'"
          + (f" (category={category})" if category else ""))
    print()
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r['title']}  ({r['category']})")
        print(f"    {r['source_path']}")
        if r.get("snippet"):
            snip = r["snippet"].replace("\n", " ").strip()
            print(f"    {snip[:160]}")
        print()


def _knowledge_list(args: argparse.Namespace) -> None:
    """列出知识卡 / 索引状态。"""
    from fulilian_ctf.knowledge import CATEGORIES, SKILLS_DIR, get_knowledge_card
    from fulilian_ctf.knowledge_retriever import get_index_stats, list_categories

    category = getattr(args, "category", None)

    print("CTF knowledge cards:")
    for cat, filename in CATEGORIES.items():
        if category and cat != category:
            continue
        path = SKILLS_DIR / filename
        status = "✓" if path.exists() else "✗ missing"
        print(f"  {cat:<12} {filename:<18} {status}")

    stats = get_index_stats()
    print(f"\nFTS5 index: {stats['total_docs']} writeups"
          f" (db: {stats['db_path']})")
    if stats["by_category"]:
        print("  by category: " + ", ".join(
            f"{cat}={n}" for cat, n in stats["by_category"].items()
        ))

    cats_in_db = list_categories()
    if cats_in_db:
        print(f"  categories in db: {', '.join(cats_in_db)}")


def _knowledge_stats() -> None:
    """跨题学习统计。"""
    from fulilian_ctf.experiential_learning import get_learning_stats

    stats = get_learning_stats()
    print("Experiential learning stats:")
    print(f"  entries: {stats['total_entries']} "
          f"(positive={stats['positive']}, negative={stats['negative']})")
    print(f"  techniques: {stats['techniques']}")
    if stats["by_category"]:
        print("  by category: " + ", ".join(
            f"{cat}={n}" for cat, n in stats["by_category"].items()
        ))
    print(f"  file: {stats['file_path']}")


def _knowledge_cards_sync() -> None:
    """从经验库筛「建议加入知识卡」的技巧候选清单。

    读取 experiential_learning 的 learnings 文件（ATT&CK 索引），筛出
    成功率高（成功率 ≥0.75）或出现 ≥2 次的 technique，打印
    分类 + 技巧 + 频次 + 建议目标卡。纯读操作，不修改知识卡。
    """
    from fulilian_ctf.experiential_learning import query_index
    from fulilian_ctf.knowledge import CATEGORIES, SKILLS_DIR

    rows = query_index()  # [{category, technique, success, fail, total, success_rate}]
    if not rows:
        print("cards-sync: learning.json 为空，暂无可同步的技巧。")
        return

    # 入选条件：出现 ≥2 次，或成功率 ≥0.75（含 1 次即高成功的技巧）
    candidates = [
        r for r in rows
        if r["total"] >= 2 or r["success_rate"] >= 0.75
    ]
    # 高频优先，其次成功次数
    candidates.sort(key=lambda r: (r["total"], r["success"]), reverse=True)

    print(f"cards-sync: {len(candidates)} candidate technique(s) "
          f"(出现≥2次 或 成功率≥0.75；共 {len(rows)} 条技巧记录)")
    print()
    for r in candidates[:20]:
        card_file = CATEGORIES.get(r["category"], "misc.md")
        card_path = SKILLS_DIR / card_file
        status = "✓" if card_path.exists() else "✗ missing"
        print(
            f"  [{r['category']:<8}] {r['technique'][:70]}"
            f"\n      频次: 成功 {r['success']} / 失败 {r['fail']}"
            f" (共 {r['total']}，成功率 {r['success_rate']:.0%})"
            f"  → 建议目标卡: skills/ctf-knowledge/{card_file} {status}"
        )
    if len(candidates) > 20:
        print(f"  ... 其余 {len(candidates) - 20} 条省略")
