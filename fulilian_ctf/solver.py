"""单题 Solver 进程（F2-001 的 worker 侧）。

每个 solver 是一个独立进程（进程隔离：崩溃不影响其他），复用 Fulilian 的
``run_agent.main(mode="ctf")`` 核心。通过 multiprocessing.Queue 上报结果。

流程：
1. 读取 RELAY.md（若存在）→ 从「下一步」续接，不重复侦察
2. 构造 CTF 查询（含挑战元信息 + 声明式提交指令）
3. chdir 到挑战工作目录，调用 run_agent 核心（stdout/stderr 重定向到 solver.log
   作为证据来源，供调度器 check_output_for_flag 扫描）
4. 读取 FLAG 文件（声明式提交），连同结果经 Queue 上报

另提供 ``tee_solver_log``：默认 solve 路径（cli.handle_solve_command 不经
本模块 worker）复用同一证据来源——stdout/stderr 透传终端的同时 tee 进
work_dir/solver.log，供 trace 回放 / stopper 停滞检测消费。
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .fsutil import atomic_write_text
from .relay import read_relay_file
from .sandbox import ENV_SANDBOX_MODE, SandboxMode
from .verify import check_output_for_flag

FLAG_FILENAME = "FLAG"
SOLVER_LOG = "solver.log"
USAGE_FILE = "usage.json"

# 镜像日志的目标路径。设了它，tee_solver_log 会把同一份字节额外写到这里 ——
# 供采集器拿一份 agent 没理由去动的副本。见 tee_solver_log 的类文档。
SOLVER_LOG_MIRROR_ENV = "FULILIAN_SOLVER_LOG_MIRROR"

# CTF solver 最大轮数按难度分档（2026-09-04 起默认不启用）：
# 默认 max_turns 不设上限（AIAgent 库默认 sys.maxsize，题目一直解到
# 出 flag 为止）；本表仅在 --max-turns=0/未设时**不生效**——只有调用方
# 显式选择难度分档（fulilian_ctf.difficulty_max_turns）时作参考。
DIFFICULTY_MAX_TURNS = {
    "easy": 20,
    "medium": 30,
    "hard": 45,
    "expert": 45,
}


def difficulty_max_turns(difficulty: str) -> int:
    """难度 → solver max_turns（仅显式启用分档时使用；未知难度按 medium=30）。"""
    return DIFFICULTY_MAX_TURNS.get((difficulty or "").lower(), 30)


def resolve_max_turns_from_env(default_when_unlimited: int = sys.maxsize) -> int:
    """解析 FULILIAN_CTF_MAX_TURNS（CLI --max-turns 经环境变量传入）。

    显式正整数 → 轮数上限；未设/0/非法 → ``default_when_unlimited``
    （默认 sys.maxsize，即不限轮数——题目一直解到出 flag，靠 dispatcher
    进展型止损兜底）。
    """
    try:
        val = int(os.environ.get("FULILIAN_CTF_MAX_TURNS", "") or 0)
    except ValueError:
        val = 0
    if val <= 0:
        return default_when_unlimited
    return val


# ── 求解模式（solve_mode）────────────────────────────────────────────────
# 抢一血靠并行：race 多模型竞速 / multi-agent 多方向探索 / boomerang 折返。
# 但三者都是 N 份并发的成本与时长，**不能悄悄成为默认**——默认仍是单
# agent，需要时由 --solve-mode / FULILIAN_CTF_SOLVE_MODE / config ctf.solve_mode
# 显式打开。

SOLVE_MODE_ENV = "FULILIAN_CTF_SOLVE_MODE"
SOLVE_MODE_SINGLE = "single"
SOLVE_MODE_RACE = "race"
SOLVE_MODE_MULTI_AGENT = "multi-agent"
SOLVE_MODE_BOOMERANG = "boomerang"
SOLVE_MODES = (
    SOLVE_MODE_SINGLE,
    SOLVE_MODE_RACE,
    SOLVE_MODE_MULTI_AGENT,
    SOLVE_MODE_BOOMERANG,
)

# 宽松别名：命令行/环境变量里写成 multi_agent / multiagent / 默认 都认
_SOLVE_MODE_ALIASES = {
    "multi_agent": SOLVE_MODE_MULTI_AGENT,
    "multiagent": SOLVE_MODE_MULTI_AGENT,
    "default": SOLVE_MODE_SINGLE,
    "single-agent": SOLVE_MODE_SINGLE,
    "single_agent": SOLVE_MODE_SINGLE,
}


def _normalize_solve_mode(raw) -> str:
    """原始值 → 规范模式名；无法识别返回空串（由调用方决定降级还是告警）。"""
    if not raw:
        return ""
    text = str(raw).strip().lower().replace(" ", "")
    text = _SOLVE_MODE_ALIASES.get(text, text)
    return text if text in SOLVE_MODES else ""


def resolve_solve_mode(explicit: str = "", warn=None) -> str:
    """解析 CTF 求解模式：显式 > env > config ``ctf.solve_mode`` > single。

    Args:
        explicit: CLI ``--solve-mode`` 的值（空串 = 未指定）
        warn: 可选的告警回调 ``warn(str)``；用于把无法识别的取值报出去。
            默认打到 stderr —— 拼错 ``FULILIAN_CTF_SOLVE_MODE=rac`` 而静默
            退回单 agent，正是"以为在并行其实没有"的那类故障。

    Returns:
        str: ``single`` / ``race`` / ``multi-agent`` / ``boomerang`` 之一。
        任何解析失败都降级为 ``single``（绝不抛异常——求解模式不该挡住解题）。
    """
    if warn is None:
        def warn(msg: str) -> None:  # noqa: E306 — 局部默认实现
            print(f"[solve] {msg}", file=sys.stderr)

    sources = (
        ("--solve-mode", explicit),
        (SOLVE_MODE_ENV, os.environ.get(SOLVE_MODE_ENV, "")),
    )
    for label, raw in sources:
        if not raw or not str(raw).strip():
            continue
        mode = _normalize_solve_mode(raw)
        if mode:
            return mode
        warn(
            f"ignoring unrecognized solve mode {raw!r} from {label} "
            f"(expected one of: {', '.join(SOLVE_MODES)})"
        )

    try:
        from fulilian_cli.config import load_config

        raw = ((load_config() or {}).get("ctf") or {}).get("solve_mode")
        mode = _normalize_solve_mode(raw)
        if mode:
            return mode
        if raw and str(raw).strip():
            warn(
                f"ignoring unrecognized ctf.solve_mode {raw!r} in config "
                f"(expected one of: {', '.join(SOLVE_MODES)})"
            )
    except Exception:  # noqa: BLE001 — 配置读取失败回退单 agent
        pass
    return SOLVE_MODE_SINGLE


def _read_session_usage(agent) -> dict:
    """从 AIAgent 实例提取精确会话消耗（usage 计数器缺失时容错降级）。"""
    def _int(name: str) -> int:
        try:
            return max(0, int(getattr(agent, name, 0) or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _int("session_input_tokens") + _int("session_cache_read_tokens")
        + _int("session_cache_write_tokens"),
        "output_tokens": _int("session_output_tokens"),
        "api_calls": _int("session_api_calls"),
        "cost_usd": round(max(0.0, float(getattr(agent, "session_estimated_cost_usd", 0.0) or 0.0)), 6),
    }


def write_usage_record(work_dir: Path, agent, attempt: int = 1) -> Optional[dict]:
    """把本次尝试的精确消耗累计写进 work_dir/usage.json（跨尝试累加）。

    solver.log 每次尝试被 ``open(..., "w")`` 截断——跨尝试的 token 累计
    只能靠这里。写失败不阻断解题（返回 None）。
    """
    import json

    usage = _read_session_usage(agent)
    if usage["api_calls"] <= 0 and usage["input_tokens"] + usage["output_tokens"] <= 0:
        return None  # 无任何消耗记录（agent 未跑/老版本），保持文件不动
    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    try:
        path = Path(work_dir) / USAGE_FILE
        prev: dict = {}
        if path.is_file():
            try:
                prev = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(prev, dict):
                    prev = {}
            except (OSError, ValueError):
                prev = {}
        usage["total_tokens"] = int(prev.get("total_tokens", 0) or 0) + usage["total_tokens"]
        usage["api_calls"] = int(prev.get("api_calls", 0) or 0) + usage["api_calls"]
        usage["cost_usd"] = round(
            float(prev.get("cost_usd", 0.0) or 0.0) + usage["cost_usd"], 6
        )
        usage["attempts"] = int(prev.get("attempts", 0) or 0) + max(1, int(attempt or 1))
        # P1-3：原子写（tmp + os.replace），中断不留截断 usage.json
        atomic_write_text(path, json.dumps(usage, ensure_ascii=False, indent=2), lock=False)
        return usage
    except (OSError, TypeError, ValueError):
        return None


@dataclass
class SolverResult:
    """solver 进程的最终结果。"""

    ok: bool
    exit_code: int = 0
    error: str = ""
    flag: str = ""


# 子进程 → 父进程的结果走 multiprocessing.Queue 的管道（Linux 默认 64KiB）。
# 载荷一旦超过缓冲，feeder 线程阻塞在写端，而进程退出要等该线程收尾；父进程
# 又只在「子进程已死」后才读队列 —— 双方互等，直到时间盒耗尽，整条回传丢失
# （实测 200KB error：6s 时间盒被吃满、error 读到空串）。回传字段里唯一可能
# 无界的就是 error（异常消息 / traceback），估值截断即可。
MAX_RESULT_FIELD = 16_384


def shrink_result(result: SolverResult) -> SolverResult:
    """把超长的回传字段截断（保留头尾，便于定位），使载荷稳在管道缓冲内。

    完整内容仍在 solver.log / trace_*.json 里，不因截断而丢证据。
    """
    error = result.error or ""
    if len(error) <= MAX_RESULT_FIELD:
        return result
    head = MAX_RESULT_FIELD // 2
    tail = MAX_RESULT_FIELD - head
    return replace(
        result,
        error=(
            f"{error[:head]}\n…[截断 {len(error) - MAX_RESULT_FIELD} 字符，"
            f"完整内容见 solver.log]…\n{error[-tail:]}"
        ),
    )


def build_solve_query(project, relay_text: Optional[str] = None) -> str:
    """构造发给 solver 的 CTF 查询（含知识注入）。"""
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

    # 知识注入（playbook + 知识卡 + 历史教训 + 相似 WP 检索）。
    # 检索 query 优先用题目标题+描述关键词；inject_ctf_context 内部
    # 全程 best-effort，失败时静默降级、绝不阻断解题。
    try:
        from .knowledge import inject_ctf_context

        query_text = " ".join(
            t for t in (project.title, project.description) if t
        ).strip() or None
        query = inject_ctf_context(project.category or "", query, query_text)
    except Exception:  # noqa: BLE001 — 知识注入失败不阻断解题
        pass

    return query


def read_flag_file(work_dir: str | Path) -> str:
    """读取工作目录的 FLAG 文件（声明式提交）。

    ``is_file`` 而非 ``exists``：同名目录在这里不该变成 IsADirectoryError
    抛给调用方（solver_worker / cli 的 flag 检测链都是「读不到就当没有」）。
    """
    flag_file = Path(work_dir) / FLAG_FILENAME
    if flag_file.is_file():
        return flag_file.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def resolve_default_model() -> str:
    """从 Fulilian 配置解析默认模型（config.yaml 的 model.default）。

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


@contextlib.contextmanager
def solver_evidence_stream(work_dir: str | Path, filename: str = SOLVER_LOG):
    """打开 ``work_dir/<filename>`` 作为证据流，并（可选）镜像到目录之外。

    yield 的对象可直接赋给 ``sys.stdout``/``sys.stderr``：写它 = 写主日志
    （+ 镜像）。**落盘失败时 yield None**，调用方退回原流 —— 证据缺失不该
    阻断求解，这与两处调用点原本的降级语义一致。

    镜像由 ``FULILIAN_SOLVER_LOG_MIRROR`` 指定。存在的理由：``work_dir`` 是
    agent 的地盘，它可以用 write_file 把 solver.log 覆盖掉，**就发生在求解
    过程中**（实测 misc-chunkconcat-01，2026-09-11：那一跑解出 flag，
    api_calls 15，日志却被换成一份解题报告，工具面数据全丢 —— 0 被读成了
    "高效"）。镜像只增不改：work_dir 内那份原地保留，dispatcher 的增量扫描、
    replay/writeup、racer/multi_agent 的子目录证据全部不受影响。
    """
    log_path = Path(work_dir) / filename
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(log_path, "w", encoding="utf-8", errors="replace")
    except OSError:
        yield None
        return

    mirror = None
    mirror_env = os.environ.get(SOLVER_LOG_MIRROR_ENV) or ""
    if mirror_env:
        try:
            mirror_path = Path(mirror_env)
            mirror_path.parent.mkdir(parents=True, exist_ok=True)
            mirror = open(mirror_path, "w", encoding="utf-8", errors="replace")
        except OSError:
            mirror = None  # 镜像失败不影响主日志
    # 以主日志为「原流」（而非终端）：__getattr__ 委托给它，isatty/encoding
    # /buffer 等属性照旧可用，调用方看到的与直接用文件对象时一致。
    stream = log if mirror is None else _TeeStream(log, mirror)
    try:
        yield stream
    finally:
        for fh in (log, mirror):
            if fh is not None:
                try:
                    fh.flush()
                except (OSError, ValueError):
                    pass
                fh.close()


class _TeeStream:
    """把写入同时转发到原流与日志文件的流代理（write 级线程安全）。

    print 每次调用都动态查 ``sys.stdout``，所以线程池里的工具 worker 打印
    也能被捕获；其余属性（isatty/encoding/buffer…）透传原流，保持终端
    语义不变。日志写失败只降级（不阻断终端输出），与「证据落盘不应影响
    求解本身」的原则一致。

    可挂**多个**落盘目标（``log_file`` + ``mirror_file``）：见
    ``tee_solver_log`` 对镜像日志的说明。
    """

    def __init__(self, stream, log_file, mirror_file=None) -> None:
        self._stream = stream
        self._sinks = [f for f in (log_file, mirror_file) if f is not None]
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            for sink in self._sinks:
                try:
                    sink.write(text)
                    sink.flush()
                except (OSError, ValueError):
                    pass  # 日志写失败不阻断终端输出
            if self._stream is None:
                return len(text)
            return self._stream.write(text)

    def flush(self) -> None:
        with self._lock:
            for sink in self._sinks:
                try:
                    sink.flush()
                except (OSError, ValueError):
                    pass
            if self._stream is not None:
                self._stream.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


class tee_solver_log:
    """solve 期间把 stdout/stderr 透传终端，同时 tee 进 ``work_dir/solver.log``。

    默认 solve 路径（``fulilian solve`` 不带 ``--race``/``--multi-agent``）
    此前不落 solver.log，导致 replay/writeup 无步骤、stopper 停滞检测无
    数据源；本上下文管理器让该路径与 ``solver_worker``/``_run_solve_once``
    共用同一证据来源（run_agent 全程 stdout/stderr）。用法::

        with tee_solver_log(work_dir):
            run_agent.main(query=..., mode="ctf", ...)

    - 日志以 ``"w"`` 截断写（与 _run_solve_once/solver_worker 语义一致）
    - 写入即时 flush，供 stopper 在求解中途读取
    - 日志文件打不开（如只读目录）时静默降级为纯透传，不阻断求解
    - 退出时按对象身份精确还原被替换的 sys.stdout/sys.stderr（支持嵌套），
      异常安全，不吞异常

    **镜像日志（``FULILIAN_SOLVER_LOG_MIRROR``，2026-09-11 新增）：**
    ``work_dir`` 是 agent 的地盘 —— 它自己就能用 write_file 把
    ``solver.log`` 覆盖掉，而且**就发生在求解过程中**。实测
    （misc-chunkconcat-01，2026-09-11）：那一跑解出 flag、api_calls 15，
    但日志被换成一份解题报告，工具面数据全部丢失 —— 0 被读成了"高效"。

    设了该环境变量时，同样的字节**再写一份**到指定路径。刻意是**只增不改**：
    ``work_dir/solver.log`` 原地保留，stopper 的增量扫描、replay/writeup、
    racer / multi_agent 的子目录证据全部不受影响；镜像只是给采集器留一份
    agent 没有理由去动的副本。变量为空/未设时不改变任何行为。

    **注意（2026-09-11 核实）：本类当前没有生产调用点** —— 默认 solve 路径
    实际走 ``cli._run_solve_once`` / ``solver._default_solver_impl``，两者
    **共用** ``solver_evidence_stream``。本类保留供将来接终端 tee 用；
    别照它的文档判断"哪条路在写日志"，去看那两处。
    """

    def __init__(self, work_dir: str | Path, filename: str = SOLVER_LOG,
                 mirror: str | Path | None = None) -> None:
        self.log_path = Path(work_dir) / filename
        # 显式参数优先；否则读环境变量（跑批器用它把副本放到 work_dir 之外）
        if mirror is None:
            mirror = os.environ.get(SOLVER_LOG_MIRROR_ENV) or None
        self.mirror_path = Path(mirror) if mirror else None
        self._log_file = None
        self._mirror_file = None
        self._saved: tuple = ()
        self._out_tee = None
        self._err_tee = None

    def __enter__(self) -> Path:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._log_file = open(
                self.log_path, "w", encoding="utf-8", errors="replace"
            )
        except OSError:
            # 证据落盘失败只降级：不换流、不阻断求解
            self._log_file = None
            return self.log_path
        if self.mirror_path is not None:
            try:
                self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
                self._mirror_file = open(
                    self.mirror_path, "w", encoding="utf-8", errors="replace"
                )
            except OSError:
                self._mirror_file = None  # 镜像失败不影响主日志
        self._saved = (sys.stdout, sys.stderr)
        self._out_tee = _TeeStream(self._saved[0], self._log_file, self._mirror_file)
        self._err_tee = _TeeStream(self._saved[1], self._log_file, self._mirror_file)
        sys.stdout = self._out_tee
        sys.stderr = self._err_tee
        return self.log_path

    def __exit__(self, exc_type, exc, tb) -> bool:
        # 按对象身份还原：期间若被第三方再替换则不动（支持嵌套 tee）
        if self._out_tee is not None and sys.stdout is self._out_tee:
            sys.stdout = self._saved[0]
        if self._err_tee is not None and sys.stderr is self._err_tee:
            sys.stderr = self._saved[1]
        for fh in (self._log_file, self._mirror_file):
            if fh is not None:
                try:
                    fh.flush()
                except (OSError, ValueError):
                    pass
                fh.close()
        self._log_file = self._mirror_file = None
        self._out_tee = self._err_tee = None
        return False  # 不吞异常


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
    from .relay import is_relay_meta_text, parse_relay

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
            # P1-3 / A-4：与 dispatcher._write_relay 共用同一谓词口径
            if is_relay_meta_text(p) or p in existing:
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


def _solver_result_from_code(code) -> SolverResult:
    """把 run_agent.main 的退出码转为 SolverResult（M-2）。

    ``None`` 视为失败：main 修复前所有路径无 return（恒 None），旧语义
    下 ``ok=(code == 0)`` 恒真——初始化失败/API 全挂都报成功。本防线保证
    即使上游又退化为无返回值，也不会误报 ok。
    （注意：卡面参考式 ``ok=((code or 1) == 0)`` 会把 0 也误判为失败
    —— ``0 or 1`` 求值为 1——故按契约语义用 ``is None`` 显式判空。）
    """
    exit_code = 1 if code is None else int(code)
    return SolverResult(ok=(exit_code == 0), exit_code=exit_code)


def _default_solver_impl(project, work_dir: Path, query: str) -> int:
    """真实求解：复用 Fulilian run_agent 核心（CTF 模式），stdout/stderr 进 solver.log。"""
    from run_agent import main as run_agent_main

    # 解题时钟 + CTF hooks（危险命令拦截/flag 检测/知识库检索注入）：
    # solve-all 走独立子进程，需在此自行标记与注册（best-effort 不阻断求解）
    try:
        from .solve_clock import mark_solve_start
        mark_solve_start(work_dir)
    except Exception:  # noqa: BLE001 — 时钟失败不阻断求解
        pass
    try:
        from .hooks import register_ctf_tool_hooks
        register_ctf_tool_hooks()
    except Exception:  # noqa: BLE001 — hook 注册失败只降级安全检查
        pass

    # 轮数上限：环境变量显式覆盖（CLI --max-turns）才限制；未设/0 =
    # 不限轮数（sys.maxsize，AIAgent 库默认无限迭代语义）——题目一直
    # 解到出 flag 为止。（forkserver 子进程继承父进程环境，故 solve-all
    # 设置的变量可见）
    max_turns = resolve_max_turns_from_env()

    log_path = work_dir / SOLVER_LOG
    old_cwd = os.getcwd()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        os.chdir(work_dir)
        # 证据流 + 镜像：见 solver_evidence_stream 的文档。None = 落盘失败，
        # 退回原流照跑（与「证据缺失不阻断求解」一致）。
        with solver_evidence_stream(work_dir) as log:
            if log is not None:
                sys.stdout, sys.stderr = log, log
            code = run_agent_main(
                query=query,
                mode="ctf",
                model=project.model or "",
                max_turns=max_turns,
            )
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        os.chdir(old_cwd)
    # None 原样上交：让 _solver_result_from_code 的 ``is None`` 失败判定
    # 真正生效（``int(code or 0)`` 会把 None 折叠成 0，初始化失败被误报成功）
    return None if code is None else int(code)


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
    # 初始化结构化轨迹（延迟导入避免循环依赖）
    from .trace import SolverTrace, TraceEntry

    solver_id = project.challenge_id if hasattr(project, "challenge_id") and project.challenge_id else f"pid-{os.getpid()}"
    solver_trace = SolverTrace(
        solver_id=solver_id,
        model=model or "",
        start_time=time.time(),
    )
    solver_trace.add_entry(TraceEntry(
        timestamp=time.time(),
        round=0,
        action="worker_start",
        tool_call=f"solver_worker({project.challenge_id}, {model})",
    ))
    # 初始化上下文管理器（F4-008：上下文紧凑管理）
    from .planner import ContextManager, TurnRole

    context = ContextManager(f"solver_{solver_id}", max_tokens=15000)
    context.set_system_prompt(f"Solve CTF challenge: {project.challenge_id} ({project.category})")
    context.add_turn(TurnRole.USER, f"Starting solver for {project.challenge_id}")
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        os.environ["FULILIAN_CTF_MODE"] = "1"
        os.environ["FULILIAN_CTF_WORK_DIR"] = str(Path(work_dir).resolve())
        # F4-001：题目目录自动生成 AGENTS.md（chdir 后由 _load_agents_md 注入）
        try:
            from .agents_md import ensure_agents_md

            ensure_agents_md(work_dir, project)
        except Exception:  # noqa: BLE001 — AGENTS.md 缺失只降级上下文注入，不阻断解题
            pass
        # F4-004：solver 侧默认 workspace-write 沙箱档（hooks 读取）
        os.environ.setdefault(ENV_SANDBOX_MODE, "workspace-write")
        # F4-003/F4-004：worker 进程内注册 CTF hooks（不写 ~/.fulilian 配置）
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

        solver_trace.model = project.model or model

        if solver_impl is None:
            code = _default_solver_impl(project, work_dir, query)
        else:
            code = solver_impl(project, work_dir, query)
        result = _solver_result_from_code(code)
        context.add_turn(TurnRole.TOOL, f"solver finished: exit_code={code}", is_reasoning=True)
        solver_trace.add_entry(TraceEntry(
            timestamp=time.time(),
            round=1,
            action="solver_finished",
            conclusion=f"exit_code={code}",
            tool_output=f"ok={result.ok}, exit_code={result.exit_code}",
        ))
    except SystemExit as e:  # run_agent 以 sys.exit 退出
        # 语义：sys.exit() / sys.exit(0) = 成功（退出码 0）；非 0 整数原样；
        # 字符串消息（sys.exit("msg")）按失败计 1（直接 int() 会二次抛异常）。
        exit_code = 0 if e.code in (None, 0) else (e.code if isinstance(e.code, int) else 1)
        result = SolverResult(ok=(exit_code == 0), exit_code=exit_code, error=f"SystemExit: {e.code}")
        solver_trace.add_entry(TraceEntry(
            timestamp=time.time(),
            round=1,
            action="solver_error",
            error_type="SystemExit",
            conclusion=f"SystemExit: {e.code}",
        ))
    except Exception as e:  # noqa: BLE001 — 进程隔离：任何异常都不影响其他 solver
        result = SolverResult(ok=False, exit_code=1, error=f"{type(e).__name__}: {e}")
        solver_trace.add_entry(TraceEntry(
            timestamp=time.time(),
            round=1,
            action="solver_error",
            error_type=type(e).__name__,
            conclusion=str(e),
        ))

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

    # 记录 flag 结果
    if result.flag:
        context.add_turn(TurnRole.ASSISTANT, f"Flag found: {result.flag[:80]}")
        solver_trace.flag_found = True
        solver_trace.add_entry(TraceEntry(
            timestamp=time.time(),
            round=2,
            action="flag_found",
            flag_found=True,
            tool_output=result.flag[:100],
        ))
    else:
        context.add_turn(TurnRole.ASSISTANT, f"Flag not found: {result.error or 'no_flag'}", is_reasoning=True)
        solver_trace.add_entry(TraceEntry(
            timestamp=time.time(),
            round=2,
            action="flag_not_found",
            flag_found=False,
            error_type=result.error or "no_flag",
        ))

    solver_trace.end_time = time.time()

    try:
        publish_result_fact(project, work_dir, result)
    except Exception:  # noqa: BLE001 — 黑板接线失败不掩盖结果上报
        pass
    try:
        queue.put(shrink_result(result))  # 截断见 shrink_result：超管道缓冲会死锁
    except Exception:  # noqa: BLE001 — 上报失败不掩盖结果
        pass

    # 持久化结构化轨迹
    try:
        trace_path = work_dir / f"trace_{solver_id}.json"
        solver_trace.save(trace_path)
    except Exception:  # noqa: BLE001 — 轨迹保存失败不阻断结果上报
        pass


def switch_solver_model(agent, new_model: str, new_provider: str = "") -> None:
    """运行时切换 solver 模型（F4-005，卡题时换强模型）。

    复用 Fulilian 原生 ``switch_model()``；黑板上下文在题目目录
    blackboard.json 文件里，换模型不受影响。交互会话中直接用原生
    ``/model`` 命令即可（run_agent 内置，等价路径）。
    """
    from agent.agent_runtime_helpers import switch_model

    switch_model(agent, new_model, new_provider)


__all__ = [
    "FLAG_FILENAME",
    "SOLVER_LOG",
    "SOLVER_LOG_MIRROR_ENV",
    "solver_evidence_stream",
    "SolverResult",
    "bootstrap_blackboard",
    "build_solve_query",
    "publish_result_fact",
    "read_flag_file",
    "scan_log_for_flag",
    "solver_worker",
    "switch_solver_model",
    "tee_solver_log",
]
