"""Worker: claim -> execute -> heartbeat -> land (phase 3b, W1-W5/W8/W9).

Frozen contract: ``docs/design/orchestration-phase3b-worker-decisions.md``.

What this module is *not*: it does not decide which tier to use (that is
``dispatcher.choose_tier``), it does not start processes (``launcher.launch``),
and it does not know how to run an agent (the caller injects
``execute(ctx) -> TaskResult``, W1). No import of ``tools.*``.

Two invariants drive the shape of this file:

* **W2** -- the lease is renewed from a *separate thread* while ``execute``
  runs. A single ``heartbeat()`` before ``execute`` is not enough: a slow
  execute (tens of seconds) outlives ``lease_expires`` and ``patrol()`` blocks
  a task that is in fact alive.
* **W9** -- a sqlite3 connection never crosses a thread boundary. The heartbeat
  thread therefore opens its own ``Store`` and its own ``Control``; the
  ``WorkerContext`` handed to ``execute`` keeps the *caller's* connections,
  because ``execute`` runs on the caller's thread.

The heartbeat thread is also where commands are drained (W3): poll -> handle ->
**ack**, in that order. Acking first would lose a ``stop``/``steer`` for good if
the handler raised.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from agent.orchestration.control import Control
from agent.orchestration.store import FencedOutError, NotClaimableError, Store

__all__ = ["TaskResult", "Worker", "WorkerContext"]

logger = logging.getLogger(__name__)

#: How long ``run_forever`` sleeps between two empty claims. Also the upper
#: bound of the sleep, so a short ``idle_timeout`` is not overshot by much.
_IDLE_POLL_SECONDS = 0.5


class _SteerList(list):
    """``list[str]`` with a lock around ``append`` (W3).

    ``WorkerContext`` is frozen *and* slotted, so a ``threading.Lock`` field
    cannot be bolted on after construction without changing the frozen field
    list. Carrying the lock inside the list keeps the dataclass exactly as
    specified while still serialising the only mutation the heartbeat thread
    performs. Readers copy the list (``list(ctx.steers)``), which is atomic in
    CPython.
    """

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        with self._lock:
            super().append(text)


@dataclass(frozen=True, slots=True)
class WorkerContext:
    """Everything ``execute`` may touch. ``cancelled`` is set by the stop path."""

    store: Store
    control: Control
    worker_id: str
    task_id: str
    lease_epoch: int
    cancelled: threading.Event
    steers: list[str]


@dataclass(frozen=True, slots=True)
class TaskResult:
    """What ``execute`` reports back. ``reason`` is mandatory when ``ok=False``."""

    ok: bool
    output_path: str | None = None
    result_json: str | None = None
    reason: str | None = None


class Worker:
    """Claims one task at a time and lands it (W1-W5).

    Args:
        store: The caller's store. Used on the calling thread only (W9).
        control: The caller's control channel. Used on the calling thread only.
        worker_id: Non-empty identity; also the prefix of the heartbeat
            connection's own id.
        lease_seconds: Lease length handed to ``claim``/``heartbeat``.
        heartbeat_interval: Seconds between two renewals. Must be well below
            ``lease_seconds`` or ``patrol()`` will block a live task.

    The idle clock is ``store``'s injected ``now`` (see :meth:`run_forever`).
    Reading the private attribute is deliberate: the frozen ``__init__``
    signature has no ``now`` parameter, and inventing a second time source
    would make the store and the worker disagree about "now".
    """

    def __init__(
        self,
        store: Store,
        control: Control,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        heartbeat_interval: float = 5.0,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id 不能为空")
        if heartbeat_interval <= 0:
            raise ValueError(f"heartbeat_interval 必须 > 0，实际 {heartbeat_interval!r}")
        self._store = store
        self._control = control
        self._worker_id = worker_id
        self._lease_seconds = int(lease_seconds)
        self._heartbeat_interval = float(heartbeat_interval)
        # W9: the heartbeat thread needs the path, not the connection.
        self._db_path = store._db_path
        self._now = store.now

    # -- 主循环 -------------------------------------------------------------

    def run_once(
        self, pool: str, execute: Callable[[WorkerContext], TaskResult]
    ) -> bool:
        """Claim one task and run it to a landing point. ``False`` = nothing to do."""
        claimed = self._store.claim(pool, lease_seconds=self._lease_seconds)
        if claimed is None:
            return False

        # CLAIMED -> RUNNING before the heartbeat starts: ``cancel``/``complete``
        # both require RUNNING, and a stop command that lands on a CLAIMED row
        # would have no legal edge (``_ALLOWED[CLAIMED]`` has no CANCELLED).
        self._store.start(claimed.task_id, claimed.lease_epoch)

        ctx = WorkerContext(
            store=self._store,
            control=self._control,
            worker_id=self._worker_id,
            task_id=claimed.task_id,
            lease_epoch=claimed.lease_epoch,
            cancelled=threading.Event(),
            steers=_SteerList(),
        )

        thread, stop = self._start_heartbeat(ctx)
        try:
            result = self._execute(execute, ctx)
        finally:
            self._stop_heartbeat(thread, stop)

        self._land(ctx, claimed.card.output_path, result)
        return True

    def run_forever(
        self,
        pool: str,
        execute: Callable[[WorkerContext], TaskResult],
        *,
        idle_timeout: float | None = None,
    ) -> None:
        """Loop until ``idle_timeout`` seconds pass without a claim (W8).

        ``idle_timeout=None`` never exits -- the short-lived worker case, and
        what tests use. Time comes from the injected clock, so a test can push
        it forward instead of sleeping for real.
        """
        last_busy = self._now()
        while True:
            if self.run_once(pool, execute):
                last_busy = self._now()
                continue
            if idle_timeout is None:
                time.sleep(_IDLE_POLL_SECONDS)
                continue
            remaining = idle_timeout - (self._now() - last_busy)
            if remaining <= 0:
                logger.info(
                    "空闲 %.3fs 未领到任务，退出：worker_id=%s pool=%s",
                    idle_timeout,
                    self._worker_id,
                    pool,
                )
                return
            time.sleep(min(_IDLE_POLL_SECONDS, remaining))

    # -- 执行与落点 ---------------------------------------------------------

    def _execute(
        self, execute: Callable[[WorkerContext], TaskResult], ctx: WorkerContext
    ) -> TaskResult:
        """Run the injected body; an exception becomes ``ok=False`` (W5)."""
        try:
            result = execute(ctx)
        except Exception as exc:  # noqa: BLE001 - W5: 转成 TaskResult，堆栈进日志
            # The type name goes into ``reason`` (acceptance 7) and the full
            # stack into the log -- ``store.fail()`` writes only ``reason``.
            logger.exception(
                "execute 抛出异常：task_id=%s worker_id=%s", ctx.task_id, ctx.worker_id
            )
            return TaskResult(ok=False, reason=f"{type(exc).__name__}: {exc}")

        if not isinstance(result, TaskResult):
            return TaskResult(
                ok=False,
                reason=f"TypeError: execute 返回 {type(result).__name__}，期望 TaskResult",
            )
        return result

    def _land(self, ctx: WorkerContext, default_output_path: str, result: TaskResult) -> None:
        """Decide where the task goes (W5).

        The cancel branch is checked **first**: W3 has the heartbeat thread call
        ``store.cancel`` the moment a ``stop`` arrives, so by the time
        ``execute`` returns the row is already ``CANCELLED`` and a ``complete``
        would only raise ``NotClaimableError``. Row 1 of the W5 table ("ok=True
        -> complete") therefore only applies while the task is still RUNNING.
        """
        output_path = result.output_path or default_output_path
        try:
            if ctx.cancelled.is_set():
                self._cancel(ctx, result.reason or "stop 指令生效")
            elif result.ok:
                self._store.complete(
                    ctx.task_id,
                    ctx.lease_epoch,
                    output_path=output_path,
                    result_json=result.result_json,
                )
            else:
                self._store.fail(
                    ctx.task_id,
                    ctx.lease_epoch,
                    reason=result.reason or "execute 返回 ok=False 但未给 reason",
                )
        except FencedOutError:
            # The lease was taken over while we were executing. The row now
            # belongs to another worker; writing to it would clobber its work.
            logger.warning(
                "落点被 fence，放弃写回：task_id=%s epoch=%s",
                ctx.task_id,
                ctx.lease_epoch,
            )
            # R6: the write-back is abandoned, but the artifact is still sitting
            # at ``output_path``. Anyone reading the agreed path would pick up a
            # result the system never acknowledged -- worse than no artifact.
            self._void_artifact(output_path, ctx)

    def _void_artifact(self, output_path: str | None, ctx: WorkerContext) -> None:
        """R6: move a fenced artifact off its canonical path, unless someone owns it.

        The target is ``{output_path}.fenced-{epoch}``. Rename, never delete:
        the file may be the only evidence of what the stale worker produced.

        Ownership is decided from the database, not from the file. This runs
        only after ``complete()`` was fenced -- i.e. after the lease was lost --
        so any stat taken here may already be looking at the *new* holder's
        file. A file identity cannot separate "mine" from "theirs"; the row
        can, because it knows whether the result was accepted and who holds the
        task now.

        Two consequences are deliberate and must not be "fixed" later:

        * ``SUCCEEDED`` -- the artifact is acknowledged, never touch it.
        * Held by another worker -- the file may already be theirs, so the
          stale artifact stays at the canonical path. An artifact that *might*
          be stale beats deleting one that *might* be the acknowledged result.
          ``patrol``/``redispatch`` move the row on; a later pass then judges
          against a different holder.

        Every failure is logged and swallowed. Voiding is best-effort; a
        read-only directory or a vanished file must not take the worker down.
        """
        if not output_path:
            return
        try:
            row = self._store.query(
                "SELECT state, claimed_by FROM tasks WHERE task_id = ?",
                (ctx.task_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            # Cannot judge ownership -> do not touch the file: keeping one that
            # might be new is recoverable, deleting one is not.
            logger.warning(
                "查询任务归属失败，不作废：task_id=%s：%s: %s",
                ctx.task_id,
                type(exc).__name__,
                exc,
            )
            return
        if row is not None:
            if str(row["state"]) == "SUCCEEDED":
                logger.warning(
                    "任务已被承认（SUCCEEDED），产物不作废：task_id=%s path=%s",
                    ctx.task_id,
                    output_path,
                )
                return
            holder = row["claimed_by"]
            if holder is not None and str(holder) != ctx.worker_id:
                logger.warning(
                    "任务已被新持有者 %s 持有，产物不作废：task_id=%s path=%s",
                    str(holder),
                    ctx.task_id,
                    output_path,
                )
                return
        fenced_path = f"{output_path}.fenced-{ctx.lease_epoch}"
        try:
            os.replace(output_path, fenced_path)
        except FileNotFoundError:
            # Raced away between the ownership query and the rename.
            logger.info(
                "产物在作废前消失：task_id=%s path=%s", ctx.task_id, output_path
            )
        except OSError as exc:
            logger.warning(
                "产物改名失败，放弃作废：task_id=%s path=%s -> %s：%s: %s",
                ctx.task_id,
                output_path,
                fenced_path,
                type(exc).__name__,
                exc,
            )
        else:
            logger.warning(
                "产物已作废（改名）：task_id=%s epoch=%s path=%s -> %s",
                ctx.task_id,
                ctx.lease_epoch,
                output_path,
                fenced_path,
            )

    def _cancel(self, ctx: WorkerContext, reason: str) -> None:
        """``RUNNING -> CANCELLED``, tolerating "already cancelled"."""
        try:
            self._store.cancel(ctx.task_id, ctx.lease_epoch, reason=reason)
        except NotClaimableError:
            # The heartbeat thread got there first (that is the normal path), or
            # the task already left RUNNING. Either way the intent is recorded.
            logger.info("任务已不在 RUNNING，取消视为已生效：task_id=%s", ctx.task_id)

    # -- heartbeat 线程 (W2 + W3 + W9) --------------------------------------

    def _start_heartbeat(self, ctx: WorkerContext) -> tuple[threading.Thread, threading.Event]:
        stop = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(ctx, stop),
            name=f"worker-hb-{ctx.task_id}",
            daemon=True,
        )
        thread.start()
        return thread, stop

    def _stop_heartbeat(self, thread: threading.Thread, stop: threading.Event) -> None:
        stop.set()
        thread.join(timeout=max(1.0, self._heartbeat_interval * 2))

    def _heartbeat_loop(self, ctx: WorkerContext, stop: threading.Event) -> None:
        """Renew the lease and drain commands until ``stop`` is set.

        W9: this thread opens its **own** ``Store`` and ``Control``. Sharing the
        caller's connection would raise ``sqlite3.ProgrammingError`` (or, with
        ``check_same_thread=False``, hand out a half-committed view).
        """
        store: Store | None = None
        conn: sqlite3.Connection | None = None
        try:
            store = Store(self._db_path, worker_id=f"{self._worker_id}:heartbeat")
            conn = sqlite3.connect(self._db_path, isolation_level=None)
            control = Control(conn)
            while not stop.wait(self._heartbeat_interval):
                try:
                    store.heartbeat(
                        ctx.task_id,
                        ctx.lease_epoch,
                        lease_seconds=self._lease_seconds,
                    )
                except FencedOutError:
                    # W2: the lease was taken over -> this worker must stop.
                    logger.warning(
                        "续租被 fence，worker 停手：task_id=%s epoch=%s",
                        ctx.task_id,
                        ctx.lease_epoch,
                    )
                    ctx.cancelled.set()
                    return
                self._drain_commands(ctx, store, control)
        except BaseException:  # noqa: BLE001 - 线程静默死掉会让任务被 patrol 判死
            logger.exception("heartbeat 线程异常退出：task_id=%s", ctx.task_id)
            ctx.cancelled.set()
        finally:
            if conn is not None:
                conn.close()
            if store is not None:
                store.close()

    def _drain_commands(
        self, ctx: WorkerContext, store: Store, control: Control
    ) -> None:
        """poll -> handle -> ack (W3). Acking first would lose commands."""
        commands = control.poll(ctx.task_id, ctx.lease_epoch)
        if not commands:
            return
        handled: list[int] = []
        for command in commands:
            if command.kind == "stop":
                ctx.cancelled.set()
                self._cancel_with(store, ctx, command.payload or "stop 指令生效")
            elif command.kind == "steer":
                if command.payload is not None:
                    ctx.steers.append(command.payload)
            else:
                # budget_update 等留给后续阶段：不处理就不 ack，下轮还会再来。
                logger.debug(
                    "忽略未知指令 kind=%s task_id=%s", command.kind, ctx.task_id
                )
                continue
            handled.append(command.cmd_id)
        control.ack(handled)

    def _cancel_with(self, store: Store, ctx: WorkerContext, reason: str) -> None:
        """Cancel through the heartbeat thread's own store (W9)."""
        try:
            store.cancel(ctx.task_id, ctx.lease_epoch, reason=reason)
        except FencedOutError:
            ctx.cancelled.set()
        except NotClaimableError:
            logger.info("任务已不在 RUNNING，stop 视为已生效：task_id=%s", ctx.task_id)
