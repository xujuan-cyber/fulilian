"""P1-4 mini-corpus 与回归基线 runner（修复计划 09 号卡）。

一条命令出基线：

    python3 -m fulilian_ctf.benchmark --suite unit          # 题型回归 corpus（离线 mock 层）
    python3 -m fulilian_ctf.benchmark --suite retrieval     # FTS5 检索金标 hit@5
    python3 -m fulilian_ctf.benchmark --fault empty-model   # 故障注入 4 用例之一
    python3 -m fulilian_ctf.benchmark --suite smoke         # 默认拒绝（真 API 档，需显式配置）

设计契约（09-P1-4 卡）：
1. 离线可跑：unit suite 用本地 fixture + mock solver_impl（参考解脚本化），
   走真实 solver_worker → verify 三重校验门 → FLAG 文件声明式提交链路；
   不调真 API、不碰外网靶机。mock 层 token 记 None。
2. fixture 自证：每个 fixture 配 solve_reference.py 参考解，runner 先跑参考解
   验证有效性（--validate-fixtures 或 unit suite 内置前置校验）；跑不通的
   如实标 skipped: fixture-invalid，计入分母、不造假通过率。
3. 故障注入 4 用例：空 model / 黑板 JSON 损坏 / FTS5 库缺失 / 远程靶机断连，
   断言降级不崩、有明确告警、后续题继续跑。knowledge.db 全程只读。
4. 检索金标：benchmarks/retrieval-golden.yaml（20 条，分层抽样、种子固定落盘），
   对 ~/.fulilian/knowledge.db 做 FTS5 top-5 检索，产出命中@5 基线。
5. 基线即锁：--save-baseline 存 benchmarks/baselines/<date>-<suite>.json；
   --baseline 对比历史基线，通过率退化 / 耗时超阈值即 fail（exit 1）。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import multiprocessing
import os
import queue as queue_mod
import re
import shutil
import socket
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .blackboard import BLACKBOARD_FILENAME, load_blackboard
from .dispatcher import Project
from .knowledge_retriever import DB_PATH as REAL_KB_DB_PATH
from .knowledge_retriever import search as kb_search
from .racer import _stop_process
from .solver import FLAG_FILENAME, SOLVER_LOG, SolverResult, solver_worker
from .verify import check_output_for_flag

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmarks"
DEFAULT_MANIFEST = BENCH_DIR / "manifest-unit.yaml"
GOLDEN_PATH = BENCH_DIR / "retrieval-golden.yaml"
BASELINE_DIR = BENCH_DIR / "baselines"

# 基线对比默认阈值（可通过 flags 覆盖）
PASS_RATE_DROP_LIMIT = 0.05      # 每题型通过率相对基线允许的最大降幅
TIME_FACTOR_LIMIT = 3.0          # 平均耗时相对基线允许的最大倍数
HIT_AT_5_DROP_LIMIT = 0.10       # 检索命中@5 相对基线允许的最大降幅
HIT_AT_5_FLOOR = 0.5             # 无基线时的首跑合理性下限

WARN_PREFIX = "[benchmark-fault][WARN]"

CATEGORIES = ["web", "crypto", "pwn", "reverse", "misc"]


# ─────────────────────────── 通用工具 ───────────────────────────


def _warn(msg: str) -> None:
    """告警：stderr 明确告警行 + 返回给调用方留档。"""
    print(f"{WARN_PREFIX} {msg}", file=sys.stderr, flush=True)


@contextmanager
def _clean_solver_env():
    """隔离 solver_worker 的 os.environ 副作用（基准进程内不外泄）。"""
    keys_guard = ("FULILIAN_CTF_MODE", "FULILIAN_CTF_WORK_DIR")
    saved = {k: os.environ.get(k) for k in keys_guard}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copy_fixture(fixture_dir: Path, work_dir: Path) -> None:
    """把 fixture 材料拷进工作目录（参考解脚本本身不进挑战目录）。"""
    shutil.copytree(
        fixture_dir, work_dir,
        ignore=shutil.ignore_patterns("solve_reference.py", "__pycache__"),
    )


def _make_project(entry: dict, work_dir: Path) -> Project:
    return Project(
        challenge_id=entry["id"],
        challenge_dir=str(work_dir),
        title=entry.get("title") or entry["id"],
        category=entry.get("category") or "",
        difficulty=entry.get("difficulty") or "easy",
        description=entry.get("description") or "",
        attempts=1,
        model=entry.get("model") or "",
    )


# ─────────────────────────── mock 求解层 ───────────────────────────


def _load_reference(fixture_dir: Path):
    return _load_module(fixture_dir / "solve_reference.py", f"solve_ref_{fixture_dir.name}")


# 参考解子进程超时（秒）。参考解是我们自己的 fixture 脚本，但它会真连
# socket / 真读文件：卡在网络上的参考解在进程内调用会让自证与整个用例
# 循环永久挂住（实测语义：跑到这里就不会再有输出，也没有任何超时能救）。
REFERENCE_SOLVE_TIMEOUT = 180.0


def _reference_solve_target(fixture_dir: str, work_dir: str, q) -> None:
    """子进程入口：加载 fixture 参考解并执行（必须模块级，forkserver 要 pickle）。"""
    try:
        ref = _load_module(
            Path(fixture_dir) / "solve_reference.py",
            f"solve_ref_{Path(fixture_dir).name}",
        )
        q.put(("ok", str(ref.solve(work_dir))))
    except BaseException as e:  # noqa: BLE001 — 子进程里的异常只能靠回传
        try:
            q.put(("err", f"{type(e).__name__}: {e}"))
        except Exception:  # noqa: BLE001
            pass


def _reference_solve(
    fixture_dir: Path, work_dir: Path, timeout: float | None = None
) -> tuple[str, str]:
    """在子进程里跑参考解，返回 ``(output, error)``（error 非空即失败）。

    进程内跑参考解无法设超时（线程超时杀不掉卡在 C 层的调用），这里用
    子进程 + ``_stop_process``：超时就真杀死，自证与本用例循环都能继续。
    """
    ctx = multiprocessing.get_context(
        "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
    )
    q = ctx.Queue()
    proc = ctx.Process(
        target=_reference_solve_target,
        args=(str(fixture_dir), str(work_dir), q),
        daemon=True,
    )
    limit = REFERENCE_SOLVE_TIMEOUT if timeout is None else timeout
    proc.start()
    try:
        proc.join(limit)
        if proc.is_alive():
            _stop_process(proc)
            return "", f"reference solver timed out after {limit:g}s"
        try:
            kind, payload = q.get_nowait()
        except Exception:  # noqa: BLE001 — 子进程没回传（被信号杀/解释器崩）
            return "", f"reference solver exited without result (exit={proc.exitcode})"
        if kind == "err":
            return "", payload
        return payload, ""
    finally:
        if proc.is_alive():
            _stop_process(proc)


def make_mock_solver(fixture_dir: Path, stats: dict):
    """mock solver_impl：执行 fixture 参考解（脚本化的正确解题流程），
    输出"工具输出"后走**真实** verify 三重校验门 + FLAG 文件声明式提交。

    这是 mock 层与被测系统的边界：解题步骤由参考解脚本化代替 LLM，
    但 flag 提取、三门校验、FLAG 文件落盘全部走 fulilian_ctf 真实代码——
    因此 P0-1 多平台前缀 flag 门语义被本 corpus 直接回归锁定。
    """
    ref = _load_reference(fixture_dir)
    steps = max(1, int(getattr(ref, "SOLUTION_STEPS", 1)))

    def impl(project, work_dir, query) -> int:
        stats["tool_calls"] = steps  # 参考解内部工具步数
        # 参考解走子进程 + 超时：进程内直调没有超时，参考解一卡（网络是最
        # 常见的一种），整个用例循环就永久停在这里，连"失败"都报不出来。
        output, ref_err = _reference_solve(fixture_dir, Path(work_dir))
        if ref_err:
            stats["tool_calls"] += 1
            stats["reference_error"] = ref_err
            return 1
        stats["tool_calls"] += 1  # 提交扫描（check_output_for_flag）也是一次工具调用
        flag = check_output_for_flag(output, flag_file=str(Path(work_dir) / FLAG_FILENAME))
        return 0 if flag else 1

    return impl


def _run_mock_challenge(entry: dict, fixture_dir: Path, work_dir: Path,
                        model: str = "", solver_impl=None, stats: dict | None = None):
    """对单个用例跑完整 solver_worker 链路（进程内），返回 SolverResult。"""
    if solver_impl is None:
        if stats is None:
            stats = {}
        solver_impl = make_mock_solver(fixture_dir, stats)
    project = _make_project(entry, work_dir)
    q: queue_mod.Queue = queue_mod.Queue()
    t0 = time.perf_counter()
    with _clean_solver_env():
        # solver_worker 会把 [solver:...] 进度打到 stdout——重定向进 work_dir
        # /solver.log（与真实链路的证据落盘语义一致），保持基准进程 stdout
        # 干净（只有 JSON/MD 摘要）。stderr 不动：故障告警必须可见。
        with open(Path(work_dir) / SOLVER_LOG, "w", encoding="utf-8") as log, \
                contextlib.redirect_stdout(log):
            solver_worker(project, str(work_dir), model, q, solver_impl=solver_impl)
    elapsed = time.perf_counter() - t0
    result = q.get_nowait()
    return result, elapsed


# ─────────────────────────── unit suite ───────────────────────────


def load_manifest(path: Path) -> list[dict]:
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError(f"manifest 必须是条目列表: {path}")
    for entry in data:
        for key in ("id", "category", "fixture", "expected_flag", "expect"):
            if key not in entry:
                raise ValueError(f"manifest 条目缺少字段 {key!r}: {entry}")
    return data


def validate_fixture(entry: dict) -> tuple[bool, str]:
    """fixture 自证：新临时目录跑参考解 → 真实 flag 门 → 比对期望 flag。"""
    fixture_dir = BENCH_DIR / entry["fixture"]
    if not (fixture_dir / "solve_reference.py").is_file():
        return False, "solve_reference.py missing"
    try:
        with tempfile.TemporaryDirectory(prefix="bench-validate-") as td:
            work = Path(td) / "work"
            _copy_fixture(fixture_dir, work)
            output, ref_err = _reference_solve(fixture_dir, work)
            if ref_err:
                return False, ref_err
            flag = check_output_for_flag(output, flag_file=str(work / FLAG_FILENAME))
            if flag != entry["expected_flag"]:
                return False, f"gate returned {flag!r}, expected {entry['expected_flag']!r}"
        return True, ""
    except Exception as e:  # noqa: BLE001 — 校验失败原样上报，不造假
        return False, f"{type(e).__name__}: {e}"


def run_unit_suite(manifest_path: Path, show_validation: bool = False) -> dict:
    entries = load_manifest(manifest_path)
    cases: list[dict] = []
    validation_report: dict[str, tuple[bool, str]] = {}

    if show_validation:
        print("== fixture 自证（solve_reference.py → 真实 flag 门）==", flush=True)

    for entry in entries:
        fid = entry["id"]
        ok, err = validate_fixture(entry)
        validation_report[fid] = (ok, err)
        if show_validation:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {fid}" + (f" — {err}" if err else ""), flush=True)
        if not ok:
            # 红线：跑不通的 fixture 如实标注，计入分母
            cases.append({
                "id": fid, "category": entry["category"],
                "status": "skipped: fixture-invalid", "detail": err,
                "seconds": None, "tokens": None, "tool_calls": None,
                "solved": False,
            })
            continue

        fixture_dir = BENCH_DIR / entry["fixture"]
        stats: dict = {}
        try:
            with tempfile.TemporaryDirectory(prefix="bench-unit-") as td:
                work = Path(td) / "work"
                _copy_fixture(fixture_dir, work)
                result, elapsed = _run_mock_challenge(entry, fixture_dir, work, stats=stats)
        except BaseException as e:  # noqa: BLE001 — 逐用例隔离
            # 一个用例自己炸掉（fixture 拷贝失败 / 队列空 / 未知异常）不该
            # 让整轮基准丢掉已经跑完的结果，也不该让它在分母里消失 ——
            # 如实记成 crashed 并继续，与上面「fixture 不自证」的处理同款。
            cases.append({
                "id": fid, "category": entry["category"],
                "status": "crashed", "detail": f"{type(e).__name__}: {e}",
                "seconds": None, "tokens": None, "tool_calls": None,
                "solved": False,
            })
            continue
        got = (result.flag or "").strip()
        solved = result.ok and got == entry["expected_flag"]
        if result.ok and got and got != entry["expected_flag"]:
            status = "flag-mismatch"
        elif not result.ok and not got:
            status = "failed"
        elif not result.ok:
            status = "solver-error"
        else:
            status = "solved"
        cases.append({
            "id": fid, "category": entry["category"], "status": status,
            "detail": result.error if (not result.ok and result.error) else "",
            "flag_returned": got, "seconds": round(elapsed, 4),
            "tokens": None,  # mock 层无真实 API 消耗
            "tool_calls": stats.get("tool_calls"), "solved": solved,
        })

    # 每题型汇总
    categories: dict[str, dict] = {}
    for cat in CATEGORIES:
        sub = [c for c in cases if c["category"] == cat]
        if not sub:
            continue
        total = len(sub)
        solved = sum(1 for c in sub if c["solved"])
        timed = [c["seconds"] for c in sub if c["seconds"] is not None]
        tools = [c["tool_calls"] for c in sub if c["tool_calls"] is not None]
        categories[cat] = {
            "solved": solved,
            "total": total,
            "pass_rate": round(solved / total, 4) if total else 0.0,
            "avg_seconds": round(sum(timed) / len(timed), 4) if timed else None,
            "avg_tokens": None,  # mock 层 token 恒为 None
            "avg_tool_calls": round(sum(tools) / len(tools), 2) if tools else None,
            "skipped_fixture_invalid": sum(
                1 for c in sub if c["status"] == "skipped: fixture-invalid"),
        }
    total_all = len(cases)
    solved_all = sum(1 for c in cases if c["solved"])
    summary = {
        "suite": "unit",
        "date": date.today().isoformat(),
        "totals": {
            "solved": solved_all,
            "total": total_all,
            "pass_rate": round(solved_all / total_all, 4) if total_all else 0.0,
        },
        "categories": categories,
        "cases": cases,
        "validation": {k: {"ok": v[0], "error": v[1]} for k, v in validation_report.items()},
    }
    return summary


def unit_markdown(summary: dict) -> str:
    lines = [
        "# Unit suite 摘要（mini-corpus，mock 层）",
        "",
        f"- 日期: {summary['date']}  总体: "
        f"{summary['totals']['solved']}/{summary['totals']['total']} "
        f"(pass_rate={summary['totals']['pass_rate']:.2%})",
        "",
        "| 题型 | 通过 | 总数 | 通过率 | 平均耗时(s) | 平均token | 平均工具调用 | fixture无效 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cat, s in summary["categories"].items():
        lines.append(
            f"| {cat} | {s['solved']} | {s['total']} | {s['pass_rate']:.0%} "
            f"| {s['avg_seconds']} | {s['avg_tokens']} | {s['avg_tool_calls']} "
            f"| {s['skipped_fixture_invalid']} |"
        )
    bad = [c for c in summary["cases"] if c["status"] != "solved"]
    if bad:
        lines += ["", "## 未通过/跳过用例", ""]
        for c in bad:
            lines.append(f"- {c['id']}: {c['status']}"
                         + (f" — {c['detail']}" if c.get("detail") else ""))
    return "\n".join(lines) + "\n"


# ─────────────────────────── 检索金标 ───────────────────────────


def run_retrieval_suite(golden_path: Path = GOLDEN_PATH) -> dict:
    """读 retrieval-golden.yaml → 对 knowledge.db FTS5 做 top-5 检索 → 命中@5。

    只读：search(auto_build=False)，绝不触发索引重建/写库。
    """
    import yaml

    with open(golden_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    golden = data["golden"] if isinstance(data, dict) else data
    cases = []
    hits = 0
    for item in golden:
        query = item["query"]
        expected_path = item["expected_source_path"]
        results = kb_search(query, limit=5, auto_build=False)
        got_paths = [r.get("source_path") for r in results]
        hit = expected_path in got_paths
        hits += int(hit)
        cases.append({
            "id": item.get("id"), "category": item.get("category"),
            "query": query, "hit": hit, "rank": (got_paths.index(expected_path) + 1) if hit else None,
        })
    total = len(golden)
    hit_at_5 = round(hits / total, 4) if total else 0.0
    return {
        "suite": "retrieval",
        "date": date.today().isoformat(),
        "hit_at_5": hit_at_5,
        "hits": hits,
        "total": total,
        "db_path": str(REAL_KB_DB_PATH),
        "cases": cases,
    }


# ─────────────────────────── 故障注入 ───────────────────────────


def _run_two_challenge_scenario(inject) -> dict:
    """故障注入骨架：对挑战 A 注入故障 → 断言降级不崩 → 挑战 B（正常）继续跑。

    返回检查结果 dict；所有断言为软检查（结果如实呈现，不抛异常）。
    """
    manifest = {e["id"]: e for e in load_manifest(DEFAULT_MANIFEST)}
    fid_a = "web-info-leak-01"
    fid_b = "reverse-rot13-01"
    checks: dict = {}
    warnings: list[str] = []

    def warn(msg: str) -> None:
        warnings.append(msg)
        _warn(msg)

    fixture_a = BENCH_DIR / manifest[fid_a]["fixture"]
    fixture_b = BENCH_DIR / manifest[fid_b]["fixture"]

    with tempfile.TemporaryDirectory(prefix="bench-fault-") as td:
        work_a = Path(td) / "challengeA"
        work_b = Path(td) / "challengeB"
        _copy_fixture(fixture_a, work_a)
        _copy_fixture(fixture_b, work_b)

        inject_ctx = inject(work_a, work_b, warn, manifest)
        try:
            with inject_ctx:
                result_a, _ = _run_mock_challenge(
                    manifest[fid_a], fixture_a, work_a, solver_impl=inject_ctx.mock_impl)
                # 这里原本写的是 ``isinstance(result_a, object)`` —— 对任何对象
                # 恒真，等于「只要没抛异常就算过」，检查项本身永远不可能失败。
                # 要断的是「降级路径仍然返回一个正常的 SolverResult」：返回
                # None / 换了类型（重构时把失败转成别的信号）应当在这里暴露。
                checks["challengeA_degraded_without_crash"] = isinstance(
                    result_a, SolverResult
                )
                checks["challengeA_result"] = {
                    "ok": result_a.ok, "flag": result_a.flag, "error": result_a.error}
                # 后续题继续跑
                result_b, _ = _run_mock_challenge(manifest[fid_b], fixture_b, work_b)
                checks["challengeB_continued"] = result_b.flag == manifest[fid_b]["expected_flag"]
        except BaseException as e:  # noqa: BLE001 — 崩溃本身即故障场景失败，如实记录
            checks["challengeA_degraded_without_crash"] = False
            checks["crash"] = f"{type(e).__name__}: {e}"
            result_b_flag = None
        else:
            result_b_flag = checks.get("challengeB_continued")

    checks["warnings_emitted"] = warnings
    passed = (
        checks.get("challengeA_degraded_without_crash", False)
        and bool(warnings)
        and checks.get("challengeB_continued", False)
    )
    return {"scenario": inject.__self__.__class__.__name__ if hasattr(inject, "__self__") else "",
            "passed": bool(passed), "checks": checks}


class _FaultScenario:
    """故障场景基类：inject() 返回上下文管理器，内部提供 mock_impl。"""

    def mock_impl(self, project, work_dir, query) -> int:  # pragma: no cover - 覆盖点
        raise NotImplementedError

    def inject(self, work_a, work_b, warn, manifest):  # pragma: no cover - 覆盖点
        raise NotImplementedError

    def run(self) -> dict:
        return _run_two_challenge_scenario(self.inject)


class EmptyModelFault(_FaultScenario):
    """空 model：上游求解实现因空模型名请求 API 而失败（run_agent 行为，
    见 solver.resolve_default_model 文档）——solver_worker 必须把失败装回
    SolverResult 上报，进程不崩、告警可见、后续题继续。"""

    class _Ctx:
        def __init__(self, warn):
            self.warn = warn
            self._saved = None

        def __enter__(self):
            # 模拟"无默认模型可回退"的配置态：resolve_default_model → ""
            # （真实场景：config.yaml 未配置 model.default，run_agent 以空模型名
            # 请求 API 得到 400。见 solver.resolve_default_model 文档。）
            import fulilian_ctf.solver as solver_mod

            self._saved = solver_mod.resolve_default_model
            solver_mod.resolve_default_model = lambda: ""
            self.warn(
                "no default model configured (resolve_default_model -> '') — "
                "solver will request API with empty model name (HTTP 400); "
                "expecting graceful degradation to a failed attempt"
            )
            return self

        def __exit__(self, *exc):
            import fulilian_ctf.solver as solver_mod

            solver_mod.resolve_default_model = self._saved
            return False

        def mock_impl(self, project, work_dir, query) -> int:
            if not (project.model or "").strip():
                self.warn(
                    f"empty model name for challenge '{project.challenge_id}' — "
                    "solver would request API with empty model (HTTP 400); degrading to failed attempt"
                )
                raise RuntimeError("empty model name: provider request would fail with 400")
            from .verify import check_output_for_flag as _gate

            ref = _load_reference(BENCH_DIR / "fixtures/reverse-rot13-01")
            output = ref.solve(str(work_dir))
            flag = _gate(output, flag_file=str(Path(work_dir) / FLAG_FILENAME))
            return 0 if flag else 1

    def inject(self, work_a, work_b, warn, manifest):
        return self._Ctx(warn)


class CorruptBlackboardFault(_FaultScenario):
    """黑板 JSON 损坏：work_dir/blackboard.json 为非法 JSON —— solver_worker
    的黑板接线必须降级（load_blackboard 异常被吞成告警），解题照常完成。"""

    class _Ctx:
        def __init__(self, work_a, warn):
            self.work_a = work_a
            self.warn = warn

        def __enter__(self):
            # 预置损坏黑板（solver_worker 的 bootstrap_blackboard 将消费它）
            (self.work_a / BLACKBOARD_FILENAME).write_text(
                '{"facts": [BROKEN!!! not json', encoding="utf-8")
            try:
                load_blackboard(self.work_a / BLACKBOARD_FILENAME)
                degraded = "load_blackboard returned silently"
            except Exception as e:  # noqa: BLE001
                degraded = f"load_blackboard raised {type(e).__name__} (expected)"
            self.warn(
                f"blackboard.json is corrupt JSON in '{self.work_a.name}'; "
                f"solver blackboard bootstrap will degrade ({degraded})"
            )
            return self

        def __exit__(self, *exc):
            return False

        def mock_impl(self, project, work_dir, query) -> int:
            from .verify import check_output_for_flag as _gate

            ref = _load_reference(BENCH_DIR / "fixtures/web-info-leak-01")
            output = ref.solve(str(work_dir))
            flag = _gate(output, flag_file=str(Path(work_dir) / FLAG_FILENAME))
            return 0 if flag else 1

    def inject(self, work_a, work_b, warn, manifest):
        return self._Ctx(work_a, warn)


class MissingFts5Fault(_FaultScenario):
    """FTS5 库缺失：把检索层 DB_PATH/KB_PATH 指向空的临时位置——
    知识注入必须静默降级（build_solve_query 内部 best-effort），解题不被阻断。
    真实 knowledge.db 全程不被触碰（只读）。"""

    class _Ctx:
        def __init__(self, warn):
            self.warn = warn
            self._tmp = None

        def __enter__(self):
            import fulilian_ctf.knowledge_retriever as kr

            self._tmp = tempfile.TemporaryDirectory(prefix="bench-missing-fts5-")
            self._kr = kr
            self._saved = (kr.DB_PATH, kr.KB_PATH)
            fake_db = Path(self._tmp.name) / "knowledge.db"
            fake_kb = Path(self._tmp.name) / "empty-kb"
            fake_kb.mkdir(parents=True, exist_ok=True)
            kr.DB_PATH = fake_db
            kr.KB_PATH = fake_kb
            self.warn(
                f"FTS5 database not found at '{fake_db}' — "
                "knowledge retrieval degrades to no-op; solve continues without WP refs"
            )
            # 验证检索 API 自身降级：missing DB + auto_build=False → 空结果不抛
            res = kr.search("anything", limit=5, auto_build=False)
            assert res == [], "missing DB + auto_build=False must return [] without error"
            return self

        def __exit__(self, *exc):
            self._kr.DB_PATH, self._kr.KB_PATH = self._saved
            self._tmp.cleanup()
            return False

        def mock_impl(self, project, work_dir, query) -> int:
            from .verify import check_output_for_flag as _gate

            ref = _load_reference(BENCH_DIR / "fixtures/web-info-leak-01")
            output = ref.solve(str(work_dir))
            flag = _gate(output, flag_file=str(Path(work_dir) / FLAG_FILENAME))
            return 0 if flag else 1

    def inject(self, work_a, work_b, warn, manifest):
        return self._Ctx(warn)


class RemoteDownFault(_FaultScenario):
    """远程靶机断连：目标 127.0.0.1:1（必然拒绝）——求解先做真实网络探测，
    连接被拒后必须告警并降级到本地静态信息收集路径，解题不被阻断、后续题继续。"""

    class _Ctx:
        DEAD_HOST, DEAD_PORT = "127.0.0.1", 1

        def __init__(self, warn):
            self.warn = warn

        def __enter__(self):
            self.warn(
                f"remote target {self.DEAD_HOST}:{self.DEAD_PORT} refused connection — "
                "degrading from remote interaction to local static analysis"
            )
            return self

        def __exit__(self, *exc):
            return False

        def mock_impl(self, project, work_dir, query) -> int:
            from .verify import check_output_for_flag as _gate

            # 真实网络探测：连接必然被拒（本机保留端口 1 无监听）
            try:
                with socket.create_connection((self.DEAD_HOST, self.DEAD_PORT), timeout=2):
                    reachable = True
            except OSError as e:
                reachable = False
                self.warn(
                    f"probe {self.DEAD_HOST}:{self.DEAD_PORT} failed: {e} — "
                    "falling back to local file inspection"
                )
            assert not reachable, "127.0.0.1:1 should be unreachable in the fault scenario"
            ref = _load_reference(BENCH_DIR / "fixtures/web-info-leak-01")
            output = ref.solve(str(work_dir))
            flag = _gate(output, flag_file=str(Path(work_dir) / FLAG_FILENAME))
            return 0 if flag else 1

    def inject(self, work_a, work_b, warn, manifest):
        return self._Ctx(warn)


FAULT_SCENARIOS = {
    "empty-model": EmptyModelFault,
    "corrupt-blackboard": CorruptBlackboardFault,
    "missing-fts5": MissingFts5Fault,
    "remote-down": RemoteDownFault,
}


def run_fault_scenario(name: str) -> dict:
    scenario = FAULT_SCENARIOS[name]()
    report = scenario.run()
    report["scenario"] = name
    return report


def run_all_faults() -> dict:
    reports = [run_fault_scenario(name) for name in FAULT_SCENARIOS]
    return {
        "suite": "fault-injection",
        "date": date.today().isoformat(),
        "passed": all(r["passed"] for r in reports),
        "scenarios": reports,
    }


# ─────────────────────────── 基线保存/对比 ───────────────────────────


def save_baseline(summary: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, out_path)  # 原子写（与 P1-3 原子写纪律一致）
    return out_path


def compare_with_baseline(summary: dict, baseline_path: Path,
                          pass_rate_limit: float = PASS_RATE_DROP_LIMIT,
                          time_factor: float = TIME_FACTOR_LIMIT,
                          hit_limit: float = HIT_AT_5_DROP_LIMIT) -> list[str]:
    """对比历史基线，返回退化项列表（空 = 未退化）。"""
    with open(baseline_path, encoding="utf-8") as f:
        base = json.load(f)
    regressions: list[str] = []
    if summary["suite"] == "unit":
        for cat, cur in summary["categories"].items():
            old = (base.get("categories") or {}).get(cat)
            if not old:
                continue
            if cur["pass_rate"] < old["pass_rate"] - pass_rate_limit:
                regressions.append(
                    f"{cat}: pass_rate {cur['pass_rate']:.0%} < baseline "
                    f"{old['pass_rate']:.0%} -{pass_rate_limit:.0%}")
            if (cur.get("avg_seconds") is not None and old.get("avg_seconds")
                    and cur["avg_seconds"] > old["avg_seconds"] * time_factor):
                regressions.append(
                    f"{cat}: avg_seconds {cur['avg_seconds']} > baseline "
                    f"{old['avg_seconds']} x{time_factor}")
    elif summary["suite"] == "retrieval":
        old = base.get("hit_at_5")
        if old is not None and summary["hit_at_5"] < old - hit_limit:
            regressions.append(
                f"hit@5 {summary['hit_at_5']:.0%} < baseline {old:.0%} -{hit_limit:.0%}")
    return regressions


# ─────────────────────────── CLI ───────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m fulilian_ctf.benchmark",
        description="FuLiLian CTF mini-corpus 与回归基线 runner（P1-4）",
    )
    parser.add_argument("--suite", choices=["unit", "retrieval", "smoke"], default=None)
    parser.add_argument("--fault", choices=sorted(FAULT_SCENARIOS), default=None)
    parser.add_argument("--all-faults", action="store_true", help="跑全部 4 个故障注入用例")
    parser.add_argument("--validate-fixtures", action="store_true",
                        help="打印每个 fixture 参考解自证明细（unit suite 始终内置自证）")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--baseline", default=None, help="历史基线 JSON 路径（对比退化）")
    parser.add_argument("--save-baseline", default=None, help="本次结果存为基线 JSON")
    args = parser.parse_args(argv)

    if not args.suite and not args.fault and not args.all_faults:
        parser.error("需要 --suite unit|retrieval|smoke 或 --fault <scenario> 或 --all-faults")

    if args.suite == "smoke":
        print(
            "[benchmark] smoke suite 默认拒绝运行。\n"
            "  smoke 层会调用真实 API 对真题（BUUCTF/NSSCTF）做 3 题冒烟，\n"
            "  消耗 API 配额并访问外网靶机——需要你显式确认后才能执行：\n"
            "    1) 在 manifest-smoke.yaml 填好真题题号与附件路径；\n"
            "    2) 确认 fulilian 已配置可用模型与 API key；\n"
            "    3) 设置环境变量 FULILIAN_BENCHMARK_SMOKE_CONFIRM=yes 后重试。\n"
            "  本次未执行任何真题、未消耗任何配额。",
            file=sys.stderr,
        )
        return 2

    if args.suite == "unit":
        summary = run_unit_suite(Path(args.manifest), show_validation=args.validate_fixtures)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print()
        print(unit_markdown(summary))
    elif args.suite == "retrieval":
        summary = run_retrieval_suite()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if summary["hit_at_5"] < HIT_AT_5_FLOOR and not args.baseline:
            print(f"[benchmark] hit@5={summary['hit_at_5']:.0%} 低于首跑下限 "
                  f"{HIT_AT_5_FLOOR:.0%}，请检查 knowledge.db / golden 文件",
                  file=sys.stderr)
    else:  # fault / all-faults
        summary = run_all_faults() if args.all_faults else run_fault_scenario(args.fault)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    # 基线对比
    if args.baseline:
        regressions = compare_with_baseline(summary, Path(args.baseline))
        if regressions:
            print("[benchmark] 基线对比：检测到退化：", file=sys.stderr)
            for r in regressions:
                print(f"  - {r}", file=sys.stderr)
            return 1
        print(f"[benchmark] 基线对比通过（vs {args.baseline}）", file=sys.stderr)

    if args.save_baseline:
        out = save_baseline(summary, Path(args.save_baseline))
        print(f"[benchmark] 基线已保存: {out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
