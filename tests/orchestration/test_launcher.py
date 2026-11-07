"""``agent.orchestration.launcher`` 的测试（阶段 3b 验收 ⑨ + W8/W9；阶段 5 R4/R5）。

三档各一条。全部用文件库：``:memory:`` 无法跨线程/跨进程，测不出 W9。

``execute`` 必须是**模块级函数**：``Tier.DAEMON`` 走 spawn，子进程按限定名
import 它，闭包/lambda 会 pickle 失败。
"""

from __future__ import annotations

import multiprocessing
import sqlite3

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.dispatcher import Tier
from agent.orchestration.launcher import LaunchHandle, _ensure_spawn, launch
from agent.orchestration.reaper import ISOLATION_ENV, ReaperError
from agent.orchestration.store import Store
from agent.orchestration.worker import TaskResult, WorkerContext


# ------------------------------------------------------------------- helpers


def _card(task_id: str = "t1", *, pool: str = "solve") -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"goal of {task_id}",
        dod=("done",),
        output_path=f"/tmp/out/{task_id}.md",
        pool=pool,
    )


def _ok_execute(_ctx: WorkerContext) -> TaskResult:
    """模块级：DAEMON 档要能 pickle 它（spawn 按限定名 import）。"""
    return TaskResult(ok=True, output_path="/tmp/out/t1.md", result_json='{"ok": true}')


@pytest.fixture()
def db(tmp_path):
    """``(path, conn)``：建好库的文件路径 + 测试线程自己的读连接。"""
    path = str(tmp_path / "orchestration.db")
    Store(path, worker_id="setup").close()
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield path, conn
    finally:
        conn.close()


def _enqueue(path: str, task_id: str = "t1") -> None:
    store = Store(path, worker_id="setup")
    try:
        store.enqueue(_card(task_id))
    finally:
        store.close()


def _state(conn: sqlite3.Connection, task_id: str = "t1") -> str:
    row = conn.execute(
        "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    return str(row["state"])


# ---------------------------------------------------------- 验收 ⑨ 三档起停


def test_launcher_inline_runs_synchronously(db):
    path, conn = db
    _enqueue(path, "t1")

    handle = launch(
        Tier.INLINE,
        path,
        "solve",
        _ok_execute,
        worker_id="w-inline",
        heartbeat_interval=0.05,
    )

    # 同步：launch 返回时任务已经落库，不需要等任何东西
    assert _state(conn, "t1") == "SUCCEEDED"
    assert isinstance(handle, LaunchHandle)
    assert handle.tier is Tier.INLINE
    assert handle.worker_id == "w-inline"
    assert handle.thread is None and handle.process is None
    assert handle.is_alive() is False
    assert handle.reaper is None, "INLINE 档没有进程可回收"
    handle.join(1.0)  # 空操作，不该抛


def test_launcher_embedded_thread_joins(db):
    path, conn = db
    _enqueue(path, "t1")

    handle = launch(
        Tier.EMBEDDED,
        path,
        "solve",
        _ok_execute,
        worker_id="w-embedded",
        heartbeat_interval=0.05,
        idle_timeout=0.3,  # 空闲即退出，测试不必等 30 分钟
    )

    assert handle.thread is not None and handle.process is None
    handle.join(15.0)
    assert handle.is_alive() is False, "embedded 线程没有按空闲超时退出"
    assert _state(conn, "t1") == "SUCCEEDED"


def test_launcher_daemon_process_joins(db):
    path, conn = db
    _enqueue(path, "t1")

    handle = launch(
        Tier.DAEMON,
        path,
        "solve",
        _ok_execute,
        worker_id="w-daemon",
        heartbeat_interval=0.05,
        idle_timeout=0.5,  # 覆盖 W8 的 1800s 默认值
    )

    assert handle.process is not None and handle.thread is None
    handle.join(60.0)
    assert handle.is_alive() is False, "daemon 子进程没有按空闲超时退出"
    assert handle.process.exitcode == 0, "子进程非正常退出，看 stderr 的 traceback"
    assert _state(conn, "t1") == "SUCCEEDED"


# --------------------------------------------------------------- 参数校验

def test_launch_rejects_non_tier(db):
    path, _conn = db
    with pytest.raises(TypeError):
        launch("inline", path, "solve", _ok_execute)  # type: ignore[arg-type]


# ------------------------------------------------- 阶段 5 R4：强制 spawn 守卫


class _ForkContext:
    """冒充 fork 上下文。真 fork 会真的复制父进程状态，测试不能真跑。"""

    def get_start_method(self) -> str:
        return "fork"


def test_spawn_guard_rejects_fork(db, monkeypatch):
    path, _conn = db

    with pytest.raises(ReaperError):
        _ensure_spawn(_ForkContext())  # type: ignore[arg-type]

    # 守卫必须在 Process 建出来之前就炸：连 fork context 都不许走到 start()。
    monkeypatch.setattr(multiprocessing, "get_context", lambda _m: _ForkContext())
    with pytest.raises(ReaperError):
        launch(Tier.DAEMON, path, "solve", _ok_execute, worker_id="w-fork")


# ---------------------------------------- 阶段 5 R5：灰度开关控制 reaper 登记


def test_daemon_reaper_attached_only_when_flag_on(db, monkeypatch):
    path, _conn = db
    monkeypatch.delenv(ISOLATION_ENV, raising=False)
    _enqueue(path, "t1")

    off = launch(
        Tier.DAEMON,
        path,
        "solve",
        _ok_execute,
        worker_id="w-off",
        heartbeat_interval=0.05,
        idle_timeout=0.5,
    )
    try:
        assert off.reaper is None, "开关默认关时不该登记 reaper"
    finally:
        off.join(60.0)
    assert off.is_alive() is False

    monkeypatch.setenv(ISOLATION_ENV, "1")
    _enqueue(path, "t2")
    on = launch(
        Tier.DAEMON,
        path,
        "solve",
        _ok_execute,
        worker_id="w-on",
        heartbeat_interval=0.05,
        idle_timeout=0.5,
    )
    try:
        assert on.reaper is not None, "开关打开时必须登记 reaper"
    finally:
        on.join(60.0)
        on.reaper.close()
    assert on.is_alive() is False
