"""跨进程控制通道（阶段 3a）。

冻结决议：``docs/design/orchestration-phase3a-control-decisions.md``（D1-D8）。

本模块只做**存储侧**：发指令、取指令、确认、按所有权列任务。不跑任务、不发
信号、不杀进程——承载方式（inline/embedded/daemon）留给后续阶段。

行为契约抄自 ``tools/delegate_tool.py`` 的同进程 ``action=list/stop/steer``，
跨进程版必须保住它：

* ``stop`` 在**下一个迭代边界**生效，不是 SIGKILL：这里只落一条 ``stop`` 指令，
  由 worker 在自己选的边界收敛到 ``CANCELLED``；
* ``steer`` 追加到**下一个 tool result**，当前 tool call 永不切断：同样只落指令；
* ``steer`` 未送达时由 worker 以 ``missed_steer`` 回报——本模块不替它吞掉；
* ``list`` 只能看**本调用方范围内**的任务（D5，安全项，不是可选项）。

D1：``Control`` 接收一条**已打开**的连接，自己开 ``BEGIN IMMEDIATE``，不 import
``Store``、不碰 ``store._conn``。连接必须是自动提交模式
（``isolation_level=None``）且当前没有未提交的事务，否则 ``BEGIN IMMEDIATE``
会抛 ``sqlite3.OperationalError``——报错好过静默降级（D8）。

行访问一律用**位置下标**，不依赖调用方的 ``row_factory``：跨进程场景下每条
连接由各自的进程建，本模块不对别人连接的配置做任何假设。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from agent.orchestration.contracts import TERMINAL_STATES, TaskState
from agent.orchestration.state_machine import transition

__all__ = [
    "Command",
    "Control",
    "ControlError",
    "NotOwnedError",
    "TargetGoneError",
    "TaskView",
]


# ------------------------------------------------------------------ 数据契约


@dataclass(frozen=True, slots=True)
class Command:
    """一条待投递的控制指令。``lease_epoch`` 是它的归属时代（D2）。"""

    cmd_id: int
    task_id: str
    lease_epoch: int
    kind: str  # 'steer' | 'stop' | 'budget_update'
    payload: str | None
    created_at: float


@dataclass(frozen=True, slots=True)
class TaskView:
    """任务只读视图。``goal`` 取自 ``card_json``（``tasks`` 表没有 goal 列）。"""

    task_id: str
    parent_task_id: str | None
    batch_id: str
    goal: str
    state: str
    pool: str
    attempts: int
    lease_epoch: int
    claimed_by: str | None
    cancel_requested: bool
    started_at: float | None
    updated_at: float


class ControlError(Exception):
    """控制通道错误基类。"""


class NotOwnedError(ControlError):
    """``list_children`` 没给所有权范围（D5）。"""


class TargetGoneError(ControlError):
    """任务不存在、已终态，或当前状态不接受该动作（D3/D4）。"""


# ---------------------------------------------------------------- SQL 常量

#: D3 的读侧：一次读齐判定所需的状态、时代与卡片快照。
_SELECT_TASK = (
    "SELECT state, lease_epoch, attempts, handoff_count, card_json "
    "FROM tasks WHERE task_id = ?"
)

#: D3 无持有者路径：直接取消。``AND state = :expected`` 是并发闸，rowcount 必须为 1。
_CANCEL_SQL = """
UPDATE tasks SET state = :cancelled, completed_at = :now, updated_at = :now
 WHERE task_id = :task_id AND state = :expected
"""

#: D3 有持有者路径：落指令。payload 为 NULL——stop 不需要文本。
_INSERT_STOP_SQL = """
INSERT INTO task_commands (task_id, lease_epoch, kind, payload, created_at)
VALUES (:task_id, :epoch, 'stop', NULL, :now)
"""

#: H5：``cancel_requested_at`` 记录"已请求但尚未生效"。任务本身仍是 RUNNING。
_MARK_CANCEL_REQUESTED_SQL = """
UPDATE tasks SET cancel_requested_at = :now, updated_at = :now
 WHERE task_id = :task_id AND lease_epoch = :epoch
   AND state IN ('CLAIMED', 'RUNNING')
"""

_INSERT_STEER_SQL = """
INSERT INTO task_commands (task_id, lease_epoch, kind, payload, created_at)
VALUES (:task_id, :epoch, 'steer', :payload, :now)
"""

#: D2：只取本时代的未确认指令。
_PENDING_SQL = """
SELECT cmd_id, task_id, lease_epoch, kind, payload, created_at
  FROM task_commands
 WHERE task_id = :task_id AND lease_epoch = :epoch AND acked_at IS NULL
 ORDER BY cmd_id ASC
"""

#: D2：**之前** attempt 的残留（持有者已死），同一次 poll 里顺手清掉。
#: 必须是严格小于：僵尸 worker 只能确认自己之前的时代，不能确认之后的时代。
_ACK_STALE_SQL = """
UPDATE task_commands SET acked_at = :now
 WHERE task_id = :task_id AND lease_epoch < :epoch AND acked_at IS NULL
"""

#: D6：幂等确认，只有 ``acked_at IS NULL`` 的行会被改。
_ACK_SQL = """
UPDATE task_commands SET acked_at = :now
 WHERE cmd_id = :cmd_id AND acked_at IS NULL
"""

#: D5 的只读投影。列序即 ``_task_view`` 的解包顺序。
_SELECT_VIEW = (
    "SELECT task_id, parent_task_id, batch_id, card_json, state, pool, attempts, "
    "lease_epoch, claimed_by, cancel_requested_at, started_at, updated_at "
    "FROM tasks"
)

#: D3：没有持有者，写指令没人读。取消要立刻生效。
_UNOWNED_STATES: frozenset[TaskState] = frozenset(
    {TaskState.QUEUED, TaskState.BLOCKED}
)

#: D3/D4：有活着的持有者，只能走指令通道。
_OWNED_STATES: frozenset[TaskState] = frozenset(
    {TaskState.CLAIMED, TaskState.RUNNING}
)


def _goal_from_card(card_json: object) -> str:
    """Best-effort ``goal`` extraction; never raises.

    ``card_json`` is written by :meth:`Store.enqueue` and normally well-formed,
    but this projection feeds the control channel's listing path: one corrupt
    row must not blind the caller to every other child. A row with broken JSON
    or a missing ``goal`` key shows an empty goal instead of aborting the whole
    listing.
    """
    try:
        data = json.loads(str(card_json))
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    goal = data.get("goal")
    return "" if goal is None else str(goal)


def _task_view(row: Sequence[Any]) -> TaskView:
    """把 ``_SELECT_VIEW`` 的一行解成 :class:`TaskView`。"""
    (
        task_id,
        parent_task_id,
        batch_id,
        card_json,
        state,
        pool,
        attempts,
        lease_epoch,
        claimed_by,
        cancel_requested_at,
        started_at,
        updated_at,
    ) = row
    return TaskView(
        task_id=str(task_id),
        parent_task_id=None if parent_task_id is None else str(parent_task_id),
        batch_id=str(batch_id),
        goal=_goal_from_card(card_json),
        state=str(state),
        pool=str(pool),
        attempts=int(attempts),
        lease_epoch=int(lease_epoch),
        claimed_by=None if claimed_by is None else str(claimed_by),
        cancel_requested=cancel_requested_at is not None,
        started_at=None if started_at is None else float(started_at),
        updated_at=float(updated_at),
    )


# ------------------------------------------------------------------- Control


class Control:
    """跨进程控制通道。只持有一条调用方给的连接（D1）。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._conn = conn
        self._now = now

    # -- 事务 ---------------------------------------------------------------

    @contextlib.contextmanager
    def _write_tx(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` .. ``COMMIT``，任何异常都回滚（D7）。"""
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        if conn.in_transaction:
            conn.execute("COMMIT")

    def _load(
        self, conn: sqlite3.Connection, task_id: str
    ) -> tuple[TaskState, int, int, int, str]:
        """读任务当前态、时代、attempts、handoff_count、card_json。

        Raises:
            TargetGoneError: 任务不存在。
        """
        row = conn.execute(_SELECT_TASK, (task_id,)).fetchone()
        if row is None:
            raise TargetGoneError(f"任务不存在：{task_id}")
        state, epoch, attempts, handoff_count, card_json = row
        return (
            TaskState(state),
            int(epoch),
            int(attempts),
            int(handoff_count),
            str(card_json),
        )

    # -- 写指令 -------------------------------------------------------------

    def request_stop(self, task_id: str) -> str:
        """请求停止；返回 ``'queued'``（已投递指令）或 ``'cancelled'``（未领取，直接取消）。

        D3 的两条路，按任务当前状态分派：

        ====================  ====================================  ===========
        当前状态              动作                                  返回
        ====================  ====================================  ===========
        ``QUEUED``/``BLOCKED``  ``transition -> CANCELLED``，不写指令  ``'cancelled'``
        ``CLAIMED``/``RUNNING``  写 ``stop`` 指令 + 置 ``cancel_requested_at``  ``'queued'``
        终态                   抛 :class:`TargetGoneError`             —
        ====================  ====================================  ===========

        未领取的任务没有持有者，写指令没人会读，只会留一条永远不被 ack 的垃圾。

        Raises:
            TargetGoneError: 任务不存在或已终态。
            ControlError: 状态既不在无持有者集合也不在有持有者集合（数据异常）。
        """
        now = self._now()
        with self._write_tx() as conn:
            current, epoch, attempts, handoff_count, card_json = self._load(
                conn, task_id
            )

            if current in TERMINAL_STATES:
                raise TargetGoneError(
                    f"任务已终态，无法 stop：task_id={task_id} state={current}"
                )

            if current in _UNOWNED_STATES:
                # 未领取的任务：没有持有者，指令通道是死信。直接取消。
                card = json.loads(card_json)
                transition(
                    current,
                    TaskState.CANCELLED,
                    max_retries=int(card["max_retries"]),
                    attempts=attempts,
                    handoff_count=handoff_count,
                    handoff_cap=int(card["max_handoffs"]),
                )
                cursor = conn.execute(
                    _CANCEL_SQL,
                    {
                        "cancelled": TaskState.CANCELLED.value,
                        "now": now,
                        "task_id": task_id,
                        "expected": current.value,
                    },
                )
                if cursor.rowcount != 1:
                    raise ControlError(
                        f"取消未命中：task_id={task_id} 期望 state={current}，"
                        f"影响 {cursor.rowcount} 行"
                    )
                return "cancelled"

            if current in _OWNED_STATES:
                conn.execute(
                    _INSERT_STOP_SQL,
                    {"task_id": task_id, "epoch": epoch, "now": now},
                )
                cursor = conn.execute(
                    _MARK_CANCEL_REQUESTED_SQL,
                    {"now": now, "task_id": task_id, "epoch": epoch},
                )
                if cursor.rowcount != 1:
                    raise ControlError(
                        f"标记 cancel_requested_at 未命中：task_id={task_id} "
                        f"lease_epoch={epoch}，影响 {cursor.rowcount} 行"
                    )
                return "queued"

            raise ControlError(
                f"任务状态既无持有者也不可控制：task_id={task_id} state={current}"
            )

    def request_steer(self, task_id: str, text: str) -> int:
        """追加一条 steer 指令，返回 ``cmd_id``。

        可达性判定是**近似**，不是精确语义（D4）：库里没有 ``accepting_steer``
        列（那是旧内存记录的字段），这里用状态近似——只有 ``CLAIMED`` /
        ``RUNNING`` 可 steer。真正的"是否还在接受 steer"由 worker 在迭代边界
        决定：它若已过边界，文本以 ``missed_steer`` 回报，而不是被这里静默丢弃。

        ``payload`` 逐字保存调用方给的文本（不 strip、不改写）；只有空白校验
        用 strip 后的结果。

        Raises:
            ValueError: ``text`` 去空白后为空。
            TargetGoneError: 任务不存在、已终态或当前状态不接受 steer。
        """
        if not text.strip():
            raise ValueError("steer 文本不能为空或纯空白")

        now = self._now()
        with self._write_tx() as conn:
            current, epoch, _attempts, _handoff_count, _card_json = self._load(
                conn, task_id
            )
            if current not in _OWNED_STATES:
                raise TargetGoneError(
                    f"任务当前状态不接受 steer：task_id={task_id} state={current}"
                )
            cursor = conn.execute(
                _INSERT_STEER_SQL,
                {"task_id": task_id, "epoch": epoch, "payload": text, "now": now},
            )
            cmd_id = cursor.lastrowid
        if cmd_id is None:
            raise ControlError(f"steer 指令未写入：task_id={task_id}")
        return int(cmd_id)

    # -- 读指令（worker 侧）------------------------------------------------

    def poll(self, task_id: str, epoch: int) -> list[Command]:
        """返回该任务**当前 epoch** 的未确认指令；顺带 ack 掉过期 epoch 的指令。

        D2：``lease_epoch < :epoch`` 的未确认指令是之前 attempt 的残留（那些
        worker 已经死了）。不清理会永久堆积，且下个 attempt 会重复执行别人时代
        的指令——所以它们在**同一次事务**里被 ack 掉，且不出现在返回值里。

        边界必须是**严格小于**，不能写成 ``<>``：``<>`` 会把 ``lease_epoch >
        :epoch`` 的指令也 ack 掉。僵尸 worker（旧 epoch 但进程还活着）醒来 poll
        一次，就会吞掉现役 worker 尚未执行的 steer/stop。worker 只能确认自己之前
        的时代，不能确认自己之后的时代。

        任务不存在时返回空列表，不抛错：poll 是 heartbeat 侧的幂等读，worker
        在收尾阶段 poll 一个已删除的任务不应炸掉自己的循环。
        """
        now = self._now()
        with self._write_tx() as conn:
            conn.execute(
                _ACK_STALE_SQL,
                {"now": now, "task_id": task_id, "epoch": int(epoch)},
            )
            rows = conn.execute(
                _PENDING_SQL, {"task_id": task_id, "epoch": int(epoch)}
            ).fetchall()
        return [
            Command(
                cmd_id=int(row[0]),
                task_id=str(row[1]),
                lease_epoch=int(row[2]),
                kind=str(row[3]),
                payload=None if row[4] is None else str(row[4]),
                created_at=float(row[5]),
            )
            for row in rows
        ]

    def ack(self, cmd_ids: Sequence[int]) -> int:
        """确认已执行；幂等，返回本次**真正改变**的行数（D6）。

        空输入直接返回 0，不开写事务——没有要改的行就没有写。
        """
        ids = [int(cmd_id) for cmd_id in cmd_ids]
        if not ids:
            return 0
        now = self._now()
        changed = 0
        with self._write_tx() as conn:
            for cmd_id in ids:
                cursor = conn.execute(_ACK_SQL, {"now": now, "cmd_id": cmd_id})
                changed += cursor.rowcount
        return changed

    # -- 列任务 -------------------------------------------------------------

    def list_children(
        self,
        *,
        parent_task_id: str | None = None,
        batch_id: str | None = None,
    ) -> list[TaskView]:
        """按所有权范围列任务；两个参数**至少给一个**，否则抛 :class:`NotOwnedError`。

        D5（安全项）：旧实现的 ``list`` 用 spawn 树过滤，等价于"只看自己的子
        任务"。跨进程后若不强制给范围，这里就变成全库 dump，一个会话能看到另
        一个会话的子任务。两个都给时取**交集**（AND），不是并集——范围只会更
        窄，不会更宽。

        Raises:
            NotOwnedError: 两个参数都没给（含空字符串）。
        """
        if not parent_task_id and not batch_id:
            raise NotOwnedError(
                "list_children 必须给 parent_task_id 或 batch_id："
                "无范围查询等于全库 dump，会泄漏其他会话的子任务（D5）"
            )

        clauses: list[str] = []
        params: list[object] = []
        if parent_task_id:
            clauses.append("parent_task_id = ?")
            params.append(parent_task_id)
        if batch_id:
            clauses.append("batch_id = ?")
            params.append(batch_id)

        where = " AND ".join(clauses)
        sql = f"{_SELECT_VIEW} WHERE {where} ORDER BY created_at ASC, task_id ASC"
        rows = self._conn.execute(sql, params).fetchall()
        return [_task_view(row) for row in rows]
