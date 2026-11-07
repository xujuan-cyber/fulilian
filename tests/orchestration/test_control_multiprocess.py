"""阶段 3a 跨进程验收：另一个进程投递的指令，本进程必须能取到。

覆盖 ``docs/design/orchestration-phase3a-control-decisions.md`` §五 的 ①，
外加两条决议没有单列、但跨进程语义必须守住的边界：

===========================================================  ==========================
①  ``test_cross_process_stop_within_one_heartbeat``           子进程 post stop，父进程一次 poll 取到
②  ``test_cross_process_steer_text_survives_roundtrip``      中文/换行/引号逐字往返
③  ``test_cross_process_list_does_not_leak_across_parents``  两个 parent 的子树互不可见
===========================================================  ==========================

三条硬约束，违反其中任何一条本文件就会变成假绿：

1. **必须用文件库**。``:memory:`` 不跨进程共享，每个进程各自拿到一个空库，
   于是"子进程写了、父进程读到了"这件事根本没被验证——两边各写各的空库也能
   全绿。库一律建在 ``tmp_path`` 下。
2. **每个进程自己 ``sqlite3.connect``**。连接对象不可跨进程传递；父进程在
   ``fork`` 前把 ``Store`` 关掉，子进程里重开。
3. **断言不放宽**。``control.py`` 违反冻结决议就报，不改测试迁就实现。
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sqlite3
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import pytest

from agent.orchestration.config import OrchestrationConfig
from agent.orchestration.contracts import TaskCard
from agent.orchestration.control import Control
from agent.orchestration.schema import configure_connection
from agent.orchestration.store import Store

#: ``fork`` + 文件库 + 多进程语义，非 Linux 宿主上跑不出结论。
pytestmark = pytest.mark.linux_only

#: 验收 ① 的时间上界：一个 heartbeat 周期（决议 §五 ①）。
#: 取 ``OrchestrationConfig`` 的默认值而不是硬编码 5.0，配置改了这里跟着改。
HEARTBEAT_SECONDS = OrchestrationConfig().heartbeat_seconds

#: 子进程必须在这个时间内退出，否则用例挂住而不是失败。
CHILD_TIMEOUT_SECONDS = 60.0


# ────────────────────────────────────────────────────────────── 测试工具


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """每个进程各自开一条连接。

    ``isolation_level=None`` 让连接停在自动提交，事务边界完全由 ``Control``
    自己用 ``BEGIN IMMEDIATE`` 划定（D7）；``busy_timeout`` 必须设，否则两个
    进程撞上时直接 ``database is locked`` 而不是等锁。
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    configure_connection(conn, busy_timeout_ms=5000)
    return conn


def _card(task_id: str, out_dir: Path, **overrides: object) -> TaskCard:
    """造一张能过 ``validate_card`` 的卡。

    ``output_path`` 必须绝对且每任务一个文件：``idx_tasks_output_active`` 是
    部分唯一索引，同一路径同时只允许一个非终态任务。
    """
    kwargs: dict[str, object] = {
        "task_id": task_id,
        "goal": f"control channel demo for {task_id}",
        "dod": ("worker polls the command within one heartbeat",),
        "output_path": str(out_dir / f"{task_id}.md"),
    }
    kwargs.update(overrides)
    return TaskCard(**kwargs)  # type: ignore[arg-type]


def _set_parent(conn: sqlite3.Connection, task_id: str, parent_task_id: str) -> None:
    """只补 ``parent_task_id`` 这一列。

    ``Store.enqueue`` 把 ``parent_task_id`` 写死成 NULL（阶段 2 还没有派发
    概念），而 ``list_children`` 的所有权过滤完全依赖这一列，所以层级关系
    只能在造数时补。这里刻意只改这一列，**不碰 ``state``**——状态变更必须
    走 ``transition()``（决议 §六.2）。
    """
    cursor = conn.execute(
        "UPDATE tasks SET parent_task_id = ? WHERE task_id = ?",
        (parent_task_id, task_id),
    )
    assert cursor.rowcount == 1, f"补 parent_task_id 失败：{task_id} 不存在"


def _write_report(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    assert report_path.exists(), f"子进程没有留下报告文件：{report_path}"
    return json.loads(report_path.read_text(encoding="utf-8"))


def _child_guard(report_path: str, body: Callable[[], Any]) -> None:
    """子进程统一收口：结果落盘，异常也落盘后**重新抛出**。

    ``except: pass`` 会让"子进程根本没跑起来"看起来像"父进程没收到指令"，
    所以异常一律写进报告文件再 ``raise``——``Process.exitcode`` 因此非 0，
    父进程的断言能同时看到退出码和 traceback。
    """
    try:
        result = body()
    except BaseException:
        _write_report(report_path, {"ok": False, "traceback": traceback.format_exc()})
        raise
    _write_report(report_path, {"ok": True, "result": result})


def _run_child(
    ctx: Any,
    target: Callable[..., None],
    args: tuple[Any, ...],
    report_path: Path,
) -> Any:
    """起子进程、等它退出、把报告里的 ``result`` 交回来。"""
    proc = ctx.Process(target=target, args=args, name=target.__name__)
    proc.start()
    proc.join(timeout=CHILD_TIMEOUT_SECONDS)
    assert not proc.is_alive(), f"{target.__name__} 超过 {CHILD_TIMEOUT_SECONDS}s 未退出"
    report = _read_report(report_path)
    assert proc.exitcode == 0, (
        f"{target.__name__} 退出码 {proc.exitcode}；"
        f"子进程报告：{report.get('traceback')}"
    )
    assert report.get("ok") is True, f"{target.__name__} 失败：{report.get('traceback')}"
    return report["result"]


# ──────────────────────────────────────────────────────────── 子进程入口
# 必须是模块级函数：``fork`` 下闭包也能用，但模块级同时兼容 ``spawn``，
# 且失败时的 traceback 里函数名可读。


def _child_request_stop(db_path: str, task_id: str, report_path: str) -> None:
    """子进程：只做一件事——从**另一条连接**投递 stop。"""

    def body() -> dict[str, Any]:
        conn = _connect(db_path)
        try:
            outcome = Control(conn).request_stop(task_id)
        finally:
            conn.close()
        return {"outcome": outcome}

    _child_guard(report_path, body)


def _child_request_steer(db_path: str, task_id: str, text: str, report_path: str) -> None:
    """子进程：从另一条连接投递 steer，回传 ``cmd_id``。"""

    def body() -> dict[str, Any]:
        conn = _connect(db_path)
        try:
            cmd_id = Control(conn).request_steer(task_id, text)
        finally:
            conn.close()
        return {"cmd_id": cmd_id}

    _child_guard(report_path, body)


def _child_list_children(
    db_path: str, parent_ids: tuple[str, ...], report_path: str
) -> None:
    """子进程：从另一条连接按所有权范围列子任务。"""

    def body() -> dict[str, list[str]]:
        conn = _connect(db_path)
        try:
            control = Control(conn)
            return {
                parent: [view.task_id for view in control.list_children(parent_task_id=parent)]
                for parent in parent_ids
            }
        finally:
            conn.close()

    _child_guard(report_path, body)


# ────────────────────────────────────────────────────────────── 验收 ①


def test_cross_process_stop_within_one_heartbeat(tmp_path: Path) -> None:
    """① 进程 A ``request_stop``，进程 B 在**一个 heartbeat 周期**内 poll 到。

    "一个 heartbeat 周期内"在存储侧的准确含义是：**一次 poll 就能取到**，
    不需要重试、不需要 sleep。所以这里只调一次 ``poll``，并给这次调用一个
    ``HEARTBEAT_SECONDS`` 的墙钟上界——若实现把指令写到别的 epoch、或只在
    某个后台线程里补写，单次 poll 拿不到，用例会红。

    任务必须是 ``CLAIMED``/``RUNNING``：``QUEUED`` 走 D3 的直接取消分支
    （不写 ``task_commands``），拿它测跨进程等于什么都没测。
    """
    db_path = tmp_path / "control.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # 父进程扮演 worker：领任务、start 进 RUNNING，记下自己的 epoch。
    store = Store(str(db_path), worker_id="worker-b")
    try:
        store.enqueue(_card("task-stop", out_dir))
        claimed = store.claim("solve", max_wait_seconds=0.0)
        assert claimed is not None, "任务没被领到，用例前提不成立"
        store.start(claimed.task_id, claimed.lease_epoch)
        epoch = claimed.lease_epoch
    finally:
        store.close()  # fork 前必须关：连接不跨进程

    assert epoch >= 1, f"claim 之后 lease_epoch 应 >= 1，实际 {epoch}"

    # 另一个进程投递 stop，然后退出。
    report_path = tmp_path / "child-stop.json"
    ctx = mp.get_context("fork")
    outcome = _run_child(
        ctx,
        _child_request_stop,
        (str(db_path), "task-stop", str(report_path)),
        report_path,
    )
    assert outcome["outcome"] == "queued", (
        f"RUNNING 任务的 request_stop 应返回 'queued'（D3），实际 {outcome['outcome']!r}"
    )

    # worker 侧：一次 poll，不重试。
    conn = _connect(db_path)
    try:
        control = Control(conn)
        started = time.monotonic()
        commands = control.poll("task-stop", epoch)
        elapsed = time.monotonic() - started
    finally:
        conn.close()

    stops = [command for command in commands if command.kind == "stop"]
    assert len(stops) == 1, (
        f"poll 应取到恰好 1 条 stop，实际 {len(stops)} 条；全部指令："
        f"{[(c.kind, c.lease_epoch) for c in commands]}"
    )
    stop = stops[0]
    assert stop.task_id == "task-stop"
    assert stop.lease_epoch == epoch, (
        f"指令必须绑定投递时的 epoch={epoch}，实际 {stop.lease_epoch}"
    )
    assert isinstance(stop.cmd_id, int) and stop.cmd_id > 0
    assert elapsed < HEARTBEAT_SECONDS, (
        f"单次 poll 花了 {elapsed:.3f}s，超过一个 heartbeat 周期 "
        f"{HEARTBEAT_SECONDS}s——指令没有在投递后立即可见"
    )

    # D3：排队分支必须同时置 cancel_requested_at，否则承载层不知道要收敛。
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT state, cancel_requested_at FROM tasks WHERE task_id = ?",
            ("task-stop",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["state"] == "RUNNING", (
        f"request_stop 只表达意图，不应替 worker 改状态，实际 {row['state']}"
    )
    assert row["cancel_requested_at"] is not None, "D3：排队分支必须置 cancel_requested_at"


# ────────────────────────────────────────────────────────────── 跨进程边界 ②


def test_cross_process_steer_text_survives_roundtrip(tmp_path: Path) -> None:
    """② steer 文本跨进程往返必须**逐字相等**。

    文本里同时放中文、``\\n``、单双引号、中文引号、反斜杠和制表符：任何一个
    环节（``json.dumps`` 漏 ``ensure_ascii``、编码写成 latin-1、按行切分、
    ``strip()`` 后再存）都会在这里露馅。

    刻意**不含首尾空白**：D4 只说"去空白后为空要抛 ValueError"，没有规定
    存储时是否 ``strip``，用首尾空白去测会把一个未定义的歧义变成假失败。
    """
    steer_text = (
        "第一行：把输出改成中文。\n"
        '第二行带 "双引号" 与 \'单引号\'，还有 “中文引号”。\n'
        "第三行含反斜杠 C:\\tmp\\x 和制表符\t结尾。"
    )

    db_path = tmp_path / "steer.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    store = Store(str(db_path), worker_id="worker-b")
    try:
        store.enqueue(_card("task-steer", out_dir))
        claimed = store.claim("solve", max_wait_seconds=0.0)
        assert claimed is not None
        store.start(claimed.task_id, claimed.lease_epoch)
        epoch = claimed.lease_epoch
    finally:
        store.close()

    report_path = tmp_path / "child-steer.json"
    ctx = mp.get_context("fork")
    result = _run_child(
        ctx,
        _child_request_steer,
        (str(db_path), "task-steer", steer_text, str(report_path)),
        report_path,
    )
    posted_cmd_id = result["cmd_id"]
    assert isinstance(posted_cmd_id, int) and posted_cmd_id > 0

    conn = _connect(db_path)
    try:
        control = Control(conn)
        commands = control.poll("task-steer", epoch)
        steers = [command for command in commands if command.kind == "steer"]
        assert len(steers) == 1, (
            f"poll 应取到恰好 1 条 steer，实际 {len(steers)} 条；全部："
            f"{[(c.kind, c.payload) for c in commands]}"
        )
        steer = steers[0]
        assert steer.payload == steer_text, (
            "steer 文本往返后不再逐字相等：\n"
            f"  期望 {steer_text!r}\n"
            f"  实际 {steer.payload!r}"
        )
        assert steer.cmd_id == posted_cmd_id, (
            f"poll 到的 cmd_id={steer.cmd_id} 与 request_steer 返回的 "
            f"{posted_cmd_id} 不一致"
        )

        # ack 之后不能再返回（D6）：跨进程投递 + 本进程确认的完整闭环。
        assert control.ack([steer.cmd_id]) == 1
        assert control.poll("task-steer", epoch) == [], "ack 之后 poll 必须为空"
        assert control.ack([steer.cmd_id]) == 0, "D6：重复 ack 不报错且返回 0"
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────── 跨进程边界 ③


def test_cross_process_list_does_not_leak_across_parents(tmp_path: Path) -> None:
    """③ ``list_children`` 的所有权过滤跨进程同样成立（D5，安全项）。

    造两个互不相干的 parent，各挂两个子任务，然后**在另一个进程里**分别按
    parent 列：A 的调用不许看到 B 的任何子任务。同时验证 ``TaskView.goal``
    能填出来——``tasks`` 表没有 goal 列，它只能从 ``card_json`` 反序列化，
    漏了这一步会返回空串而不是报错，属于静默错。
    """
    db_path = tmp_path / "list.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    store = Store(str(db_path), worker_id="seed")
    try:
        for task_id in ("parent-a", "parent-b", "a-child-1", "a-child-2", "b-child-1", "b-child-2"):
            store.enqueue(_card(task_id, out_dir))
    finally:
        store.close()

    conn = _connect(db_path)
    try:
        for child in ("a-child-1", "a-child-2"):
            _set_parent(conn, child, "parent-a")
        for child in ("b-child-1", "b-child-2"):
            _set_parent(conn, child, "parent-b")
    finally:
        conn.close()

    report_path = tmp_path / "child-list.json"
    ctx = mp.get_context("fork")
    result = _run_child(
        ctx,
        _child_list_children,
        (str(db_path), ("parent-a", "parent-b"), str(report_path)),
        report_path,
    )

    assert sorted(result["parent-a"]) == ["a-child-1", "a-child-2"], (
        f"parent-a 应只看到自己的两个子任务，实际 {result['parent-a']}"
    )
    assert sorted(result["parent-b"]) == ["b-child-1", "b-child-2"], (
        f"parent-b 应只看到自己的两个子任务，实际 {result['parent-b']}"
    )
    assert not set(result["parent-a"]) & set(result["parent-b"]), (
        f"两个 parent 的子任务集合有交集：{result}"
    )
    assert "parent-a" not in result["parent-a"], "list_children 不应把 parent 自己算进子任务"

    # 父进程再确认一遍视图字段（跨进程结果只回了 task_id）。
    conn = _connect(db_path)
    try:
        views = Control(conn).list_children(parent_task_id="parent-a")
    finally:
        conn.close()
    assert len(views) == 2
    for view in views:
        assert view.parent_task_id == "parent-a"
        assert view.goal == f"control channel demo for {view.task_id}", (
            f"TaskView.goal 必须从 card_json 还原，实际 {view.goal!r}"
        )
        assert view.state == "QUEUED"
        assert view.pool == "solve"
        assert view.batch_id == view.task_id
        assert view.lease_epoch == 0
        assert view.claimed_by is None
        assert view.cancel_requested is False
        assert view.started_at is None
        assert view.updated_at > 0


# ──────────────────────────────────────── 跨进程边界 ④（D2 严格小于的回归闸）


def _child_poll(db_path: str, task_id: str, epoch: int, report_path: str) -> None:
    """子进程：只 poll 一次，回传指令摘要（不做 ack）。"""

    def body() -> list[dict[str, Any]]:
        conn = _connect(db_path)
        try:
            commands = Control(conn).poll(task_id, epoch)
        finally:
            conn.close()
        return [
            {"cmd_id": command.cmd_id, "kind": command.kind, "lease_epoch": command.lease_epoch}
            for command in commands
        ]

    _child_guard(report_path, body)


def test_cross_process_zombie_worker_does_not_swallow_live_commands(tmp_path: Path) -> None:
    """僵尸 worker 的 poll 不许吞掉**现役** worker 的指令。

    D2 原意是"顺手清掉上一次 attempt 的残留"，但"残留"是有方向的：僵尸
    （旧 epoch）只能确认**比自己更旧**的时代。若 stale-ack 写成 ``<>``，
    一个已死/暂停的 epoch1 worker 醒来 poll 一次，就会把 epoch2 现役 worker
    尚未 ack 的指令当成残留 ack 掉——指令凭空消失，worker 永远等不到 stop。

    本用例两个方向都钉住：
    * 僵尸 poll(epoch=1) 只拿回自己时代的指令，**不许**碰 epoch2 的（``acked_at`` 仍为 NULL）；
    * 现役 poll(epoch=2) 照常把 epoch1 的残留 ack 掉且不返回，只返回 epoch2 的。

    epoch 的推进走 ``fail → QUEUED → claim`` 这条公开路径，不直接 ``UPDATE
    tasks``：手改 epoch 会绕过 fencing 语义，测出来的东西不可信。
    """
    db_path = tmp_path / "zombie.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    store = Store(str(db_path), worker_id="worker-live")
    try:
        store.enqueue(_card("task-zombie", out_dir, max_retries=1))
        first = store.claim("solve", max_wait_seconds=0.0)
        assert first is not None, "首次领取失败，用例前提不成立"
        store.start(first.task_id, first.lease_epoch)
        epoch_zombie = first.lease_epoch

        # epoch1 时代留下一条指令：它是"残留"，由现役 worker 负责清掉。
        conn = _connect(db_path)
        try:
            cmd_old = Control(conn).request_steer("task-zombie", "给 epoch1 的残留")
        finally:
            conn.close()

        # 这次 attempt 死掉 → 回 QUEUED（attempts=1 <= max_retries=1）→ 被重新领取。
        store.fail(first.task_id, first.lease_epoch, reason="worker died")
        second = store.claim("solve", max_wait_seconds=0.0)
        assert second is not None, "重试预算内应能重新领取"
        store.start(second.task_id, second.lease_epoch)
        epoch_live = second.lease_epoch
    finally:
        store.close()  # fork 前必须关：连接不跨进程

    assert epoch_zombie == 1 and epoch_live == 2, (
        f"epoch 推进不符合预期：zombie={epoch_zombie} live={epoch_live}"
    )

    conn = _connect(db_path)
    try:
        cmd_live = Control(conn).request_steer("task-zombie", "给 epoch2 的现役")
    finally:
        conn.close()

    ctx = mp.get_context("fork")

    # 1) 僵尸醒来 poll 一次：只许拿到自己时代的 cmd_old。
    zombie_report = tmp_path / "zombie-poll.json"
    zombie_cmds = _run_child(
        ctx,
        _child_poll,
        (str(db_path), "task-zombie", epoch_zombie, str(zombie_report)),
        zombie_report,
    )
    assert [item["cmd_id"] for item in zombie_cmds] == [cmd_old], (
        f"僵尸 poll(epoch={epoch_zombie}) 应只拿到自己时代的 {cmd_old}，"
        f"实际 {[item['cmd_id'] for item in zombie_cmds]}"
    )

    # 关键断言：现役指令必须**仍然未被 ack**。"不返回"抓不到这个洞——
    # 旧实现（`lease_epoch <> :epoch`）正是把它 ack 掉后才不返回的。
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT acked_at FROM task_commands WHERE cmd_id = ?", (cmd_live,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["acked_at"] is None, (
        f"僵尸 worker 的 poll 把现役指令 cmd_id={cmd_live} ack 掉了（D2 必须是严格小于）"
    )

    # 2) 现役 worker poll：epoch1 的残留被 ack 且不返回，只返回 epoch2 的。
    live_report = tmp_path / "live-poll.json"
    live_cmds = _run_child(
        ctx,
        _child_poll,
        (str(db_path), "task-zombie", epoch_live, str(live_report)),
        live_report,
    )
    assert [item["cmd_id"] for item in live_cmds] == [cmd_live], (
        f"现役 poll(epoch={epoch_live}) 应只拿到 {cmd_live}，"
        f"实际 {[item['cmd_id'] for item in live_cmds]}"
    )

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT cmd_id, acked_at FROM task_commands WHERE task_id = ? ORDER BY cmd_id",
            ("task-zombie",),
        ).fetchall()
    finally:
        conn.close()
    acked = {row["cmd_id"]: row["acked_at"] for row in rows}
    assert acked[cmd_old] is not None, "D2：现役 poll 必须把旧 epoch 的残留 ack 掉"
    assert acked[cmd_live] is None, "现役指令在被 ack 之前必须保持未确认"
