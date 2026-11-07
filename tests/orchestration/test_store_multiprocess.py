"""阶段 2a 并发验收：``Store`` 在多进程下的领取、判死、回收与吸收。

覆盖 ``docs/design/orchestration-phase2a-store-decisions.md`` §四 的四条
（②「被 fence 的写回失败」由 ``test_store.py`` 覆盖，这里不重复）：

===========================  ============================================
①  ``test_concurrent_claim_single_winner``        8 进程抢同一批任务，每任务恰好成功一次
③  ``test_idle_queue_write_amplification``        空队列写放大（60 秒等价折算）
④  ``test_sigkill_then_patrol_and_redispatch``    kill -9 后重启可接管
⑤  ``test_end_to_end_absorption``                 端到端吸收态
===========================  ============================================

三条硬约束，违反其中任何一条都会让本文件变成假绿：

1. **必须用文件库**。``:memory:`` 不跨进程共享，每个子进程会各自拿到一个空库，
   于是"8 个进程各领各的"也能全绿。库一律建在 ``tmp_path`` 下。
2. **每个进程自己 ``Store(path, worker_id=...)``**。sqlite3 连接不可跨进程传递；
   父进程在 fork 前把连接关掉，子进程里重开。
3. **断言不放宽**。门禁是决议的一部分，实现不达标就报，不改测试迁就实现。
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import sqlite3
import sys
import time
import traceback
from pathlib import Path

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.store import Store

# 写事务计数与 stress_claim.py 共用同一份实现，避免"压测脚本量到 0、单测量到 3"
# 这种两边口径不一致的假绿。
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from stress_claim import WriteTxnCounter, find_connection, wal_size  # noqa: E402

#: 全部用例都依赖 ``fork`` + ``SIGKILL`` 的进程语义。
pytestmark = pytest.mark.linux_only

#: ① 的规模：8 个进程抢 120 个任务。任务数远大于进程数，才有真正的争抢。
CLAIM_WORKERS = 8
CLAIM_TASKS = 120

#: ③ 的规模：15 个 worker 空转。
IDLE_WORKERS = 15

#: ③ 的观察窗口。计划要求「15 worker × 10 分钟，写事务 < 100」，10 分钟在单测里
#: 不可接受，故按时间线性折算到 60 秒（10 分钟的 1/10）：
#:
#:     60 秒阈值 = 100 次 / (600 秒 / 60 秒) = 100 / 10 = 10 次
#:
#: 折算成立的前提是**写事务速率在窗口内近似恒定**：空队列稳态下 claim 只做只读
#: 探测，没有任何随时间增长的状态（无重试队列、无退避表持久化），所以 60 秒里
#: 的速率可以直接外推。若实现把"每次探测"变成"每次写一行审计"，速率同样恒定，
#: 只是数值会顶破 10 —— 那正是要被抓住的写放大。
#: 想跑满 10 分钟做交叉验证：``FULILIAN_STRESS_IDLE_SECONDS=600``（阈值同步 ×10）。
IDLE_WINDOW_SECONDS = float(os.environ.get("FULILIAN_STRESS_IDLE_SECONDS", "60"))
IDLE_WRITE_TXN_LIMIT = 10


# ────────────────────────────────────────────────────────────── 测试工具


def _card(task_id: str, out_dir: Path, **overrides: object) -> TaskCard:
    """造一张能过 ``validate_card`` 的卡。

    ``output_path`` 必须绝对且规范，且**每个任务一个文件**——
    ``idx_tasks_output_active`` 是部分唯一索引，同一时刻同一路径只能有一个
    非终态任务，重复了 ``enqueue`` 会撞唯一约束。
    """
    kwargs: dict[str, object] = {
        "task_id": task_id,
        "goal": "store stress",
        "dod": ("claimed exactly once",),
        "output_path": str(out_dir / f"{task_id}.md"),
    }
    kwargs.update(overrides)
    return TaskCard(**kwargs)  # type: ignore[arg-type]


def _row(db_path: Path, task_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None, f"库里没有 {task_id}"
    return row


def _all_rows(db_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        return conn.execute("SELECT * FROM tasks ORDER BY task_id").fetchall()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────── 子进程入口
# 必须是模块级函数：fork 下虽然闭包也能用，但模块级能同时兼容 spawn，
# 且 traceback 里的名字可读。


def _claim_worker(db_path: str, worker_id: str, pool: str, log_path: str) -> None:
    lines: list[str] = []
    store = Store(db_path, worker_id=worker_id)
    try:
        misses = 0
        while misses < 3:
            claimed = store.claim(pool, max_wait_seconds=0.0)
            if claimed is None:
                # D2 第 5 步：输掉竞态（探测到有行、进事务后已被别人抢走）时
                # claim() 也返回 None，和"队列空"完全不可区分。所以单次 None
                # 不足以判定收工，连续 3 次才退出，否则 worker 会在还有任务的
                # 时候提前散伙，让"每个任务恰好被领一次"测不出来。
                misses += 1
                continue
            misses = 0
            lines.append(
                json.dumps(
                    {
                        "task_id": claimed.task_id,
                        "worker_id": claimed.worker_id,
                        "lease_epoch": claimed.lease_epoch,
                        "attempts": claimed.attempts,
                    }
                )
            )
    except BaseException:
        lines.append(json.dumps({"error": traceback.format_exc()}))
        raise
    finally:
        Path(log_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        store.close()


def _idle_worker(
    db_path: str,
    worker_id: str,
    pool: str,
    duration: float,
    start_event: object,
    log_path: str,
) -> None:
    store = Store(db_path, worker_id=worker_id)
    counter = WriteTxnCounter()
    find_connection(store).set_trace_callback(counter)
    payload: dict[str, object] = {}
    try:
        start_event.wait(timeout=60.0)  # type: ignore[attr-defined]
        counter.reset()  # 窗口起点：所有 worker 都已建好 Store
        deadline = time.monotonic() + duration
        probes = 0
        unexpected = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            claimed = store.claim(pool, max_wait_seconds=min(1.0, max(remaining, 0.01)))
            probes += 1
            if claimed is not None:
                unexpected += 1
        payload = {
            "write_txns": counter.count,
            "probes": probes,
            "unexpected_claims": unexpected,
            "sample": counter.sample,
        }
    finally:
        Path(log_path).write_text(json.dumps(payload), encoding="utf-8")
        store.close()


def _sigkill_worker(
    db_path: str,
    worker_id: str,
    pool: str,
    log_path: str,
    start_first: bool = False,
) -> None:
    """领一个任务，把租约记下来，然后被 SIGKILL 打死（不 close、不写回）。

    ``start_first=True`` 时先 ``start()`` 进入 RUNNING 再死，用于验证
    "崩溃（RUNNING）落 BLOCKED" 这条路径；默认停在 CLAIMED，验证
    "领了没跑就死（CLAIMED）走重试预算" 这条路径。两条路径语义不同，
    不能混成一个用例。
    """
    store = Store(db_path, worker_id=worker_id)
    claimed = store.claim(pool, max_wait_seconds=0.0)
    if claimed is None:
        Path(log_path).write_text(json.dumps({"claimed": False}), encoding="utf-8")
        os._exit(3)
    Path(log_path).write_text(
        json.dumps(
            {
                "claimed": True,
                "task_id": claimed.task_id,
                "worker_id": claimed.worker_id,
                "lease_epoch": claimed.lease_epoch,
                "attempts": claimed.attempts,
            }
        ),
        encoding="utf-8",
    )
    if start_first:
        store.start(claimed.task_id, claimed.lease_epoch)
    # 文件已 close，记录落盘。现在模拟 OOM-killer / kill -9：不 close 连接、
    # 不心跳、不写回，租约就这么烂在库里。
    os.kill(os.getpid(), signal.SIGKILL)


# ────────────────────────────────────────────────────────────── 验收 ①


def test_concurrent_claim_single_winner(tmp_path: Path) -> None:
    """① 8 进程抢同一批任务，每个任务成功数恰为 1。

    判定看三处，缺一不可：
    - 领取记录总数 == 任务数（没有漏领，也没有多领）；
    - 去重后的 task_id 数 == 任务数（**没有重复领取**，这是本用例的核心）；
    - 库内每行 ``attempts == 1`` / ``lease_epoch == 1``（D3/D4：claim 时原子 +1，
      两个 worker 读到同一个旧值就会在这里露馅）。
    """
    db_path = tmp_path / "claim.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    seed = Store(str(db_path), worker_id="seed")
    try:
        for index in range(CLAIM_TASKS):
            seed.enqueue(_card(f"task-{index:04d}", out_dir))
    finally:
        seed.close()  # fork 前必须关：连接不跨进程

    ctx = mp.get_context("fork")
    logs = [str(tmp_path / f"claim-{i:02d}.jsonl") for i in range(CLAIM_WORKERS)]
    procs = [
        ctx.Process(
            target=_claim_worker,
            args=(str(db_path), f"w{i:02d}", "solve", logs[i]),
            name=f"claim-w{i:02d}",
        )
        for i in range(CLAIM_WORKERS)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=120)

    assert [p.exitcode for p in procs] == [0] * CLAIM_WORKERS, "worker 非正常退出"

    records: list[dict] = []
    for log in logs:
        for line in Path(log).read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                assert "error" not in item, item.get("error")
                records.append(item)

    assert len(records) == CLAIM_TASKS, f"领取记录 {len(records)} 条，应为 {CLAIM_TASKS}"
    counts: dict[str, int] = {}
    for record in records:
        counts[record["task_id"]] = counts.get(record["task_id"], 0) + 1
    duplicated = {tid: n for tid, n in counts.items() if n != 1}
    assert not duplicated, f"这些任务被领取了不止一次：{duplicated}"
    assert len(counts) == CLAIM_TASKS

    rows = _all_rows(db_path)
    assert len(rows) == CLAIM_TASKS
    for row in rows:
        assert row["attempts"] == 1, f"{row['task_id']} attempts={row['attempts']}"
        assert row["lease_epoch"] == 1, f"{row['task_id']} lease_epoch={row['lease_epoch']}"
        assert row["state"] == "CLAIMED"
        assert row["claimed_by"] is not None
    # 库内 holder 必须与子进程拿到的 worker_id 一致（不能是"别人领了、我记了"）。
    for record in records:
        row = _row(db_path, record["task_id"])
        assert row["claimed_by"] == record["worker_id"]
        assert row["lease_epoch"] == record["lease_epoch"]


# ────────────────────────────────────────────────────────────── 验收 ③


def test_idle_queue_write_amplification(tmp_path: Path) -> None:
    """③ 空队列写放大：60 秒内写事务 < 10（10 分钟的等价折算）。

    折算依据（与计划原文对齐）：计划要求「15 worker × 10 分钟，写事务 < 100」。
    单测不能跑 10 分钟，取 1/10 的时间窗口，阈值同比取 1/10：

        100 次 ÷ (600 秒 ÷ 60 秒) = 100 ÷ 10 = **10 次**

    折算成立的前提是空队列稳态下写事务速率恒定——claim 只做只读探测，没有随
    时间增长的状态。速率一旦不恒定（例如每次探测都写审计行），60 秒的读数照样
    会顶破 10，门禁不会漏抓。

    决议 D2 的要求比门禁更严：**空队列一次写事务都不许开**。所以这里断言 0，
    同时保留 `< 10` 的门禁断言，让人一眼看到两个数字的关系。
    """
    db_path = tmp_path / "idle.db"
    # 先把库建好（窗口外），否则 15 个 worker 各自跑 apply_schema，那 15 次建表
    # 事务会被算进测量窗口，把 D2 的读数污染成"worker 个数"。
    Store(str(db_path), worker_id="bootstrap").close()

    # 两条独立于 trace 回调的旁证：trace 说 0 次写、WAL 却长了，说明有一条没被
    # 插桩的连接在写（比如每次调用新建连接）。
    observer = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        data_version_before = observer.execute("PRAGMA data_version").fetchone()[0]
        wal_before = wal_size(db_path)

        ctx = mp.get_context("fork")
        start_event = ctx.Event()
        logs = [str(tmp_path / f"idle-{i:02d}.json") for i in range(IDLE_WORKERS)]
        procs = [
            ctx.Process(
                target=_idle_worker,
                args=(
                    str(db_path),
                    f"w{i:02d}",
                    "solve",
                    IDLE_WINDOW_SECONDS,
                    start_event,
                    logs[i],
                ),
                name=f"idle-w{i:02d}",
            )
            for i in range(IDLE_WORKERS)
        ]
        for proc in procs:
            proc.start()
        started = time.monotonic()
        start_event.set()
        for proc in procs:
            proc.join(timeout=IDLE_WINDOW_SECONDS + 120)
        elapsed = time.monotonic() - started

        data_version_after = observer.execute("PRAGMA data_version").fetchone()[0]
        wal_after = wal_size(db_path)
    finally:
        observer.close()

    assert [p.exitcode for p in procs] == [0] * IDLE_WORKERS, "worker 非正常退出"
    assert elapsed >= IDLE_WINDOW_SECONDS * 0.9, f"窗口只跑了 {elapsed:.1f}s"

    results = [json.loads(Path(log).read_text(encoding="utf-8")) for log in logs]
    write_txns = sum(int(r["write_txns"]) for r in results)
    probes = sum(int(r["probes"]) for r in results)
    unexpected = sum(int(r["unexpected_claims"]) for r in results)

    assert probes > 0, "一次 claim 都没调到，测试没跑起来"
    assert unexpected == 0, f"空队列里领到了 {unexpected} 个任务"
    # 门禁本身（60 秒等价折算，见上方注释）
    assert write_txns < IDLE_WRITE_TXN_LIMIT, (
        f"{IDLE_WORKERS} worker × {IDLE_WINDOW_SECONDS:.0f}s 内 {write_txns} 次写事务，"
        f"超过 60 秒等价阈值 {IDLE_WRITE_TXN_LIMIT}（=100/10）"
    )
    # D2 更严：空队列必须零写事务
    assert write_txns == 0, (
        f"空队列出现 {write_txns} 次写事务（D2 要求 0）；"
        f"样例：{[s for r in results for s in r.get('sample', [])][:3]}"
    )
    assert wal_after == wal_before, f"WAL 增长 {wal_after - wal_before} 字节，有未插桩的写"
    assert data_version_after == data_version_before, "data_version 变化，有未插桩的写"


# ────────────────────────────────────────────────────────────── 验收 ④


def test_sigkill_running_lands_in_blocked_then_redispatch(tmp_path: Path) -> None:
    """④-a kill -9（已 start，RUNNING）→ BLOCKED → redispatch → QUEUED → 再 claim。

    这是"崩溃是故障"的路径：任务已经跑过，需要人工/策略决定是否重派，
    所以落 BLOCKED，由 redispatch 消耗一次 handoff 预算。

    租约 300 秒，真等就是 5 分钟。这里用 ``Store(now=lambda: 未来)`` 注入时钟，
    让 patrol 看到"租约已过期"，不 sleep。
    """
    db_path = tmp_path / "kill-running.db"
    out_dir = tmp_path / "out-running"
    out_dir.mkdir()

    seed = Store(str(db_path), worker_id="seed")
    try:
        seed.enqueue(_card("victim-run", out_dir))
    finally:
        seed.close()

    ctx = mp.get_context("fork")
    log = str(tmp_path / "victim-run.json")
    victim = ctx.Process(
        target=_sigkill_worker,
        args=(str(db_path), "victim", "solve", log, True),
        name="victim-run",
    )
    victim.start()
    victim.join(timeout=120)

    assert victim.exitcode == -signal.SIGKILL, f"子进程没有被 SIGKILL 打死：{victim.exitcode}"
    record = json.loads(Path(log).read_text(encoding="utf-8"))
    assert record["claimed"] is True, "子进程没领到任务，用例前提不成立"
    assert record["attempts"] == 1

    before = _row(db_path, "victim-run")
    assert before["state"] == "RUNNING", "start() 之后应处于 RUNNING"
    assert before["lease_epoch"] == 1

    future = time.time() + 10 * 24 * 3600
    patroller = Store(str(db_path), worker_id="patrol", now=lambda: future)
    try:
        handled = patroller.patrol(limit=100)
    finally:
        patroller.close()

    assert handled == 1, f"patrol 处理了 {handled} 条，应为 1"
    blocked = _row(db_path, "victim-run")
    assert blocked["state"] == "BLOCKED", "D7：RUNNING 崩溃必须落 BLOCKED，不是 INTERRUPTED"
    assert blocked["block_reason"] == "lease_expired"
    assert blocked["handoff_count"] == 0

    rescuer = Store(str(db_path), worker_id="rescuer")
    try:
        rescuer.redispatch("victim-run")
        queued = _row(db_path, "victim-run")
        assert queued["state"] == "QUEUED"
        assert queued["handoff_count"] == 1, "D8：handoff_count 必须与状态变更同一条 UPDATE +1"
        assert queued["claimed_by"] is None
        assert queued["lease_expires"] is None
        assert queued["block_reason"] is None

        again = rescuer.claim("solve", max_wait_seconds=0.0)
        assert again is not None, "重启后必须能接管"
        assert again.task_id == "victim-run"
        assert again.attempts == 2, "D3：崩溃的 worker 消耗一次重试是正确的"
        assert again.lease_epoch == record["lease_epoch"] + 1, "D4：每次 claim 都换 fencing token"
    finally:
        rescuer.close()


def test_sigkill_claimed_lands_in_blocked_then_redispatch(tmp_path: Path) -> None:
    """④-b kill -9（停在 CLAIMED，未 start）→ BLOCKED → redispatch → QUEUED。

    阶段 4 给 ``_ALLOWED[CLAIMED]`` 补了 ``BLOCKED`` / ``CANCELLED`` 两条边，
    所以"领了没跑就死"与 RUNNING 崩溃走**同一条**路径：落 BLOCKED，由
    redispatch 决定是否转手并消耗 handoff 预算。

    补边之前这里走的是 ``CLAIMED → FAILED → QUEUED`` 的绕路，代价是一个从未
    执行过的任务白耗一次重试预算，而且 handoff 预算完全不计账——同一个事件在
    两条路径上记到了两个不同的账本里。
    """
    db_path = tmp_path / "kill-claimed.db"
    out_dir = tmp_path / "out-claimed"
    out_dir.mkdir()

    seed = Store(str(db_path), worker_id="seed")
    try:
        seed.enqueue(_card("victim-claim", out_dir))
    finally:
        seed.close()

    ctx = mp.get_context("fork")
    log = str(tmp_path / "victim-claim.json")
    victim = ctx.Process(
        target=_sigkill_worker,
        args=(str(db_path), "victim", "solve", log, False),
        name="victim-claim",
    )
    victim.start()
    victim.join(timeout=120)
    assert victim.exitcode == -signal.SIGKILL

    record = json.loads(Path(log).read_text(encoding="utf-8"))
    assert record["claimed"] is True

    before = _row(db_path, "victim-claim")
    assert before["state"] == "CLAIMED", "没调 start()，应停在 CLAIMED"

    future = time.time() + 10 * 24 * 3600
    patroller = Store(str(db_path), worker_id="patrol", now=lambda: future)
    try:
        handled = patroller.patrol(limit=100)
    finally:
        patroller.close()

    assert handled == 1
    after = _row(db_path, "victim-claim")
    assert after["state"] == "BLOCKED", (
        f"CLAIMED 崩溃应与 RUNNING 崩溃同样落 BLOCKED，实际 {after['state']}"
    )
    assert after["block_reason"] == "lease_expired"
    assert after["handoff_count"] == 0, "BLOCKED 本身不计 handoff，redispatch 才计"
    assert after["claimed_by"] is None
    assert after["lease_expires"] is None

    rescuer = Store(str(db_path), worker_id="rescuer")
    try:
        rescuer.redispatch("victim-claim")
        queued = _row(db_path, "victim-claim")
        assert queued["state"] == "QUEUED"
        assert queued["handoff_count"] == 1, "D8：redispatch 必须 +1 handoff"

        again = rescuer.claim("solve", max_wait_seconds=0.0)
        assert again is not None, "转手后必须能被重新接管"
        assert again.task_id == "victim-claim"
        assert again.attempts == 2
        assert again.lease_epoch == record["lease_epoch"] + 1
    finally:
        rescuer.close()


def test_end_to_end_absorption(tmp_path: Path) -> None:
    """⑤ 端到端吸收态：连续 claim/start/fail 直到超过 max_retries，落 FAILED 且取不到。

    ``max_retries=2`` → 最多 3 次执行（首次 + 2 次重试）。D9 要求
    ``RUNNING → FAILED`` 之后按 ``attempts <= max_retries`` 决定要不要
    ``FAILED → QUEUED``，不能跳步直接置 QUEUED。
    """
    db_path = tmp_path / "e2e.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    store = Store(str(db_path), worker_id="w1")
    try:
        store.enqueue(_card("absorb-1", out_dir, max_retries=2))

        executions = 0
        while True:
            claimed = store.claim("solve", max_wait_seconds=0.0)
            if claimed is None:
                break
            executions += 1
            assert executions <= 10, "claim 没有收敛，重试循环失控"
            store.start(claimed.task_id, claimed.lease_epoch)
            store.fail(claimed.task_id, claimed.lease_epoch, reason="boom")

        assert executions == 3, f"应执行 1 + max_retries = 3 次，实际 {executions}"

        row = _row(db_path, "absorb-1")
        assert row["state"] == "FAILED", "超过重试上限必须停在 FAILED（吸收态）"
        assert row["attempts"] == 3

        # 吸收态要真的吸住：连取两次都为 None，且库内状态不再变。
        assert store.claim("solve", max_wait_seconds=0.0) is None
        assert store.claim("solve", max_wait_seconds=0.0) is None
        assert _row(db_path, "absorb-1")["state"] == "FAILED"
    finally:
        store.close()
