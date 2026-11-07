"""``agent.orchestration.worker`` 的测试（阶段 3b，决议 W1-W5/W8/W9）。

每条测试点名它钉住的验收项。跨线程一律用文件库（``tmp_path``）：``:memory:``
连接不共享，测不出 W9 想守的东西。

W9 同样约束测试自身：``Store`` 与 ``Control`` 的连接只能在**创建它的那个线程**
里用。所以需要并发注入指令的三条测试，把整个 ``Worker``（连同它的 ``Store``）
放进工作线程里建；测试线程另持一条只读/控制连接。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.control import Control
from agent.orchestration.store import Store
from agent.orchestration.worker import TaskResult, Worker, WorkerContext


# ------------------------------------------------------------------- helpers


def _card(task_id: str = "t1", *, pool: str = "solve", max_retries: int = 1) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"goal of {task_id}",
        dod=("done",),
        output_path=f"/tmp/out/{task_id}.md",
        pool=pool,
        max_retries=max_retries,
    )


@pytest.fixture()
def db(tmp_path):
    """``(path, conn, control)``：库文件 + 测试线程自己的连接。"""
    path = str(tmp_path / "orchestration.db")
    Store(path, worker_id="setup").close()  # 建库 + 迁移，随后即弃
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield path, conn, Control(conn)
    finally:
        conn.close()


def _row(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()


def _wait_state(
    conn: sqlite3.Connection, task_id: str, state: str, *, timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if str(_row(conn, task_id)["state"]) == state:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"{task_id} 未在 {timeout}s 内进入 {state}，实际 {_row(conn, task_id)['state']}"
    )


def _event(conn: sqlite3.Connection, task_id: str, kind: str) -> str:
    row = conn.execute(
        "SELECT payload FROM events WHERE task_id = ? AND kind = ? "
        "ORDER BY event_id DESC LIMIT 1",
        (task_id, kind),
    ).fetchone()
    assert row is not None, f"没有 {kind} 事件：task_id={task_id}"
    return str(row["payload"])


def _start_worker(
    path: str,
    execute: Callable[[WorkerContext], TaskResult],
    *,
    worker_id: str = "w1",
    lease_seconds: int = 300,
    heartbeat_interval: float = 0.05,
) -> tuple[threading.Thread, dict[str, object]]:
    """在工作线程里建 ``Store``/``Control`` 并跑一次 ``run_once``（W9）。"""
    box: dict[str, object] = {}

    def body() -> None:
        store = Store(path, worker_id=worker_id)
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            worker = Worker(
                store,
                Control(conn),
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                heartbeat_interval=heartbeat_interval,
            )
            box["ran"] = worker.run_once("solve", execute)
        except BaseException as exc:  # noqa: BLE001 - 线程里的异常要带回主线程断言
            box["error"] = exc
        finally:
            conn.close()
            store.close()

    thread = threading.Thread(target=body, name="test-worker")
    thread.start()
    return thread, box


def _never_claimed(_ctx: WorkerContext) -> TaskResult:  # pragma: no cover
    raise AssertionError("空闲超时测试不应领到任务")


# --------------------------------------------------------------- 验收 ③ 完成


def test_worker_completes_task(db):
    path, conn, control = db
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card("t1"))
        seen: dict[str, object] = {}

        def execute(c: WorkerContext) -> TaskResult:
            seen["task_id"] = c.task_id
            seen["epoch"] = c.lease_epoch
            seen["worker_id"] = c.worker_id
            return TaskResult(
                ok=True, output_path="/tmp/out/t1.md", result_json='{"n": 1}'
            )

        worker = Worker(store, control, worker_id="w1", heartbeat_interval=0.05)
        assert worker.run_once("solve", execute) is True
        # 队列空了 -> False（"没有可领的任务"）
        assert worker.run_once("solve", execute) is False
    finally:
        store.close()

    row = _row(conn, "t1")
    assert row["state"] == "SUCCEEDED"
    assert row["result_json"] == '{"n": 1}'
    assert row["completed_at"] is not None
    assert seen["task_id"] == "t1"
    assert seen["epoch"] == row["lease_epoch"]
    # output_path 落库：tasks 表里是卡片的，审计事件里是 execute 报的
    assert "/tmp/out/t1.md" in _event(conn, "t1", "task_succeeded")


# --------------------------------------------------- 验收 ④ 执行期间持续续租


def test_worker_heartbeats_during_long_execution(db):
    """租约 1s、执行 1.6s：没有 heartbeat 线程的话 1.3s 时的 patrol 会判死。"""
    path, conn, _control = db
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card("t1"))

        def execute(_c: WorkerContext) -> TaskResult:
            deadline = time.monotonic() + 1.6
            while time.monotonic() < deadline:
                time.sleep(0.02)
            return TaskResult(ok=True, output_path="/tmp/out/t1.md")

        runner, box = _start_worker(
            path, execute, lease_seconds=1, heartbeat_interval=0.1
        )
        try:
            time.sleep(1.3)  # 已越过 lease_seconds=1
            blocked = store.patrol()
        finally:
            runner.join(10)
    finally:
        store.close()

    assert "error" not in box, box.get("error")
    assert box.get("ran") is True
    assert blocked == 0, "patrol 判死了一个还活着的 worker：heartbeat 没生效"
    assert _row(conn, "t1")["state"] == "SUCCEEDED"


# ------------------------------------------------------- 验收 ⑤ stop -> cancel


def test_worker_cancels_on_stop_command(db):
    path, conn, control = db
    store = Store(path, worker_id="setup2")
    store.enqueue(_card("t1"))
    store.close()
    observed: dict[str, object] = {}

    def execute(c: WorkerContext) -> TaskResult:
        observed["cancelled"] = c.cancelled.wait(5.0)
        return TaskResult(ok=False, reason="被 stop 打断")

    runner, box = _start_worker(path, execute)
    try:
        _wait_state(conn, "t1", "RUNNING")
        assert control.request_stop("t1") == "queued"
    finally:
        runner.join(10)

    assert "error" not in box, box.get("error")
    assert observed["cancelled"] is True, "execute 没有观察到 ctx.cancelled"
    assert _row(conn, "t1")["state"] == "CANCELLED"


# ------------------------------------------------------- 验收 ⑥ steer 逐字送达


def test_worker_receives_steer_text(db):
    path, conn, control = db
    store = Store(path, worker_id="setup2")
    store.enqueue(_card("t1"))
    store.close()
    seen: dict[str, object] = {}

    def execute(c: WorkerContext) -> TaskResult:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not c.steers:
            time.sleep(0.02)
        seen["steers"] = list(c.steers)
        return TaskResult(ok=True, output_path="/tmp/out/t1.md")

    runner, box = _start_worker(path, execute)
    try:
        _wait_state(conn, "t1", "RUNNING")
        control.request_steer("t1", "  多看一遍日志  ")
    finally:
        runner.join(10)

    assert "error" not in box, box.get("error")
    # 逐字相等：control 不 strip，worker 也不改写
    assert seen["steers"] == ["  多看一遍日志  "]
    epoch = int(_row(conn, "t1")["lease_epoch"])
    assert control.poll("t1", epoch) == [], "ack 之后不应再返回同一条 steer"


# --------------------------------------------------- 验收 ⑦ execute 抛异常


def test_worker_fails_on_execute_exception(db):
    path, conn, control = db
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card("t1", max_retries=0))

        def execute(_c: WorkerContext) -> TaskResult:
            raise RuntimeError("boom")

        worker = Worker(store, control, worker_id="w1", heartbeat_interval=0.05)
        assert worker.run_once("solve", execute) is True
    finally:
        store.close()

    # max_retries=0 -> FAILED 后不再入队（否则就是无限重试）
    assert _row(conn, "t1")["state"] == "FAILED"
    payload = _event(conn, "t1", "task_failed")
    assert "RuntimeError" in payload, "reason 里必须留下异常类型名"
    assert "boom" in payload


# ------------------------------------------------------- 验收 ⑧ 空闲超时退出


def test_run_forever_exits_after_idle_timeout(db):
    """假时钟每次前进 30s：idle_timeout=30 时第一轮空转后就该退出，不真 sleep。"""
    path, conn, _control = db

    class _Clock:
        def __init__(self) -> None:
            self.t = 0.0

        def __call__(self) -> float:
            self.t += 30.0
            return self.t

    store = Store(path, worker_id="w1", now=_Clock())
    try:
        worker = Worker(store, Control(conn), worker_id="w1", heartbeat_interval=0.05)
        started = time.monotonic()
        worker.run_forever("solve", _never_claimed, idle_timeout=30.0)
        elapsed = time.monotonic() - started
    finally:
        store.close()

    assert elapsed < 5.0, f"空闲超时没有生效，跑了 {elapsed:.1f}s"


# ------------------------------------------------ 验收 ⑥ fenced 产物作废 (R6)


def _bump_epoch(path: str, task_id: str) -> None:
    """``lease_epoch += 1``：模拟"执行期间租约被另一个 worker 抢走"。

    必须在执行 ``execute`` 的那个线程里调用（W9：连接不跨线程）。
    """
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute(
            "UPDATE tasks SET lease_epoch = lease_epoch + 1 WHERE task_id = ?",
            (task_id,),
        )
    finally:
        conn.close()


def _card_at(task_id: str, output_path: str) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"goal of {task_id}",
        dod=("done",),
        output_path=output_path,
        pool="solve",
        max_retries=1,
    )


def test_fenced_artifact_is_renamed(db, tmp_path):
    """R6：fencing 后 canonical 路径必须消失，产物改名到 ``.fenced-{epoch}``。"""
    path, conn, control = db
    out = tmp_path / "artifacts" / "t1.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path, worker_id="w1")
    seen: dict[str, object] = {}
    try:
        store.enqueue(_card_at("t1", str(out)))

        def execute(c: WorkerContext) -> TaskResult:
            out.write_text("stale result", encoding="utf-8")
            seen["epoch"] = c.lease_epoch
            _bump_epoch(path, c.task_id)  # complete() 将抛 FencedOutError
            return TaskResult(ok=True, output_path=str(out))

        # heartbeat_interval 远大于执行时间：不让续租线程抢先把 cancelled 置位
        worker = Worker(store, control, worker_id="w1", heartbeat_interval=30.0)
        assert worker.run_once("solve", execute) is True
    finally:
        store.close()

    epoch = seen["epoch"]
    fenced = out.with_name(f"{out.name}.fenced-{epoch}")
    assert not out.exists(), "canonical 路径还在：按约定路径会读到未被承认的产物"
    assert fenced.exists(), f"没有找到作废产物：{fenced}"
    assert fenced.read_text(encoding="utf-8") == "stale result", "改名不得改内容"
    # DB 侧语义不变：fencing 就是不写回，任务仍停在被抢走时的状态
    assert _row(conn, "t1")["state"] == "RUNNING"


def test_fenced_artifact_rename_failure_does_not_raise(db, tmp_path, monkeypatch, caplog):
    """R6：改名失败（权限不足）只记日志，worker 必须正常返回。"""
    path, conn, control = db
    out = tmp_path / "artifacts" / "t2.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card_at("t2", str(out)))

        def execute(c: WorkerContext) -> TaskResult:
            out.write_text("stale result", encoding="utf-8")
            _bump_epoch(path, c.task_id)
            return TaskResult(ok=True, output_path=str(out))

        def _deny(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("父目录不可写")

        monkeypatch.setattr("agent.orchestration.worker.os.replace", _deny)
        worker = Worker(store, control, worker_id="w1", heartbeat_interval=30.0)
        with caplog.at_level(logging.WARNING, logger="agent.orchestration.worker"):
            assert worker.run_once("solve", execute) is True
    finally:
        store.close()

    assert out.exists(), "改名失败时文件应原地不动"
    assert "改名失败" in caplog.text, caplog.text
    assert "PermissionError" in caplog.text, caplog.text


def test_fenced_artifact_not_voided_when_rewritten_by_new_holder(db, tmp_path, caplog):
    """真实时序：W2 在 W1 的 execute 期间就领走任务并写了同一路径。

    W1 的 execute 返回时租约已经不在（这正是 complete() 被 fence 的原因），
    任何"文件身份"看到的都只是 W2 的文件，因此判据必须问数据库"谁持有"。
    """
    path, conn, control = db
    out = tmp_path / "artifacts" / "t3.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card_at("t3", str(out)))

        def execute(_c: WorkerContext) -> TaskResult:
            out.write_text("result from w1", encoding="utf-8")
            # 真实的抢租约链路：patrol 判死 -> redispatch -> 新 worker 领走并写入
            w2 = Store(path, worker_id="w2")
            try:
                time.sleep(0.01)  # 让 W1 的 lease_seconds=0 真的过期
                assert w2.patrol() == 1
                w2.redispatch("t3")
                claimed = w2.claim("solve", lease_seconds=300)
                assert claimed is not None and claimed.lease_epoch > _c.lease_epoch
                w2.start(claimed.task_id, claimed.lease_epoch)
                out.write_text("result from w2", encoding="utf-8")
            finally:
                w2.close()
            return TaskResult(ok=True, output_path=str(out))

        worker = Worker(
            store, control, worker_id="w1", lease_seconds=0, heartbeat_interval=30.0
        )
        with caplog.at_level(logging.WARNING, logger="agent.orchestration.worker"):
            assert worker.run_once("solve", execute) is True
    finally:
        store.close()

    assert out.exists(), "W2 的有效产物被作废了"
    assert out.read_text(encoding="utf-8") == "result from w2", "内容被动了"
    assert not list(out.parent.glob("*.fenced-*")), "不应留下任何作废产物"
    assert "新持有者" in caplog.text, caplog.text


def test_fenced_artifact_voided_when_task_not_held(db, tmp_path, caplog):
    """判据不是"一律不作废"：BLOCKED 且无人持有时，旧产物仍要作废。"""
    path, conn, control = db
    out = tmp_path / "artifacts" / "t4.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card_at("t4", str(out)))

        def execute(_c: WorkerContext) -> TaskResult:
            out.write_text("result from w1", encoding="utf-8")
            # 抢租约后 W2 也死了：epoch 前进到 2，claimed_by 回到 NULL
            w2 = Store(path, worker_id="w2")
            try:
                time.sleep(0.01)
                assert w2.patrol() == 1
                w2.redispatch("t4")
                claimed = w2.claim("solve", lease_seconds=0)
                assert claimed is not None
                time.sleep(0.01)
                assert w2.patrol() == 1  # W2 的租约也过期 -> BLOCKED，无人持有
            finally:
                w2.close()
            return TaskResult(ok=True, output_path=str(out))

        worker = Worker(
            store, control, worker_id="w1", lease_seconds=0, heartbeat_interval=30.0
        )
        with caplog.at_level(logging.WARNING, logger="agent.orchestration.worker"):
            assert worker.run_once("solve", execute) is True
    finally:
        store.close()

    fenced = out.with_name(f"{out.name}.fenced-1")
    assert not out.exists(), "无人持有时旧产物应被作废"
    assert fenced.exists(), f"没有找到作废产物：{fenced}"
    assert fenced.read_text(encoding="utf-8") == "result from w1"


def test_fenced_artifact_not_voided_when_task_succeeded(db, tmp_path, caplog):
    """任务已被承认（SUCCEEDED）时，旧 worker 绝不能碰 canonical 上的产物。"""
    path, conn, control = db
    out = tmp_path / "artifacts" / "t5.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path, worker_id="w1")
    try:
        store.enqueue(_card_at("t5", str(out)))

        def execute(_c: WorkerContext) -> TaskResult:
            out.write_text("result from w1", encoding="utf-8")
            w2 = Store(path, worker_id="w2")
            try:
                time.sleep(0.01)
                assert w2.patrol() == 1
                w2.redispatch("t5")
                claimed = w2.claim("solve", lease_seconds=300)
                assert claimed is not None
                w2.start(claimed.task_id, claimed.lease_epoch)
                out.write_text("result from w2", encoding="utf-8")
                w2.complete(
                    claimed.task_id, claimed.lease_epoch, output_path=str(out)
                )  # 结果被承认
            finally:
                w2.close()
            return TaskResult(ok=True, output_path=str(out))

        worker = Worker(
            store, control, worker_id="w1", lease_seconds=0, heartbeat_interval=30.0
        )
        with caplog.at_level(logging.WARNING, logger="agent.orchestration.worker"):
            assert worker.run_once("solve", execute) is True
    finally:
        store.close()

    assert _row(conn, "t5")["state"] == "SUCCEEDED"
    assert out.exists(), "已被承认的产物被旧 worker 作废了"
    assert out.read_text(encoding="utf-8") == "result from w2"
    assert not list(out.parent.glob("*.fenced-*"))
    assert "SUCCEEDED" in caplog.text, caplog.text
