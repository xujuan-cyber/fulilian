#!/usr/bin/env python3
"""控制通道手工验证样板：建库 → 造任务 → worker 进程 poll → 控制进程 post。

阶段 3a 只做 ``control.py`` 的**存储侧**（决议 §一：不跑任务、不发信号、
不杀进程），所以这里的两个子进程只演示"指令能不能可靠送达"：

* **worker 进程**：按 heartbeat 节奏 ``poll`` 自己的任务，取到指令就 ``ack``；
* **控制进程**：从另一条连接 ``request_stop`` / ``request_steer``。

``stop`` 之后 ``RUNNING → CANCELLED`` 的收敛由后续阶段的承载层在迭代边界
完成，本演示不越界——库里只会看到 ``cancel_requested_at`` 被置上。

跑法::

    ./venv/bin/python scripts/demo_control.py
    ./venv/bin/python scripts/demo_control.py --keep    # 保留临时库便于手查
    ./venv/bin/python scripts/demo_control.py --polls 200 --interval 0.02

输出是一段 JSON：控制进程投递了什么、worker 收到了什么、库内最终状态。
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.orchestration.contracts import TaskCard  # noqa: E402
from agent.orchestration.control import Control  # noqa: E402
from agent.orchestration.schema import configure_connection  # noqa: E402
from agent.orchestration.store import Store  # noqa: E402

#: 控制进程等 worker 先跑起来再投递，避免"指令早就到了、worker 还没开始 poll"。
CONTROL_DELAY_SECONDS = 0.2

#: 演示用的 steer 文本：刻意混中文、换行、引号，方便肉眼确认没被转义坏。
STEER_TEXT = '第 1 行：把结论改成中文。\n第 2 行：保留 "原文引用"。'


def _connect(db_path: str) -> sqlite3.Connection:
    """每个进程各自一条连接；连接对象不能跨进程共享。"""
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    configure_connection(conn, busy_timeout_ms=5000)
    return conn


def _card(task_id: str, out_dir: Path) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"demo {task_id}",
        dod=("worker polls the command",),
        output_path=str(out_dir / f"{task_id}.md"),
    )


def _write_json(path: str, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────────────────────── 子进程


def _worker_process(
    db_path: str,
    targets: tuple[tuple[str, int], ...],
    report_path: str,
    polls: int,
    interval: float,
) -> None:
    """模拟 worker：每个 heartbeat 对每个任务 poll 一次，取到就 ack。

    ``targets`` 是 ``(task_id, lease_epoch)`` —— epoch 是 fencing token，
    poll 必须带上自己的 epoch，否则会捞到上一任 worker 的残留指令。
    """
    seen: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    conn = _connect(db_path)
    try:
        control = Control(conn)
        rounds_used = 0
        satisfied = 0
        for round_index in range(polls):
            rounds_used = round_index + 1
            for task_id, epoch in targets:
                commands = control.poll(task_id, epoch)
                if not commands:
                    continue
                acked = control.ack([command.cmd_id for command in commands])
                for command in commands:
                    seen.append(
                        {
                            "task_id": command.task_id,
                            "kind": command.kind,
                            "payload": command.payload,
                            "cmd_id": command.cmd_id,
                            "lease_epoch": command.lease_epoch,
                            "acked": acked,
                        }
                    )
                satisfied += 1
            if satisfied >= len(targets):
                break
            time.sleep(interval)
        payload = {"polls_used": rounds_used, "commands": seen}
    except BaseException:
        _write_json(report_path, {"error": traceback.format_exc(), "commands": seen})
        raise
    finally:
        conn.close()
    _write_json(report_path, payload)


def _control_process(
    db_path: str,
    stop_task: str,
    steer_task: str,
    steer_text: str,
    report_path: str,
) -> None:
    """模拟控制方：从另一条连接投递一条 stop、一条 steer。"""
    time.sleep(CONTROL_DELAY_SECONDS)
    payload: dict[str, Any]
    conn = _connect(db_path)
    try:
        control = Control(conn)
        stop_outcome = control.request_stop(stop_task)
        steer_cmd_id = control.request_steer(steer_task, steer_text)
        payload = {"stop_outcome": stop_outcome, "steer_cmd_id": steer_cmd_id}
    except BaseException:
        _write_json(report_path, {"error": traceback.format_exc()})
        raise
    finally:
        conn.close()
    _write_json(report_path, payload)


# ────────────────────────────────────────────────────────────────── 主流程


def _task_rows(db_path: str) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT task_id, state, lease_epoch, claimed_by, cancel_requested_at "
            "FROM tasks ORDER BY task_id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def run(polls: int, interval: float, *, keep: bool = False) -> dict[str, Any]:
    workdir = Path(tempfile.mkdtemp(prefix="fulilian-control-demo-"))
    db_path = workdir / "orchestration.db"
    out_dir = workdir / "out"
    out_dir.mkdir()

    # 1) 建库 + 造任务。Store 是库文件的唯一持有者，它顺带把 schema 建好。
    seed = Store(str(db_path), worker_id="demo-worker")
    targets: list[tuple[str, int]] = []
    try:
        for task_id in ("demo-stop", "demo-steer"):
            seed.enqueue(_card(task_id, out_dir))
        # 2) 把两个任务都领走并 start：只有 CLAIMED/RUNNING 才走 D3 的排队分支。
        for expected in ("demo-stop", "demo-steer"):
            claimed = seed.claim("solve", max_wait_seconds=0.0)
            if claimed is None:
                raise RuntimeError(f"没领到 {expected}，演示前提不成立")
            seed.start(claimed.task_id, claimed.lease_epoch)
            targets.append((claimed.task_id, claimed.lease_epoch))
    finally:
        seed.close()  # fork 前必须关：连接不跨进程

    epochs = dict(targets)
    worker_report = str(workdir / "worker.json")
    control_report = str(workdir / "control.json")

    # 3) worker 进程与控制进程并行；两个进程各自开连接。
    ctx = mp.get_context("fork")
    worker = ctx.Process(
        target=_worker_process,
        args=(str(db_path), tuple(targets), worker_report, polls, interval),
        name="demo-worker",
    )
    controller = ctx.Process(
        target=_control_process,
        args=(str(db_path), "demo-stop", "demo-steer", STEER_TEXT, control_report),
        name="demo-control",
    )
    started = time.monotonic()
    worker.start()
    controller.start()
    worker.join(timeout=60)
    controller.join(timeout=60)
    elapsed = time.monotonic() - started

    if worker.is_alive() or controller.is_alive():
        for proc in (worker, controller):
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
        raise RuntimeError("子进程超时未退出，演示失败")

    worker_result = json.loads(Path(worker_report).read_text(encoding="utf-8"))
    control_result = json.loads(Path(control_report).read_text(encoding="utf-8"))
    summary = {
        "db_path": str(db_path) if keep else None,
        "db_kept": keep,
        "worker_exitcode": worker.exitcode,
        "control_exitcode": controller.exitcode,
        "elapsed_seconds": round(elapsed, 3),
        "epochs": epochs,
        "control_sent": control_result,
        "worker_saw": worker_result,
        "final_tasks": _task_rows(str(db_path)),
        "note": (
            "stop 只表达意图：库里 state 仍是 RUNNING、cancel_requested_at 已置；"
            "RUNNING -> CANCELLED 的收敛由后续阶段的承载层在迭代边界完成。"
        ),
    }
    if not keep:
        shutil.rmtree(workdir, ignore_errors=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--polls", type=int, default=100, help="worker 最多 poll 多少轮")
    parser.add_argument(
        "--interval", type=float, default=0.05, help="两轮 poll 之间的间隔（秒）"
    )
    parser.add_argument("--keep", action="store_true", help="保留临时库，便于 sqlite3 手查")
    args = parser.parse_args(argv)

    if args.polls <= 0:
        parser.error("--polls 必须为正整数")
    if args.interval < 0:
        parser.error("--interval 不能为负")

    summary = run(args.polls, args.interval, keep=args.keep)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    ok = (
        summary["worker_exitcode"] == 0
        and summary["control_exitcode"] == 0
        and len(summary["worker_saw"].get("commands", [])) >= 2
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
