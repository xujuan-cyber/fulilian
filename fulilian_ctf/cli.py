"""CTF CLI handlers — dispatched from the FuLiLian command tree.

- Phase 1: ``solve`` 单题解题（CTF 模式 agent 运行）
- Phase 2: ``solve-all`` 批量解题（调度引擎：并行 + 探针 + 时间盒 + 收割轮）
- Phase 3: ``writeup`` / ``replay`` / ``knowledge``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fulilian_ctf.sandbox import ENV_SANDBOX_MODE, SandboxMode


def _resolve_project(challenge_id: str):
    """challenge id（目录 / manifest 条目 / 裸 id）→ Project。"""
    from fulilian_ctf.dispatcher import Project
    from fulilian_ctf.registry import (
        challenge_json_to_project,
        challenge_to_project,
        load_challenges,
    )

    path = Path(challenge_id).expanduser()
    if path.is_dir():
        if (path / "challenge.json").is_file():
            project = challenge_json_to_project(path / "challenge.json")
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


def _resolve_effective_solve_mode(args) -> str:
    """本次 solve 实际使用的求解模式。

    显式 flag（``--race`` / ``--multi-agent`` / ``--boomerang``）优先于
    ``--solve-mode`` / ``FULILIAN_CTF_SOLVE_MODE`` / config ``ctf.solve_mode``；
    三者都没有时是 ``single``。显式 flag 排在最前是为了保持既有语义与测试
    不变：``solve <id> --race`` 永远走 race，不受环境变量影响。
    """
    from fulilian_ctf.solver import (
        SOLVE_MODE_BOOMERANG,
        SOLVE_MODE_MULTI_AGENT,
        SOLVE_MODE_RACE,
        resolve_solve_mode,
    )

    if getattr(args, "race", False):
        return SOLVE_MODE_RACE
    if getattr(args, "boomerang", False):
        return SOLVE_MODE_BOOMERANG
    if getattr(args, "multi_agent", False):
        return SOLVE_MODE_MULTI_AGENT

    return resolve_solve_mode(getattr(args, "solve_mode", "") or "")


def _run_parallel_mode(args, solve_mode: str) -> None:
    """非默认求解模式的统一分流（race / boomerang / multi-agent）。

    三条分支共用 ``_resolve_project`` / ``_prepare_work_dir`` 与结束后的经验
    落库 —— 此前 race 分支在 ``handle_solve_command`` 里直接 ``return``，
    既没准备题目工作目录（AGENTS.md），也不落库，与单 agent 路径不同源。
    """
    from fulilian_ctf.solver import (
        SOLVE_MODE_BOOMERANG,
        SOLVE_MODE_MULTI_AGENT,
        SOLVE_MODE_RACE,
    )

    runners = {
        SOLVE_MODE_RACE: _run_race,
        SOLVE_MODE_BOOMERANG: _run_boomerang,
        SOLVE_MODE_MULTI_AGENT: _run_multi_agent,
    }
    runner = runners.get(solve_mode)
    if runner is None:  # pragma: no cover — 取值已在 resolve_solve_mode 收窄
        raise ValueError(f"unknown solve mode: {solve_mode!r}")

    project = _resolve_project(args.id)
    work_dir = _prepare_work_dir(project, args.id)
    try:
        result = runner(args)
    finally:
        # 经验落库 best-effort：失败只降级，绝不改变退出码（与单题路径同源）
        try:
            _record_single_solve_experience(project, work_dir)
        except Exception:  # noqa: BLE001 — 落库失败不影响 solve 退出码
            logging.debug("solve experience recording failed", exc_info=True)
    sys.exit(0 if result.solved else 1)


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
    from fulilian_ctf.solver import (
        SOLVER_LOG,
        read_flag_file,
        solver_evidence_stream,
    )
    from fulilian_ctf.verify import check_output_for_flag

    if as_json:
        print(json.dumps({
            "event": "start",
            "challenge": project.challenge_id,
            "model": model,
            "work_dir": str(work_dir) if work_dir else str(Path.cwd()),
        }, ensure_ascii=False), flush=True)

    from run_agent import main as solver_main
    from fulilian_ctf.solver import _log_prefix_chars_from_env

    base_dir = work_dir or Path.cwd()
    log_path = base_dir / SOLVER_LOG
    old_cwd = os.getcwd()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        if work_dir is not None:
            os.chdir(work_dir)
        # 证据流 + 镜像（solve 目录之外）：work_dir 是 agent 的地盘，它能用
        # write_file 把 solver.log 覆盖掉。见 solver_evidence_stream 的文档。
        with solver_evidence_stream(base_dir) as log:
            if log is not None:
                sys.stdout, sys.stderr = log, log
            _raw_code = solver_main(
                query=query,
                mode="ctf",
                model=model,
                architect_model=architect_model or "",
                executor_model=executor_model or "",
                log_prefix_chars=_log_prefix_chars_from_env(),
            )
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        os.chdir(old_cwd)
    # None 视为失败（与 solver._solver_result_from_code 的 M-2 防线同口径）；
    # 字符串退出码（sys.exit("msg")）按失败计 1，避免 int() 二次抛异常
    if _raw_code is None:
        code = 1
    elif isinstance(_raw_code, int):
        code = _raw_code
    else:
        try:
            code = int(_raw_code)
        except (TypeError, ValueError):
            code = 1

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
            from fulilian_ctf.registry import challenge_json_to_project

            project = challenge_json_to_project(challenge_json)
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

    # 并行模式分流：显式 flag > --solve-mode / env / config，默认单 agent。
    # 非默认模式统一走 _run_parallel_mode（共用工作目录准备 + 经验落库）。
    from fulilian_ctf.solver import SOLVE_MODE_SINGLE

    solve_mode = _resolve_effective_solve_mode(args)
    if solve_mode != SOLVE_MODE_SINGLE:
        _run_parallel_mode(args, solve_mode)

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

    # Phase 1 模型解析（P6 模型路由）：显式 --model > FULILIAN_CTF_MODEL >
    # config ctf.solve_model > model.default。run_agent 不自动回退，所以这里
    # 必须解析到底；解析结果大声打印——「以为在用强模型其实在用默认」要看得见。
    from fulilian_ctf.solver import resolve_solve_model

    model, model_source = resolve_solve_model(getattr(args, "model", "") or "")
    # stderr：--json 模式下 stdout 是机器契约（每行必须是 JSON 事件），
    # 人类可读的状态横幅一律走 stderr（与上方 knowledge injection 横幅同规）。
    print(f"[solve] model: {model or '<empty>'} (source: {model_source})", file=sys.stderr)

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
        # 解题时钟：WP 回灌判难与 10 分钟知识库检索注入共用（best-effort）
        try:
            from fulilian_ctf.solve_clock import mark_solve_start
            mark_solve_start(work_dir)
        except Exception:  # noqa: BLE001 — 时钟失败不阻断解题
            pass

    # F4-002：-p / --json 非交互模式
    # ctf_oneshot 是 argparse 的真实 dest（见 subcommands/solve.py：顶层 -z/--oneshot
    # 占了 oneshot 这个名字，共用 Namespace 会导致 `solve <id> -p` 被误判成顶层
    # 一次性对话）。回退读 oneshot 只为兼容直接构造 Namespace 的既有测试与调用方。
    oneshot = bool(getattr(args, "ctf_oneshot", False)) or bool(
        getattr(args, "oneshot", False)
    )
    as_json = bool(getattr(args, "json", False))
    if oneshot or as_json:
        code = _run_solve_once(
            project, work_dir, query, model, oneshot, as_json,
            architect_model=getattr(args, "architect_model", "") or "",
            executor_model=getattr(args, "executor_model", "") or "",
        )
        # 经验落库（F3-003/F3-004）：单题路径与 dispatcher 批量路径同源接线，
        # best-effort，失败静默，不影响退出码
        try:
            _record_single_solve_experience(project, work_dir)
        except Exception:  # noqa: BLE001 — 经验落库失败不影响 solve 退出码
            logging.debug("solve experience recording failed", exc_info=True)
        sys.exit(code)

    from run_agent import main as solver_main
    from fulilian_ctf.solver import (
        _log_prefix_chars_from_env,
        resolve_max_turns_from_env,
    )

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
            # 镜像日志参数预览宽度：fulilian solve 走的是本路径而非
            # solver.py，之前漏接线导致跑批设 FULILIAN_LOG_PREFIX_CHARS
            # 不生效（P1.2 探针踩坑：命令全被截成 "cd /tmp..."）。
            log_prefix_chars=_log_prefix_chars_from_env(),
        )
    finally:
        os.chdir(old_cwd)
    # 经验落库（F3-003/F3-004）：单题路径接线，best-effort，失败静默
    try:
        _record_single_solve_experience(project, work_dir)
    except Exception:  # noqa: BLE001 — 经验落库失败不影响 solve 退出码
        logging.debug("solve experience recording failed", exc_info=True)
    sys.exit(0)


def _guess_category_from_id(challenge_id: str) -> str:
    """从 challenge id 猜测分类（简单启发：id 前缀含 web/crypto/reverse/pwn/forensics/misc）。"""
    cid = challenge_id.lower()
    for cat in ("forensics", "crypto", "reverse", "pwn", "web", "misc"):
        if cid.startswith(cat) or f"-{cat}" in cid or f"_{cat}" in cid:
            return cat
    return ""


def _detect_solved_flag(base_dir: Path) -> str:
    """flag 检测链：read_flag_file 读 FLAG 文件 → check_output_for_flag 扫
    solver.log（后者只放行通过三重校验门的 flag）。无 flag 返回空串。

    经验落库（_record_single_solve_experience）与 WP 回灌（_writeback_wp）
    共用同一检测口径。
    """
    from fulilian_ctf.solver import SOLVER_LOG, read_flag_file
    from fulilian_ctf.verify import check_output_for_flag

    try:
        flag = read_flag_file(base_dir)
    except OSError:
        flag = ""
    if not flag:
        try:
            flag = check_output_for_flag(
                (base_dir / SOLVER_LOG).read_text(
                    encoding="utf-8", errors="replace"
                )
            ) or ""
        except OSError:
            flag = ""
    return flag


def _record_single_solve_experience(project, work_dir: Optional[Path]) -> None:
    """单题 solve 结束后的经验落库（F3-003/F3-004），best-effort。

    与 dispatcher 批量路径同源：从工作目录黑板提取 CONFIRMED/REFUTED fact
    作为 key_commands（每条截 120 字符、最多 20 条）。flag/verified 走现成
    的 flag 检测链（``read_flag_file`` 读 FLAG 文件 → ``check_output_for_flag``
    扫 solver.log；后者只放行通过三重校验门的 flag，故 verified=bool(flag)）。
    任何失败只静默吞掉：绝不改变命令退出码、绝不往 stdout 打印干扰输出。
    """
    try:
        from fulilian_ctf.blackboard import (
            BLACKBOARD_FILENAME,
            State,
            load_blackboard,
        )
        from fulilian_ctf.experiential_learning import record_solve_outcome

        # 与 _run_solve_once 的 base_dir 语义一致：无独立工作目录（清单文件
        # 形态）时在 cwd 求解，此处 cwd 已在 finally 中恢复
        base_dir = work_dir or Path.cwd()

        flag = _detect_solved_flag(base_dir)

        fact_contents: list[str] = []
        try:
            board = load_blackboard(base_dir / BLACKBOARD_FILENAME)
        except (OSError, ValueError):
            board = None
        if board is not None:
            fact_contents = [
                f.content[:120]
                for f in board.get_facts()
                if f.state in (State.CONFIRMED, State.REFUTED)
            ][:20]

        record_solve_outcome(
            challenge_id=project.challenge_id,
            category=project.category
            or _guess_category_from_id(project.challenge_id)
            or "misc",
            success=bool(flag),
            key_commands=fact_contents,
            flag=flag,
            verified=bool(flag),
        )
    except Exception:  # noqa: BLE001 — 经验落库失败不影响 solve 退出码
        # debug 记录但不打断主流程（P1 修复：裸 pass 让落库失败完全不可见）
        logging.debug("solve experience recording failed", exc_info=True)


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
            from fulilian_ctf.registry import challenge_json_to_project

            project = challenge_json_to_project(path / "challenge.json")
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
            from fulilian_constants import get_fulilian_home

            from fulilian_ctf.fsutil import safe_filename_stem

            trace_file = (
                get_fulilian_home()
                / "traces"
                / f"{safe_filename_stem(challenge_id)}.json"
            )
        except Exception:  # noqa: BLE001
            trace_file = None
        if trace_file and trace_file.is_file():
            return project, None  # 只有历史 trace，无工作目录
    return project, work_dir if work_dir.is_dir() else None


def _load_historical_trace(challenge_id: str) -> Optional[dict]:
    """读取 FULILIAN_HOME/traces/<id>.json（record_solve_outcome 写入）。

    文件名净化口径与写入方一致；目录在调用时解析，不固化模块常量。
    """
    try:
        from fulilian_constants import get_fulilian_home

        from fulilian_ctf.fsutil import safe_filename_stem

        trace_file = (
            get_fulilian_home() / "traces" / f"{safe_filename_stem(challenge_id)}.json"
        )
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
        # expanduser 后再用：`fulilian ctfd sync ... ~/ctfd` 会原样建一个名为
        # "~" 的目录（shell 在引号内不展开），而后续 solve-all 又会把 ~ 展开
        # —— 同步到 A、去 B 里找，静默扑空。本文件其余入口（_resolve_project
        # / _prepare_work_dir）都先 expanduser，这里与它们对齐。
        out_dir = Path(args.out_dir).expanduser()
        entries = sync_challenges(adapter, str(out_dir))
        print(
            f"ctfd: synced {len(entries)} challenge(s) → "
            f"{out_dir / 'manifest.json'}"
        )
        print(f"ctfd: run `fulilian solve-all {out_dir}` to batch-solve")
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
    ``fulilian knowledge query <terms> [--limit N] [--category C]
        [--year Y] [--contest NAME] [--vuln-type T]`` — 检索历史 WP
    ``fulilian knowledge list [--category C]`` — 列出知识卡 / 索引统计
    ``fulilian knowledge stats`` — 知识库 + 跨题学习统计
    ``fulilian knowledge meta build`` — 重建结构化元数据 sidecar 与大赛索引
    ``fulilian knowledge cards-sync`` — 生成知识卡候选文件（人工编辑确认）
    ``fulilian knowledge cards-sync --apply`` — 把保留的候选块回灌进知识卡
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
    elif action == "meta":
        _knowledge_meta(args)
    elif action == "cards-sync":
        _knowledge_cards_sync(args)
    else:
        print(
            "knowledge: use one of import / query / list / stats / meta / "
            "cards-sync (try `fulilian knowledge --help`)"
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
    """FTS5 检索历史 WP（支持 category / year / contest / vuln-type 过滤）。"""
    from fulilian_ctf.knowledge_retriever import search

    query = " ".join(args.query)
    category = getattr(args, "category", None)
    limit = getattr(args, "limit", 5)
    year = getattr(args, "year", None)
    contest = getattr(args, "contest", None)
    vuln_type = getattr(args, "vuln_type", None)

    results = search(
        query=query, category=category, limit=limit,
        year=year, contest=contest, vuln_type=vuln_type,
    )
    active = [
        f"{label}={val}" for label, val in (
            ("category", category), ("year", year),
            ("contest", contest), ("vuln_type", vuln_type),
        ) if val
    ]
    suffix = f" ({', '.join(active)})" if active else ""

    if not results:
        print(f"knowledge: no results for '{query}'{suffix}")
        return

    print(f"knowledge: {len(results)} result(s) for '{query}'{suffix}")
    print()
    for i, r in enumerate(results, 1):
        tags = " · ".join(str(x) for x in (
            r.get("year") or "", r.get("contest") or "", r.get("vuln_type") or ""
        ) if x)
        print(f"[{i}] {r['title']}  ({r['category']})" + (f"  [{tags}]" if tags else ""))
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
    """知识库统计 + 跨题学习统计。

    早期版本只打 experiential learning（几乎恒为 0），让人以为知识库是空的——
    「索引里到底有多少东西」才是这个命令最该回答的问题，故知识库部分在前。
    """
    from fulilian_ctf.knowledge_retriever import get_index_stats
    from fulilian_ctf.experiential_learning import get_learning_stats

    idx = get_index_stats()
    print("Knowledge base (FTS5 index):")
    print(f"  documents: {idx['total_docs']}")
    print(f"  db: {idx['db_path']}")
    if idx["by_category"]:
        print("  by category: " + ", ".join(
            f"{cat}={n}" for cat, n in idx["by_category"].items()
        ))
    if not idx["schema_current"]:
        print("  metadata: unavailable — index predates year/contest/vuln_type "
              "columns; run `fulilian knowledge import --force` to rebuild")
    else:
        print(f"  metadata coverage: year={idx['year_known']}, "
              f"contest={idx['contest_known']} "
              f"({idx['contest_count']} distinct contests), "
              f"vuln_type={sum(idx['by_vuln_type'].values())}")
        if idx["by_year"]:
            print("  by year: " + ", ".join(
                f"{y}={n}" for y, n in idx["by_year"].items()
            ))
        if idx["top_contests"]:
            print("  top contests: " + ", ".join(
                f"{c}={n}" for c, n in idx["top_contests"].items()
            ))
        if idx["by_vuln_type"]:
            print("  by vuln_type: " + ", ".join(
                f"{v}={n}" for v, n in list(idx["by_vuln_type"].items())[:12]
            ))

    stats = get_learning_stats()
    print("\nExperiential learning stats:")
    print(f"  entries: {stats['total_entries']} "
          f"(positive={stats['positive']}, negative={stats['negative']})")
    print(f"  techniques: {stats['techniques']}")
    if stats["by_category"]:
        print("  by category: " + ", ".join(
            f"{cat}={n}" for cat, n in stats["by_category"].items()
        ))
    print(f"  file: {stats['file_path']}")


def _knowledge_meta(args: argparse.Namespace) -> None:
    """重建结构化元数据 sidecar（wp_meta_index.json）与大赛索引（contest_index.md）。"""
    from fulilian_ctf.knowledge_retriever import (
        KB_PATH, META_INDEX_RELPATH, CONTEST_INDEX_RELPATH,
        build_meta_index, build_contest_index,
    )

    action = getattr(args, "meta_action", None)
    if action not in (None, "", "build"):
        print(f"knowledge meta: unknown action '{action}' (try `build`)")
        return

    min_count = getattr(args, "min_count", 3)
    n = build_meta_index(min_count=min_count)
    if n == 0:
        print(f"[knowledge] meta: no WP found under {KB_PATH / 'CTF大赛WP集合'}")
        return
    print(f"[knowledge] meta: {n} entries -> {KB_PATH / META_INDEX_RELPATH}")

    contests = build_contest_index()
    print(f"[knowledge] meta: {contests} contests -> {KB_PATH / CONTEST_INDEX_RELPATH}")


def _knowledge_cards_sync(args: argparse.Namespace) -> None:
    """知识卡回灌三步流程入口（生成 → 人工编辑确认 → --apply 回灌）。

    生成模式（默认）：从经验库筛出候选技巧，写入候选文件（默认
    ~/Exchange/ctf-知识卡候选.md），stdout 只打印摘要不刷屏；
    apply 模式（--apply）：解析候选文件里剩余的候选块，逐条回灌进
    对应知识卡的「实战经验沉淀」小节，最后把候选文件重置为仅含说明。
    """
    out_raw = getattr(args, "out", None)
    out_path = (
        Path(out_raw).expanduser() if out_raw
        else _CARDS_SYNC_DEFAULT_OUT.expanduser()
    )
    if getattr(args, "apply", False):
        _cards_sync_apply(out_path)
    else:
        _cards_sync_generate(out_path)


# ── cards-sync 候选文件（生成 / apply 共用常量）───────────────────────────

# 候选文件默认输出路径（--out 可覆盖）
_CARDS_SYNC_DEFAULT_OUT = Path("~/Exchange/ctf-知识卡候选.md")

# 候选文件头部：固定标题 + 使用说明（apply 后文件也被重置回这段）。
# 注意：说明文案里不要出现 `<!-- candidate` / `<!-- /candidate -->` 字面
# 标记，否则会被 _cards_sync_parse_blocks 误识别为候选块。
_CARDS_SYNC_HEADER = (
    "# CTF 知识卡候选（cards-sync 自动生成）\n"
    "\n"
    "使用说明：文件中每个 candidate 块（由成对的 HTML 注释标记圈起）\n"
    "是一条候选经验。**删掉不要的候选块（被删掉 = 放弃），保留想要的**，\n"
    "然后运行：\n"
    "\n"
    "    fulilian knowledge cards-sync --apply\n"
    "\n"
    "即可把保留的候选回灌进 skills/ctf-cards/ 对应知识卡的\n"
    "「实战经验沉淀」小节。apply 成功后本文件会被重置为仅含本说明。\n"
)

# 候选块开 / 闭标记（apply 解析用；开标记里带结构化元数据，容错人工编辑）
_CARDS_SYNC_OPEN_RE = re.compile(r"<!--\s*candidate\s+(?P<attrs>[^>]*?)\s*-->")
_CARDS_SYNC_CLOSE = "<!-- /candidate -->"
# 元数据属性：key="value" 优先，退化支持 key=bare-token
_CARDS_SYNC_ATTR_RE = re.compile(r'(\w+)="([^"]*)"|(\w+)=([^\s"<>]+)')

# 「实战经验沉淀」小节标题（append 模式下不存在则创建）
_CARDS_SYNC_SECTION = "## 实战经验沉淀"


def _collect_cards_sync_candidates() -> Optional[list[dict]]:
    """按既有门槛筛出候选技巧，并补充 entries 维度的证据信息。

    入选条件（与旧版打印行为一致，不放松）：出现 ≥2 次或成功率 ≥0.75；
    有成功记录的 technique 还须至少一条 verified=True 的 entry 支撑。
    纯失败（success==0）不受 verified 门槛限制。

    Returns:
        list | None：learning.json 为空（索引无记录）时返回 None；
        否则返回候选列表（可能为空列表 = 有记录但无达标候选）。
    """
    from fulilian_ctf.experiential_learning import load_learnings, query_index

    rows = query_index()
    if not rows:
        return None

    verified_keys = {
        (e.get("category", ""), e.get("technique", ""))
        for e in load_learnings()["entries"]
        if e.get("verified")
    }
    candidates = [
        r for r in rows
        if (r["total"] >= 2 or r["success_rate"] >= 0.75)
        and (r["success"] == 0 or (r["category"], r["technique"]) in verified_keys)
    ]
    candidates.sort(key=lambda r: (r["total"], r["success"]), reverse=True)

    # 按 (category, technique) 聚合 entries：来源题 id（去重保序，最多 3 个）
    # 与最新 command（entries 按落库顺序追加，遍历中最后一条即最新）
    entries_by_key: dict[tuple[str, str], list[dict]] = {}
    for e in load_learnings()["entries"]:
        entries_by_key.setdefault(
            (e.get("category", ""), e.get("technique", "")), []
        ).append(e)

    enriched = []
    for r in candidates:
        entries = entries_by_key.get((r["category"], r["technique"]), [])
        challenge_ids: list[str] = []
        latest_command = ""
        for e in entries:
            cid = str(e.get("challenge_id") or "").strip()
            if cid and cid not in challenge_ids:
                challenge_ids.append(cid)
            cmd = str(e.get("command") or "").strip()
            if cmd:
                latest_command = cmd
        enriched.append({
            **r,
            "challenge_ids": challenge_ids[:3],
            "latest_command": latest_command,
        })
    return enriched


def _cards_sync_attr_escape(value: str) -> str:
    """把值塞进 HTML 注释属性（key="value"）前的转义：去引号、压平换行。"""
    return " ".join(str(value).replace('"', "'").split())


def _cards_sync_parse_attrs(raw: str) -> dict:
    """解析候选块开标记里的元数据属性（人工编辑后仍尽量容错）。"""
    attrs: dict[str, str] = {}
    for m in _CARDS_SYNC_ATTR_RE.finditer(raw):
        key = m.group(1) or m.group(3)
        value = m.group(2) if m.group(2) is not None else m.group(4)
        attrs[key] = value
    return attrs


def _cards_sync_generate(out_path: Path) -> None:
    """生成模式：全量重建候选文件（入选门槛不变），stdout 只打摘要。"""
    candidates = _collect_cards_sync_candidates()
    if candidates is None:
        print("cards-sync: learning.json 为空，暂无可同步的技巧。")
        return
    if not candidates:
        # 有经验记录但无达标候选：仍写出仅含说明的候选文件，保持
        # 「编辑 → --apply」流程可用（对空文件 apply 是安全空操作）。
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_CARDS_SYNC_HEADER, encoding="utf-8")
        print(f"cards-sync: 0 candidate technique(s) → {out_path}")
        print(
            "cards-sync: 请编辑该文件（删除不要的候选块），然后运行 "
            "`fulilian knowledge cards-sync --apply` 回灌。"
        )
        return

    from fulilian_ctf.knowledge import CATEGORIES

    date_prefix = datetime.now().strftime("%Y%m%d")
    blocks: list[str] = []
    for i, c in enumerate(candidates, 1):
        card_file = CATEGORIES.get(c["category"], "misc.md")
        technique_line = " ".join(str(c["technique"]).split())[:70]
        # 拟写入要点：technique + 最新 command 压成单行；command 缺失只写 technique
        bullet = technique_line
        if c["latest_command"] and c["latest_command"] != c["technique"]:
            cmd_line = " ".join(str(c["latest_command"]).split())[:80]
            bullet = f"{technique_line}（关键命令: {cmd_line}）"
        evidence = f"成功 {c['success']} / 失败 {c['fail']}"
        if c["success"] > 0:
            evidence += "（含 verified 通过）"
        sources = ", ".join(c["challenge_ids"]) if c["challenge_ids"] else "无"
        attrs = (
            f'id={date_prefix}-{i} '
            f'category="{_cards_sync_attr_escape(c["category"])}" '
            f'technique="{_cards_sync_attr_escape(c["technique"])}" '
            f'sources="{_cards_sync_attr_escape(", ".join(c["challenge_ids"]))}"'
        )
        blocks.append(
            f"<!-- candidate {attrs} -->\n"
            f"### [{c['category']}] {technique_line}\n"
            f"- 目标卡: skills/ctf-cards/{card_file}\n"
            f"- 证据: {evidence}；来源: {sources}\n"
            f"- 拟写入:\n"
            f"  - {bullet}\n"
            f"<!-- /candidate -->"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        _CARDS_SYNC_HEADER + "\n" + "\n\n".join(blocks) + "\n",
        encoding="utf-8",
    )
    print(f"cards-sync: {len(candidates)} candidate technique(s) → {out_path}")
    print(
        "cards-sync: 请编辑该文件（删除不要的候选块），然后运行 "
        "`fulilian knowledge cards-sync --apply` 回灌。"
    )


def _cards_sync_parse_blocks(text: str) -> tuple[list[tuple[dict, str]], list[str]]:
    """解析候选文件里所有完整的 candidate 块。

    Returns:
        (blocks, warnings)：blocks 为 (attrs, body) 列表；warnings 为
        跳过块对应的告警文案（标记不配对 / 元数据残缺）。
        绝不抛异常——坏块一律跳过并告警。
    """
    blocks: list[tuple[dict, str]] = []
    warnings: list[str] = []
    pos = 0
    while True:
        m = _CARDS_SYNC_OPEN_RE.search(text, pos)
        if not m:
            break
        close_idx = text.find(_CARDS_SYNC_CLOSE, m.end())
        next_open = _CARDS_SYNC_OPEN_RE.search(text, m.end())
        attrs = _cards_sync_parse_attrs(m.group("attrs"))
        block_id = attrs.get("id", "?")
        if close_idx == -1 or (next_open and next_open.start() < close_idx):
            # 开标记没有配对的闭标记（闭标记前又出现下一个开标记）：
            # 跳过该块并告警，从下一个开标记处继续解析
            warnings.append(
                f"候选块 id={block_id}"
                f"（technique={attrs.get('technique', '?')}）"
                f"缺少配对的结束标记 {_CARDS_SYNC_CLOSE}，已跳过"
            )
            pos = next_open.start() if next_open else len(text)
            continue
        body = text[m.end():close_idx]
        if not attrs.get("technique"):
            warnings.append(
                f"候选块 id={block_id} 格式残缺（缺少 technique 元数据），已跳过"
            )
        else:
            blocks.append((attrs, body))
        pos = close_idx + len(_CARDS_SYNC_CLOSE)
    return blocks, warnings


def _cards_sync_extract_bullet(body: str) -> str:
    """从候选块正文提取「拟写入」要点行（尊重人工编辑后的文本）。"""
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("- 拟写入"):
            for nxt in lines[i + 1:]:
                s = nxt.strip()
                if s.startswith("- "):
                    return s[2:].strip()
                if s:
                    break
            break
    return ""


def _cards_sync_append_to_card(
    category: str, technique: str, attrs: dict, body: str,
) -> tuple[bool, str]:
    """把单个候选块回灌进目标知识卡。

    Returns:
        (ok, reason)：ok=False 时 reason 说明跳过原因（卡缺失 / 已去重）。
    """
    from fulilian_ctf.knowledge import CATEGORIES, SKILLS_DIR

    card_file = CATEGORIES.get((category or "").lower(), "misc.md")
    card_path = SKILLS_DIR / card_file
    if not card_path.exists():
        return False, f"知识卡缺失（不自动建卡）: {card_path}"

    content = card_path.read_text(encoding="utf-8")
    # 去重：卡片已含相同 technique 文本（全文或压平后的 70 字符形态）则跳过
    dedupe_keys = [k for k in (
        technique, " ".join(technique.split())[:70],
    ) if k]
    if any(k in content for k in dedupe_keys):
        return False, "卡片已含相同技巧"

    bullet = _cards_sync_extract_bullet(body) or technique
    sources = attrs.get("sources", "").strip()
    line = f"- {bullet}" + (f"（来源: {sources}）" if sources else "")

    lines = content.rstrip("\n").split("\n") if content.strip() else []
    try:
        heading_i = lines.index(_CARDS_SYNC_SECTION)
    except ValueError:
        lines.append(_CARDS_SYNC_SECTION)
        heading_i = len(lines) - 1
    # 插入位置：该小节末尾（下一个二级标题行之前，否则文件末尾）
    end_i = len(lines)
    for j in range(heading_i + 1, len(lines)):
        if lines[j].startswith("## "):
            end_i = j
            break
    lines.insert(end_i, line)
    card_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, ""


def _cards_sync_apply(out_path: Path) -> None:
    """apply 模式：回灌候选文件里剩余的块，最后把文件重置为仅含说明。"""
    if not out_path.exists():
        print(f"cards-sync: 候选文件不存在: {out_path}（先运行生成模式）")
        return

    try:
        text = out_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cards-sync: 候选文件读取失败: {exc}")
        return

    blocks, warnings = _cards_sync_parse_blocks(text)
    for w in warnings:
        print(f"cards-sync: 警告: {w}")

    applied = 0
    skipped = len(warnings)  # 残缺 / 不配对的块计入 skipped
    for attrs, body in blocks:
        category = attrs.get("category", "")
        technique = attrs.get("technique", "")
        ok, reason = _cards_sync_append_to_card(
            category, technique, attrs, body,
        )
        if ok:
            applied += 1
        else:
            skipped += 1
            print(
                f"cards-sync: skipped（{reason}）: "
                f"[{category or '?'}] {technique[:50]}"
            )

    # 消费语义：全部处理完后把候选文件重置为仅含标题与说明——
    # 保留的块已回灌，被删掉的块视为放弃，不再二次处理。
    out_path.write_text(_CARDS_SYNC_HEADER, encoding="utf-8")
    print(
        f"cards-sync: apply 完成: applied={applied}, skipped={skipped}"
        f"（候选文件已重置: {out_path}）"
    )
