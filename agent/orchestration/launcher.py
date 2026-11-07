"""Launcher: 按档位起停 worker（阶段 3b，决议 W8/W9；阶段 5 接入进程回收）。

冻结契约：``docs/design/orchestration-phase3b-worker-decisions.md`` §三，
进程层见 ``docs/design/orchestration-phase5-decisions.md``。

三档的差别是**生命周期**，不是隔离级别（决议 §一）：

============  ==================================  =========================
档位          形态                                 连接归属
============  ==================================  =========================
``INLINE``    当前线程同步跑一次 ``run_once``      调用方线程
``EMBEDDED``  后台线程，随调用方进程退出           线程内自建
``DAEMON``    独立进程，可跨调用存活               子进程内自建
============  ==================================  =========================

W9 是这一层唯一容易踩死的点：**连接绝不跨线程/进程传递**。所以 ``launch()``
只把 ``db_path`` 交给线程/子进程，各自 ``Store(db_path)`` + 自己的 ``Control``。
传一个 ``Store`` 进去会在子进程里得到一个 fork 出来的半死连接，或在线程里直接
抛 ``sqlite3.ProgrammingError``。

阶段 5 在这里挂了三件事：

* **R1**：``_process_main`` 第一句 ``os.setsid()``——子进程自成进程组，
  ``ProcessReaper.kill_tree`` 才能一次带走整棵树（含孙进程）。它**不受灰度开关
  控制**（开关关掉它也不会更安全，只会让"杀整组"彻底不可用）；win32 上不调用，
  那里靠 Job Object 回收，见下条。
* **R4**：强制 ``spawn``，并用 :func:`_ensure_spawn` 把 fork 挡在启动之前。
* **R5**：``FULILIAN_ORCH_PROCESS_ISOLATION`` 灰度开关，默认关；开时才把进程
  登记进 :class:`~agent.orchestration.reaper.ProcessReaper`。

本模块不碰任务状态：状态全部由 ``worker.py`` 写。
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sqlite3
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from agent.orchestration.control import Control
from agent.orchestration.dispatcher import Tier
from agent.orchestration.reaper import (
    ProcessReaper,
    ReaperError,
    isolation_enabled,
)
from agent.orchestration.store import Store
from agent.orchestration.worker import TaskResult, Worker, WorkerContext

__all__ = ["LaunchHandle", "launch"]

logger = logging.getLogger(__name__)

#: W8: daemon 的默认空闲自杀时间（30 分钟，对齐计划验收）。
#: ``launch(..., idle_timeout=None)`` 在这一档上落到这个值；其余两档 ``None``
#: 就是"永不自杀"。
_DAEMON_IDLE_TIMEOUT = 1800.0


@dataclass(frozen=True, slots=True)
class LaunchHandle:
    """起停句柄。``INLINE`` 档两个句柄字段都是 ``None``（没有东西可 join）。"""

    tier: Tier
    worker_id: str
    thread: threading.Thread | None = None
    process: multiprocessing.process.BaseProcess | None = None
    #: R5：灰度开关打开时才有。``None`` = 本进程没登记回收器，``kill_tree``
    #: 不可用（但子进程仍然 ``setsid``，只是没有登记表可查）。
    reaper: ProcessReaper | None = None

    def join(self, timeout: float | None = None) -> None:
        """等 worker 结束。``INLINE`` 档是空操作——它返回时已经跑完了。"""
        if self.thread is not None:
            self.thread.join(timeout)
        if self.process is not None:
            self.process.join(timeout)

    def is_alive(self) -> bool:
        if self.thread is not None:
            return self.thread.is_alive()
        if self.process is not None:
            return self.process.is_alive()
        return False


def _ensure_spawn(context: multiprocessing.context.BaseContext) -> None:
    """R4：拒绝 fork 上下文。

    fork 会把父进程已打开的 sqlite 连接复制进子进程（两个进程操作同一个文件
    句柄），且父进程若有线程持锁，fork 出的子进程可能永久死锁。这两个故障都
    极难定位，所以在启动之前就炸掉。

    **当前恒真**：调用方上一行刚 ``get_context("spawn")``，``get_start_method()``
    必然返回 ``"spawn"``，生产路径上这个分支永不触发。它守的是**将来的改动**
    （有人把 ``get_context("spawn")`` 改成可配置/``get_context()`` 默认值），
    不是当前的调用。别把它当成"正在生效的检查"。
    """
    if context.get_start_method() == "fork":
        raise ReaperError("禁止 fork：会复制父进程的 sqlite 句柄与线程状态")


def launch(
    tier: Tier,
    db_path: str,
    pool: str,
    execute: Callable[[WorkerContext], TaskResult],
    *,
    worker_id: str | None = None,
    lease_seconds: int = 300,
    heartbeat_interval: float = 5.0,
    idle_timeout: float | None = None,
) -> LaunchHandle:
    """按档位起一个 worker。

    Args:
        tier: ``Tier.INLINE`` 同步跑一个任务后返回；``Tier.EMBEDDED`` 起后台
            线程；``Tier.DAEMON`` 起独立进程。
        db_path: 库文件路径。**不是连接**——每个线程/进程自己开（W9）。
        pool: 领取哪个池。
        execute: 执行体，见 ``worker.WorkerContext``。
        worker_id: ``None`` 时按 ``pid + uuid`` 生成，避免两个 launcher 撞名。
        lease_seconds: 租约长度。
        heartbeat_interval: 续租间隔，必须远小于 ``lease_seconds``。
        idle_timeout: 空闲多久退出。``DAEMON`` 档 ``None`` 落到 1800s（W8）；
            ``INLINE`` 档忽略（它只跑一次）。

    Returns:
        :class:`LaunchHandle`。``INLINE`` 返回时任务已落库。
    """
    if not isinstance(tier, Tier):
        raise TypeError(f"tier 必须是 Tier，收到 {type(tier).__name__}")

    resolved_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    # W8: 只有 DAEMON 档把 ``None`` 映射成 1800s。判据写进**表达式**（带 tier
    # 判断），而不是靠"这一行在 EMBEDDED 的 return 之后"——将来谁把它上提到
    # 分支之前，EMBEDDED 也不会静默继承 1800s。INLINE/EMBEDDED 拿到的仍是原值，
    # 所以 ``None`` = 永不自杀在这两档上成立。
    timeout = (
        _DAEMON_IDLE_TIMEOUT
        if tier is Tier.DAEMON and idle_timeout is None
        else idle_timeout
    )

    args = (
        db_path,
        pool,
        execute,
        resolved_id,
        int(lease_seconds),
        float(heartbeat_interval),
        idle_timeout,
    )

    if tier is Tier.INLINE:
        _run_inline(*args)
        return LaunchHandle(tier=tier, worker_id=resolved_id)

    if tier is Tier.EMBEDDED:
        thread = threading.Thread(
            target=_thread_main,
            args=args,
            name=f"worker-{resolved_id}",
            daemon=True,  # 线程随调用方退出，这正是 EMBEDDED 的定义
        )
        thread.start()
        return LaunchHandle(tier=tier, worker_id=resolved_id, thread=thread)

    # spawn 优先：fork 会把父进程已打开的 sqlite 句柄复制进子进程（W9）。
    context = multiprocessing.get_context("spawn")
    _ensure_spawn(context)  # R4：即便将来有人改了上面那行，也不许 fork 过去
    process = context.Process(
        target=_process_main,
        args=(
            db_path,
            pool,
            execute,
            resolved_id,
            int(lease_seconds),
            float(heartbeat_interval),
            float(timeout),  # DAEMON 且 idle_timeout=None 时已在此前映射成 1800s
        ),
        name=f"worker-{resolved_id}",
        # 刻意不设 daemon=True：这一档要能跨调用存活，父进程退出不该带走它；
        # 收尾由 run_forever 的空闲自杀负责。
        daemon=False,
    )
    # R5：默认关。关的时候不登记（``kill_tree`` 不可用）。``setsid`` **不受这个
    # 开关控制**——它是 R1 的前提，且 win32 上本来就不调（没有进程组概念）。
    reaper = ProcessReaper() if isolation_enabled() else None
    if reaper is not None:
        # attach 必须在 start() 之前（Windows 要拿到 pid 前建好 Job Object）。
        reaper.attach(process)
    process.start()
    return LaunchHandle(
        tier=tier,
        worker_id=resolved_id,
        process=process,
        reaper=reaper,
    )


# --------------------------------------------------------------- 各档实现


def _run_inline(
    db_path: str,
    pool: str,
    execute: Callable[[WorkerContext], TaskResult],
    worker_id: str,
    lease_seconds: int,
    heartbeat_interval: float,
    idle_timeout: float | None,
) -> None:
    """W9：当前线程同步跑一次。``idle_timeout`` 在这里没有意义，忽略。"""
    store = Store(db_path, worker_id=worker_id)
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        worker = Worker(
            store,
            Control(conn),
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_interval=heartbeat_interval,
        )
        worker.run_once(pool, execute)
    finally:
        conn.close()
        store.close()


def _run_forever_in_owner_thread(
    db_path: str,
    pool: str,
    execute: Callable[[WorkerContext], TaskResult],
    worker_id: str,
    lease_seconds: int,
    heartbeat_interval: float,
    idle_timeout: float | None,
) -> None:
    """W9：在**本线程**里建连接，然后跑到空闲超时。

    线程与子进程共用这一段：两者都是"新执行体，自建连接"。
    """
    store = Store(db_path, worker_id=worker_id)
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        worker = Worker(
            store,
            Control(conn),
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_interval=heartbeat_interval,
        )
        worker.run_forever(pool, execute, idle_timeout=idle_timeout)
    finally:
        conn.close()
        store.close()


def _thread_main(
    db_path: str,
    pool: str,
    execute: Callable[[WorkerContext], TaskResult],
    worker_id: str,
    lease_seconds: int,
    heartbeat_interval: float,
    idle_timeout: float | None,
) -> None:
    """EMBEDDED 档的线程体。异常只记日志：线程没有返回值可传。"""
    try:
        _run_forever_in_owner_thread(
            db_path, pool, execute, worker_id, lease_seconds, heartbeat_interval, idle_timeout
        )
    except BaseException:  # noqa: BLE001 - 线程异常必须留痕，否则只剩一条 warning
        logger.exception("embedded worker 线程异常退出：worker_id=%s", worker_id)


def _process_main(
    db_path: str,
    pool: str,
    execute: Callable[[WorkerContext], TaskResult],
    worker_id: str,
    lease_seconds: int,
    heartbeat_interval: float,
    idle_timeout: float | None,
) -> None:
    """DAEMON 档的子进程体。异常记日志后**重新抛出**，让退出码反映失败。"""
    # R1：第一句，先于任何其它逻辑。让本进程成为新会话 + 新进程组的 leader，
    # 此后 ``os.killpg`` 能一次带走整棵树（含本进程 Popen 出来的孙进程）。
    # 不能事后补：孙进程一旦出生就已经继承了父进程的进程组，再也杀不到。
    # 极短窗口：start() 返回 ~ 执行到这一行之间父进程若崩溃，本进程会留在父的
    # 进程组里（无法消除，决议 R1 接受并记录）。
    # win32 上没有 os.setsid（进程组是 POSIX 概念），硬调会 AttributeError，让
    # DAEMON 档一进来就崩——那会让 reaper 的 Job Object 分支永远不可达。Windows
    # 的进程树回收走 Job Object，本来就不需要进程组，所以这里是设计上正确的分叉，
    # 不是妥协。
    if sys.platform != "win32":
        os.setsid()
    try:
        _run_forever_in_owner_thread(
            db_path, pool, execute, worker_id, lease_seconds, heartbeat_interval, idle_timeout
        )
    except BaseException:
        logger.exception("daemon worker 子进程异常退出：worker_id=%s", worker_id)
        raise
