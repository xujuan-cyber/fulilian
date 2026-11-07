#!/usr/bin/env python3
"""阶段 2a 并发压测：``Store.claim()`` 的争抢与空队列写放大。

用法::

    python scripts/stress_claim.py --workers 8 --tasks 200 --pool solve
    python scripts/stress_claim.py --workers 15 --duration 60 --idle

stdout 只输出一行 JSON（便于直接贴进验收报告）::

    {"claims": N, "unique_claims": M, "write_txns": K, "duration": S}

两种模式的语义：

* **填充模式**（默认，``--tasks N``）：父进程先入队 N 个任务，再起 W 个**独立
  进程**各自 ``claim(max_wait_seconds=0)`` 直到拿到 ``None``。``claims`` 是全部
  领取记录数，``unique_claims`` 是去重后的 task_id 数。两者相等才说明"每个任务
  恰好被领走一次"——硬门禁①。
* **空队列模式**（``--idle``）：队列为空，W 个进程以 ``max_wait_seconds>0``
  空转 ``--duration`` 秒。``claims`` 必须为 0，``write_txns`` 必须为 0
  （决议 D2：空队列绝不允许开写事务）。

写事务计数窗口的起点是"所有 worker 都已 ``Store()`` 完毕之后"，不是进程启动时。
原因见 ``WriteTxnCounter`` 上方的说明：``Store.__init__`` 会跑一次 ``apply_schema()``，
那是一次窗口外的一次性 DDL 事务，算进来会把硬门禁③的读数污染成 "workers 个数"。

每个进程**自己** ``Store(db_path, worker_id=...)``，不共享 sqlite3 连接——连接
不可跨进程。数据库必须是文件库（``tempfile.mkdtemp()`` 下），``:memory:`` 跨进程
不共享，用了只会得到假绿。
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:  # 允许 `python scripts/stress_claim.py` 直跑
    sys.path.insert(0, str(_REPO_ROOT))

from agent.orchestration.contracts import TaskCard  # noqa: E402
from agent.orchestration.store import Store  # noqa: E402

#: 开事务的语句首关键字。
_BEGIN_KEYWORDS = frozenset({"BEGIN"})
#: 结束事务的语句首关键字。
_END_KEYWORDS = frozenset({"COMMIT", "END", "ROLLBACK"})
#: 会落盘的语句首关键字（DDL 也算：它同样要一个写事务）。
_WRITE_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        "CREATE",
        "DROP",
        "ALTER",
        "VACUUM",
        "REINDEX",
    }
)


class WriteTxnCounter:
    """统计一条 sqlite3 连接上发生了多少次**写事务**。

    挂到 ``conn.set_trace_callback`` 上，按 SQLite 的真实事务边界计数：

    * ``BEGIN`` / ``BEGIN IMMEDIATE`` / ``BEGIN EXCLUSIVE`` → 计 1 次；
    * ``COMMIT`` / ``ROLLBACK`` / ``END`` → 关闭当前事务；
    * 不在显式事务里的 INSERT/UPDATE/DELETE/REPLACE/DDL → 各计 1 次
      （autocommit 下每条写语句自成一个事务）；
    * 只读语句（SELECT / PRAGMA / EXPLAIN）一律不计。

    这是**唯一**能把"空队列时有没有偷偷开写事务"测出来的办法：只看最终数据是
    看不出来的（写空集也不改数据），只看 ``PRAGMA data_version`` 只能知道"变过"，
    不知道"变了几次"。

    已知的保守偏差：``SAVEPOINT`` 不计入 ``_BEGIN_KEYWORDS``，用 savepoint 的
    实现会被**多计**（把 savepoint 内的写语句当成独立事务）。方向是严格的，
    不会让门禁假绿。
    """

    def __init__(self) -> None:
        self.count = 0
        self._in_txn = False
        #: 前若干条写语句，诊断用（例如看清到底是谁在写）。
        self.sample: list[str] = []

    def reset(self) -> None:
        """清零。用于把 ``Store.__init__`` 的建表事务排除在测量窗口之外。"""
        self.count = 0
        self._in_txn = False
        self.sample.clear()

    def __call__(self, sql: str) -> None:
        stripped = sql.strip()
        if not stripped:
            return
        head = stripped.split(None, 1)[0].upper()

        if head in _BEGIN_KEYWORDS:
            if not self._in_txn:
                self.count += 1
                self._in_txn = True
            return

        if head in _END_KEYWORDS:
            self._in_txn = False
            return

        if head in _WRITE_KEYWORDS and not self._in_txn:
            self.count += 1
            if len(self.sample) < 8:
                self.sample.append(stripped[:120])


def find_connection(store: Store) -> sqlite3.Connection:
    """在 ``Store`` 实例上找到它持有的 sqlite3 连接。

    找不到就**抛错**，绝不返回 ``None`` 让调用方静默记 0——那会把硬门禁③变成
    假绿（"没测到" 和 "测到 0" 必须能区分）。
    """
    try:
        values = list(vars(store).values())
    except TypeError:  # __slots__
        values = [getattr(store, name, None) for name in dir(store)]

    for value in values:
        if isinstance(value, sqlite3.Connection):
            return value
    for value in values:
        items = value.values() if isinstance(value, dict) else value
        if isinstance(value, (list, tuple, dict)):
            for item in items:
                if isinstance(item, sqlite3.Connection):
                    return item

    raise RuntimeError(
        "在 Store 实例上找不到 sqlite3.Connection，写事务计数不可用。"
        "若 store.py 每次调用都新建连接，请改用 WAL 帧统计重写本函数；"
        "不要改成返回 0 —— 那会让硬门禁③（空队列零写事务）变成假绿。"
    )


def wal_size(db_path: str | os.PathLike[str]) -> int:
    """``-wal`` 文件字节数；WAL 未启用/未写入时返回 0。

    用作独立于 trace 回调的交叉校验：trace 说 0 次写、WAL 却长大了，说明有
    一条没被插桩的连接在写。
    """
    try:
        return os.path.getsize(f"{os.fspath(db_path)}-wal")
    except OSError:
        return 0


def make_card(task_id: str, out_dir: Path, *, pool: str, **overrides: object) -> TaskCard:
    """造一张能过 ``validate_card`` 的最小任务卡。

    ``output_path`` 必须绝对且规范（``normpath(p) == p``），且同一时刻只能被一个
    非终态任务占用（``idx_tasks_output_active`` 是部分唯一索引）——所以每个
    task_id 一个文件。
    """
    kwargs: dict[str, object] = {
        "task_id": task_id,
        "goal": "stress claim",
        "dod": ("claimed exactly once",),
        "output_path": str(out_dir / f"{task_id}.md"),
        "pool": pool,
    }
    kwargs.update(overrides)
    return TaskCard(**kwargs)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────── 子进程入口


def _write_lines(path: str, lines: list[str]) -> None:
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def worker_claim(db_path: str, worker_id: str, pool: str, log_path: str) -> None:
    """填充模式 worker：抢到没有为止，逐条记录，最后落一条写事务计数。"""
    lines: list[str] = []
    store = Store(db_path, worker_id=worker_id)
    counter = WriteTxnCounter()
    find_connection(store).set_trace_callback(counter)
    try:
        counter.reset()  # 排除 Store.__init__ 的建表事务
        misses = 0
        while misses < 3:
            claimed = store.claim(pool, max_wait_seconds=0.0)
            if claimed is None:
                # D2 第 5 步：输掉竞态时 claim() 也返回 None，与"队列空"不可区分。
                # 单次 None 不足以判定收工，连续 3 次才退出。
                misses += 1
                continue
            misses = 0
            lines.append(
                json.dumps(
                    {
                        "kind": "claim",
                        "task_id": claimed.task_id,
                        "worker_id": claimed.worker_id,
                        "lease_epoch": claimed.lease_epoch,
                        "attempts": claimed.attempts,
                    }
                )
            )
    except BaseException:
        lines.append(json.dumps({"kind": "error", "traceback": traceback.format_exc()}))
        raise
    finally:
        lines.append(json.dumps({"kind": "writes", "worker_id": worker_id, "count": counter.count}))
        _write_lines(log_path, lines)
        store.close()


def worker_idle(
    db_path: str,
    worker_id: str,
    pool: str,
    duration: float,
    claim_wait: float,
    start_event: "mp.synchronize.Event",
    log_path: str,
) -> None:
    """空队列 worker：空转 ``duration`` 秒，报告窗口内的写事务数。"""
    lines: list[str] = []
    store = Store(db_path, worker_id=worker_id)
    counter = WriteTxnCounter()
    find_connection(store).set_trace_callback(counter)
    try:
        if not start_event.wait(timeout=60.0):
            raise RuntimeError("start_event 等待超时：父进程没发令")
        counter.reset()  # 测量窗口起点 = 所有 worker 都建好 Store 之后
        deadline = time.monotonic() + duration
        probes = 0
        unexpected = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            claimed = store.claim(pool, max_wait_seconds=min(claim_wait, max(remaining, 0.01)))
            probes += 1
            if claimed is not None:
                unexpected += 1
                lines.append(json.dumps({"kind": "unexpected_claim", "task_id": claimed.task_id}))
    except BaseException:
        lines.append(json.dumps({"kind": "error", "traceback": traceback.format_exc()}))
        raise
    finally:
        lines.append(
            json.dumps(
                {
                    "kind": "idle",
                    "worker_id": worker_id,
                    "write_txns": counter.count,
                    "probes": probes,
                    "unexpected_claims": unexpected,
                    "sample": counter.sample,
                }
            )
        )
        _write_lines(log_path, lines)
        store.close()


# ────────────────────────────────────────────────────────────────── 编排


def _read_logs(paths: list[str]) -> list[dict]:
    records: list[dict] = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def run_fill(args: argparse.Namespace, db_path: str, work_dir: Path) -> tuple[dict, list[str]]:
    out_dir = work_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = Store(db_path, worker_id="enqueuer")
    try:
        for index in range(args.tasks):
            store.enqueue(make_card(f"task-{index:04d}", out_dir, pool=args.pool))
    finally:
        store.close()

    ctx = mp.get_context("fork")
    log_paths = [str(work_dir / f"claim-{i:02d}.jsonl") for i in range(args.workers)]
    procs = [
        ctx.Process(
            target=worker_claim,
            args=(db_path, f"w{i:02d}", args.pool, log_paths[i]),
            name=f"claim-w{i:02d}",
        )
        for i in range(args.workers)
    ]

    started = time.monotonic()
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()
    elapsed = time.monotonic() - started

    problems = [f"{p.name}: exitcode={p.exitcode}" for p in procs if p.exitcode != 0]
    records = _read_logs(log_paths)
    for record in records:
        if record.get("kind") == "error":
            problems.append(record["traceback"])

    claims = [r for r in records if r.get("kind") == "claim"]
    write_txns = sum(r.get("count", 0) for r in records if r.get("kind") == "writes")
    result = {
        "claims": len(claims),
        "unique_claims": len({r["task_id"] for r in claims}),
        "write_txns": write_txns,
        "duration": round(elapsed, 3),
    }
    if len(claims) != args.tasks:
        problems.append(f"领取记录 {len(claims)} 条 != 入队 {args.tasks} 个任务")
    return result, problems


def run_idle(args: argparse.Namespace, db_path: str, work_dir: Path) -> tuple[dict, list[str]]:
    # 先把库建好（窗口外），否则 15 个 worker 会同时跑 apply_schema，建表事务
    # 会被算进测量窗口。
    Store(db_path, worker_id="bootstrap").close()

    observer = sqlite3.connect(db_path, isolation_level=None)
    try:
        data_version_before = observer.execute("PRAGMA data_version").fetchone()[0]
        wal_before = wal_size(db_path)

        ctx = mp.get_context("fork")
        start_event = ctx.Event()
        log_paths = [str(work_dir / f"idle-{i:02d}.jsonl") for i in range(args.workers)]
        procs = [
            ctx.Process(
                target=worker_idle,
                args=(
                    db_path,
                    f"w{i:02d}",
                    args.pool,
                    args.duration,
                    args.claim_wait,
                    start_event,
                    log_paths[i],
                ),
                name=f"idle-w{i:02d}",
            )
            for i in range(args.workers)
        ]
        for proc in procs:
            proc.start()
        started = time.monotonic()
        start_event.set()
        for proc in procs:
            proc.join()
        elapsed = time.monotonic() - started

        data_version_after = observer.execute("PRAGMA data_version").fetchone()[0]
        wal_after = wal_size(db_path)
    finally:
        observer.close()

    problems = [f"{p.name}: exitcode={p.exitcode}" for p in procs if p.exitcode != 0]
    records = _read_logs(log_paths)
    for record in records:
        if record.get("kind") == "error":
            problems.append(record["traceback"])

    idle = [r for r in records if r.get("kind") == "idle"]
    write_txns = sum(r["write_txns"] for r in idle)
    unexpected = sum(r["unexpected_claims"] for r in idle)
    probes = sum(r["probes"] for r in idle)

    if write_txns:
        problems.append(f"空队列窗口内出现 {write_txns} 次写事务（D2 要求 0）")
    if wal_after != wal_before:
        problems.append(f"WAL 在空队列窗口内增长 {wal_after - wal_before} 字节（有未插桩的连接在写？）")
    if data_version_after != data_version_before:
        problems.append("PRAGMA data_version 在空队列窗口内变化（有未插桩的连接在写）")
    if unexpected:
        problems.append(f"空队列里竟然领到了 {unexpected} 个任务")

    result = {
        "claims": 0,
        "unique_claims": 0,
        "write_txns": write_txns,
        "duration": round(elapsed, 3),
    }
    print(
        f"# idle: workers={args.workers} probes={probes} "
        f"wal_delta={wal_after - wal_before} data_version_delta={data_version_after - data_version_before}",
        file=sys.stderr,
    )
    return result, problems


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=8, help="并发进程数")
    parser.add_argument("--tasks", type=int, default=200, help="填充模式下入队的任务数")
    parser.add_argument("--duration", type=float, default=0.0, help="空队列模式下空转的秒数")
    parser.add_argument("--idle", action="store_true", help="空队列写放大模式")
    parser.add_argument("--pool", default="solve", help="领取的池名")
    parser.add_argument("--claim-wait", type=float, default=1.0, help="空队列模式下单次 claim 的最长等待秒数")
    parser.add_argument("--keep", action="store_true", help="保留临时库目录（默认删除）")
    args = parser.parse_args(argv)

    if args.workers < 1:
        parser.error("--workers 必须 >= 1")
    if args.idle and args.duration <= 0:
        parser.error("--idle 需要 --duration > 0")
    if not args.idle and args.tasks < 1:
        parser.error("--tasks 必须 >= 1")
    if args.idle and args.tasks != 200:
        parser.error("--idle 与 --tasks 互斥：空队列模式下不能入队")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    work_dir = Path(tempfile.mkdtemp(prefix="fulilian-stress-"))
    db_path = str(work_dir / "orchestration.db")
    print(f"# db={db_path}", file=sys.stderr)

    try:
        result, problems = (run_idle if args.idle else run_fill)(args, db_path, work_dir)
    except BaseException:
        traceback.print_exc()
        return 2

    for problem in problems:
        print(f"# PROBLEM: {problem}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))

    if not args.keep:
        shutil.rmtree(work_dir, ignore_errors=True)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
