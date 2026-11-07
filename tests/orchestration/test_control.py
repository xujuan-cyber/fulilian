"""``agent.orchestration.control`` 的测试（阶段 3a，决议 D1-D8）。

每条测试都点名它钉住的决议。跨进程那条（验收 ①）在
``test_control_multiprocess.py``，由另一条并行任务写，这里不重复。

``Control`` 与 ``Store`` 各持一条连接：``Store`` 负责造任务（走真实的
enqueue/claim/start 路径，``lease_epoch`` 才是真的），``Control`` 用一条独立
的自动提交连接——这正是跨进程时的形态。
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.control import (
    Command,
    Control,
    ControlError,
    NotOwnedError,
    TargetGoneError,
    TaskView,
)
from agent.orchestration.store import Store


# ------------------------------------------------------------------- helpers


def _card(task_id: str = "t1", *, max_retries: int = 1) -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"goal of {task_id}",
        dod=("done",),
        output_path=f"/tmp/out/{task_id}.md",
        max_retries=max_retries,
    )


@pytest.fixture()
def ctx(tmp_path):
    """``(store, control, conn)``：两条独立连接指向同一个文件库。"""
    path = str(tmp_path / "orchestration.db")
    store = Store(path, worker_id="w1")
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        yield store, Control(conn), conn
    finally:
        conn.close()
        store.close()


def _running(store: Store, task_id: str = "t1") -> int:
    """造一个 ``RUNNING`` 任务，返回它的 ``lease_epoch``。"""
    store.enqueue(_card(task_id))
    claimed = store.claim("solve")
    assert claimed is not None and claimed.task_id == task_id
    store.start(claimed.task_id, claimed.lease_epoch)
    return claimed.lease_epoch


def _state(conn: sqlite3.Connection, task_id: str) -> str:
    row = conn.execute(
        "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    return str(row[0])


def _cancel_requested_at(conn: sqlite3.Connection, task_id: str) -> float | None:
    return conn.execute(
        "SELECT cancel_requested_at FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()[0]


def _commands(conn: sqlite3.Connection, task_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT cmd_id, kind, lease_epoch, payload, acked_at FROM task_commands "
        "WHERE task_id = ? ORDER BY cmd_id",
        (task_id,),
    ).fetchall()


def _acked_at(conn: sqlite3.Connection, cmd_id: int) -> float | None:
    return conn.execute(
        "SELECT acked_at FROM task_commands WHERE cmd_id = ?", (cmd_id,)
    ).fetchone()[0]


def _set_parent(conn: sqlite3.Connection, task_id: str, parent: str) -> None:
    """``Store.enqueue`` 不写 ``parent_task_id``（单进程下由 spawn 树承载）。"""
    conn.execute(
        "UPDATE tasks SET parent_task_id = ? WHERE task_id = ?", (parent, task_id)
    )


# --------------------------------------------------------------------- tests


def test_stop_on_queued_task_cancels_without_command(ctx) -> None:
    """D3 + 验收 ⑥：未领取的任务直接取消，``task_commands`` 不新增行。"""
    store, control, conn = ctx
    store.enqueue(_card("t1"))
    assert _commands(conn, "t1") == []

    assert control.request_stop("t1") == "cancelled"

    assert _state(conn, "t1") == "CANCELLED"
    row = conn.execute(
        "SELECT completed_at FROM tasks WHERE task_id = ?", ("t1",)
    ).fetchone()
    assert row[0] is not None, "取消必须落 completed_at"
    assert _commands(conn, "t1") == [], "无持有者时写指令只会留一条永不 ack 的垃圾"
    assert _cancel_requested_at(conn, "t1") is None


def test_stop_on_running_task_queues_command(ctx) -> None:
    """D3：有持有者时写 ``stop`` 指令 + ``cancel_requested_at``，**不硬切**。"""
    store, control, conn = ctx
    epoch = _running(store)

    assert control.request_stop("t1") == "queued"

    commands = _commands(conn, "t1")
    assert len(commands) == 1
    _cmd_id, kind, cmd_epoch, payload, acked_at = commands[0]
    assert kind == "stop"
    assert cmd_epoch == epoch, "指令必须绑在写入时的 lease_epoch 上"
    assert payload is None
    assert acked_at is None
    assert _cancel_requested_at(conn, "t1") is not None
    # 契约 §二：stop 在下一个迭代边界生效，不是 SIGKILL。
    assert _state(conn, "t1") == "RUNNING"


def test_steer_roundtrip_and_ack(ctx) -> None:
    """D4 + 验收 ②：文本逐字送达，ack 后不再返回。"""
    store, control, conn = ctx
    epoch = _running(store)
    text = "把结论先写成三行摘要，再展开；不要动 tools/ 下的代码。"

    cmd_id = control.request_steer("t1", text)

    pending = control.poll("t1", epoch)
    assert len(pending) == 1
    assert isinstance(pending[0], Command)
    assert pending[0].cmd_id == cmd_id
    assert pending[0].kind == "steer"
    assert pending[0].payload == text, "steer 文本必须逐字相等"
    assert pending[0].lease_epoch == epoch

    assert control.ack([cmd_id]) == 1
    assert control.poll("t1", epoch) == []

    # D4：只有 CLAIMED/RUNNING 可 steer；其余状态抛 TargetGoneError。
    store.enqueue(_card("t2"))
    with pytest.raises(TargetGoneError):
        control.request_steer("t2", "还没开始跑")
    with pytest.raises(ValueError):
        control.request_steer("t1", "   ")


def test_poll_discards_stale_epoch_commands(ctx) -> None:
    """D2 + 验收 ③：过期 epoch 的指令被 ack 掉且不返回；D7：poll 也开写事务。"""
    store, control, conn = ctx
    epoch = _running(store)
    stale_id = control.request_steer("t1", "上一个 attempt 的残留")

    trace: list[str] = []
    conn.set_trace_callback(trace.append)
    try:
        assert control.poll("t1", epoch + 1) == []
    finally:
        conn.set_trace_callback(None)

    assert _acked_at(conn, stale_id) is not None, "过期指令必须被顺带 ack 掉"
    assert any(
        sql.lstrip().upper().startswith("BEGIN IMMEDIATE") for sql in trace
    ), "poll 要顺带 ack，必须走 BEGIN IMMEDIATE（D7）"

    # 清理只针对"别的时代"：新指令绑在当前时代，用当前时代 poll 照旧取到。
    fresh_id = control.request_steer("t1", "这个时代的指令")
    assert [cmd.cmd_id for cmd in control.poll("t1", epoch)] == [fresh_id]
    assert _acked_at(conn, fresh_id) is None


def test_list_children_scoped_to_parent(ctx) -> None:
    """D5 + 验收 ④：只返回指定范围内的任务，两个 parent 不互相泄漏。"""
    store, control, conn = ctx
    for task_id, batch in (
        ("p1", "b1"),
        ("p2", "b2"),
        ("c1", "b1"),
        ("c2", "b1"),
        ("c3", "b2"),
    ):
        store.enqueue(_card(task_id), batch_id=batch)
    _set_parent(conn, "c1", "p1")
    _set_parent(conn, "c2", "p1")
    _set_parent(conn, "c3", "p2")

    views = control.list_children(parent_task_id="p1")
    assert {view.task_id for view in views} == {"c1", "c2"}
    assert all(isinstance(view, TaskView) for view in views)
    assert {view.parent_task_id for view in views} == {"p1"}
    assert {view.goal for view in views} == {"goal of c1", "goal of c2"}

    # 另一个会话的范围看不到 p1 的子任务。
    assert {v.task_id for v in control.list_children(parent_task_id="p2")} == {"c3"}

    # batch 范围独立生效。
    assert {v.task_id for v in control.list_children(batch_id="b2")} == {"p2", "c3"}

    # 两个都给 = 交集，只会更窄。
    assert control.list_children(parent_task_id="p1", batch_id="b2") == []


def test_list_children_requires_ownership_scope(ctx) -> None:
    """D5 + 验收 ⑤：不给范围一律抛 ``NotOwnedError``，不返回任何行。"""
    store, control, _conn = ctx
    store.enqueue(_card("t1"))

    for kwargs in (
        {},
        {"parent_task_id": None},
        {"batch_id": None},
        {"parent_task_id": None, "batch_id": None},
        {"parent_task_id": "", "batch_id": ""},
    ):
        with pytest.raises(NotOwnedError):
            control.list_children(**kwargs)

    assert issubclass(NotOwnedError, ControlError)


def test_ack_is_idempotent(ctx) -> None:
    """D6：重复 ack 不报错，返回真实改变的行数。"""
    store, control, _conn = ctx
    epoch = _running(store)
    cmd_id = control.request_steer("t1", "只该被确认一次")
    assert epoch == 1

    assert control.ack([cmd_id]) == 1
    assert control.ack([cmd_id]) == 0
    assert control.ack([cmd_id, cmd_id]) == 0
    assert control.ack([]) == 0
    assert control.ack([cmd_id + 999]) == 0


def test_stop_on_terminal_task_raises(ctx) -> None:
    """D3：终态与不存在的任务都抛 ``TargetGoneError``，且不留指令。"""
    store, control, conn = ctx
    store.enqueue(_card("t1"))
    claimed = store.claim("solve")
    assert claimed is not None
    store.start(claimed.task_id, claimed.lease_epoch)
    store.complete(claimed.task_id, claimed.lease_epoch, output_path="/tmp/out/t1.md")
    assert _state(conn, "t1") == "SUCCEEDED"

    with pytest.raises(TargetGoneError):
        control.request_stop("t1")
    with pytest.raises(TargetGoneError):
        control.request_stop("never-existed")

    assert _commands(conn, "t1") == []
    assert _state(conn, "t1") == "SUCCEEDED"


def test_poll_does_not_swallow_newer_epoch_commands(ctx) -> None:
    """D2 的边界：僵尸 worker 只能 ack 自己**之前**时代的指令，不能 ack 之后的。

    场景：worker A 持 epoch 1 但已是僵尸（租约过期、进程没死），worker B 已被接管
    到 epoch 2 并在跑。A 醒来 poll 一次，若 stale-ack 写成 ``lease_epoch <> :epoch``，
    就会把 **B 尚未执行的指令**当成"残留"确认掉——B 永远看不到，A 也不会执行它。
    """
    store, control, conn = ctx
    epoch = _running(store)
    old_id = control.request_steer("t1", "给 epoch 1 的指令")
    # 模拟被接管：真实路径是 claim 时 lease_epoch + 1。
    conn.execute(
        "UPDATE tasks SET lease_epoch = ? WHERE task_id = ?", (epoch + 1, "t1")
    )
    new_id = control.request_steer("t1", "给 epoch 2 的指令")

    pending = control.poll("t1", epoch)
    assert [cmd.cmd_id for cmd in pending] == [old_id]
    assert {cmd.lease_epoch for cmd in pending} == {epoch}

    assert control.ack([old_id]) == 1
    assert _acked_at(conn, old_id) is not None
    # 关键断言：现任时代的指令**没有被 ack**。写成 ``<>`` 的实现会在这里变红。
    assert _acked_at(conn, new_id) is None, "僵尸 worker 不得吞掉新持有者的指令"

    # 现任 worker 照样能取到自己的指令。
    assert [cmd.cmd_id for cmd in control.poll("t1", epoch + 1)] == [new_id]


def test_list_children_tolerates_malformed_card_json(ctx) -> None:
    """一行脏 ``card_json`` 不能让整个列表崩掉。

    ``list_children`` 是控制通道的列表路径（TUI 直接读）。若 ``_task_view`` 对
    ``card_json`` 直接 ``json.loads(...)["goal"]``，一条损坏记录就会让调用方
    **看不见所有子任务**——比这一行数据本身坏掉严重得多。
    """
    _store, control, conn = ctx

    rows = [
        ("good", '{"goal": "正常的任务"}'),
        ("broken", "{not json at all"),
        ("nogoal", '{"other": 1}'),
    ]
    for task_id, card_json in rows:
        conn.execute(
            "INSERT INTO tasks(task_id,batch_id,role,pool,state,card_json,"
            "created_at,updated_at,output_path,parent_task_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                "b",
                "leaf",
                "solve",
                "QUEUED",
                card_json,
                1.0,
                1.0,
                f"/tmp/{task_id}.md",
                "P",
            ),
        )
    conn.commit()

    views = {v.task_id: v for v in control.list_children(parent_task_id="P")}

    assert set(views) == {"good", "broken", "nogoal"}, "坏数据不能把整行丢掉"
    assert views["good"].goal == "正常的任务"
    assert views["broken"].goal == ""
    assert views["nogoal"].goal == ""
