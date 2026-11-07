"""不变量护栏（评审 §6.3：第一个 PR 的第三项交付物）。

定位：给阶段 2–7 预留的**护栏**，不是阶段 1 的功能测试。每条不变量在重构中
最容易被静默破坏——例如把 ``output_path`` 的活跃态唯一索引改回全局唯一，
或把 ``lease_epoch`` 的校验从写回路径上删掉——所以先把断言写下来，后续每个
阶段填一条。

写作原则：
- 现在能真断言的立刻写真断言（第 2、4、5 条）；
- 字段还没有写入方的，``skip`` 并在 reason 里写明由哪个阶段接管（第 1、3 条）；
- 已知缺口用 ``xfail(strict=True)`` 钉住：一旦有人补上约束，该用例会以
  XPASS 变红，提示"该把这个 xfail 删掉了"，而不是继续假装没问题（第 2 条）。

五条不变量与归属阶段：

====  ==================================================  ==================
#     不变量                                              何时能真断言
====  ==================================================  ==================
1     ``attempts >= handoff_count + 1``                  阶段 2（store.claim）
2     终态必须有 ``completed_at``                        现在（缺口见下）
3     ``card_json`` 派生列 == 列实际值                    阶段 2（insert 路径）
4     ``sum(pools) <= max_running``                       现在（M1 自相矛盾）
5     活跃态 ``output_path`` 唯一                         现在（H7）
====  ==================================================  ==================

只依赖标准库与 ``agent.orchestration``，不 import ``tools.*``。
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.orchestration.config import OrchestrationConfig
from agent.orchestration.contracts import (
    RECLAIMABLE_STATES,
    TERMINAL_STATES,
    TaskState,
)
from agent.orchestration.schema import apply_schema
from agent.orchestration.state_machine import _ALLOWED


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    apply_schema(connection)
    yield connection
    connection.close()


def _insert_task(
    connection: sqlite3.Connection,
    task_id: str,
    *,
    state: str = "QUEUED",
    output_path: str | None = None,
    completed_at: float | None = None,
    attempts: int = 1,
    handoff_count: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO tasks (
            task_id, batch_id, role, pool, state, card_json, output_path,
            completed_at, attempts, handoff_count, created_at, updated_at
        ) VALUES (?, 'b1', 'leaf', 'solve', ?, '{}', ?, ?, ?, ?, 1.0, 1.0)
        """,
        (
            task_id,
            state,
            # S3: output_path 是 NOT NULL；缺省时按 task_id 派生，保证互不冲突。
            output_path or f"out/{task_id}.md",
            completed_at,
            attempts,
            handoff_count,
        ),
    )


# ---------------------------------------------------------------- 1. 计数守恒


@pytest.mark.skip(reason="阶段 2：store.claim / redispatch 落地后启用（当前无写入方）")
def test_attempts_gte_handoff_count_plus_one(conn: sqlite3.Connection) -> None:
    """``attempts`` 是执行次数（含首次），``handoff_count`` 是持有人变更次数。

    不变式 ``attempts >= handoff_count + 1``：首次执行没有转手，所以差值至少
    为 1。违反即为引擎 bug（评审 M12），不是数据问题。

    现在无法断言：schema 里两列都存在但没有任何写入路径，只能构造人工数据，
    那样测的是测试自己而不是引擎。阶段 2 的 ``store.claim`` / ``redispatch``
    落地后，改为对真实领取序列断言。
    """
    _insert_task(conn, "t1", attempts=1, handoff_count=0)
    row = conn.execute("SELECT attempts, handoff_count FROM tasks WHERE task_id = 't1'").fetchone()
    assert row[0] >= row[1] + 1


# ------------------------------------------------------- 2. 终态必须有完成时刻


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已知缺口：schema 未强制终态行的 completed_at NOT NULL（评审 §6.3 #2）。"
        "补上 CHECK/触发器后本用例会 XPASS，届时删除 xfail 并同步修改 "
        "test_schema_currently_allows_terminal_without_completed_at"
    ),
)
def test_terminal_state_without_completed_at_is_rejected(conn: sqlite3.Connection) -> None:
    """目标状态：终态行写不进 ``completed_at IS NULL`` 的数据。

    当前 schema 只约束 ``state`` 的取值，不约束"终态 ⇒ completed_at 非空"。
    这条用 ``xfail(strict=True)`` 钉住缺口：现在失败是预期，将来通过则说明
    约束已补上，strict 会让它变红提醒删掉 xfail。
    """
    with pytest.raises(sqlite3.IntegrityError):
        _insert_task(conn, "t-null-completed", state="SUCCEEDED", completed_at=None)


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"])
def test_schema_currently_allows_terminal_without_completed_at(
    conn: sqlite3.Connection, terminal: str
) -> None:
    """把"当前没有强制"这件事写成会红的测试，而不是留一句注释。

    它现在通过（缺口存在），一旦有人在 schema 层补上约束，插入会抛
    ``IntegrityError``，本用例随之变红——这正是"该更新不变量测试了"的信号。
    补偿措施：终态写入必须经状态机（``state_machine.py``）+ store 写回路径，
    两处都要保证 ``completed_at`` 与终态同事务落库。
    """
    _insert_task(conn, f"t-{terminal}", state=terminal, completed_at=None, output_path=None)
    count = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE state = ? AND completed_at IS NULL", (terminal,)
    ).fetchone()[0]
    assert count == 1, "schema 已开始强制 completed_at，请更新不变量测试与 xfail"


# ------------------------------------------------- 3. card_json 与派生列一致


@pytest.mark.skip(reason="阶段 2：insert 路径的 card_hash 校验落地后启用（H8）")
def test_derived_columns_match_card_json(conn: sqlite3.Connection) -> None:
    """列是查询与排序的唯一真相，``card_json`` 只是入队时刻的不可变快照。

    契约：``derive(card) == (role, pool, tier, is_key, priority, isolation)``，
    且 ``card_hash == sha256(canonical_json(card))``（评审 H8）。

    现在无法断言：没有任何 insert 路径会写 ``card_json`` 与 ``card_hash``，
    测试只能自造数据。阶段 2 的 store.insert 落地后，改为"用引擎插入再读回列
    比对"，一条测试即可锁死漂移。
    """
    _insert_task(conn, "t1")
    row = conn.execute("SELECT card_hash FROM tasks WHERE task_id = 't1'").fetchone()
    assert row[0] is not None


# ------------------------------------------------------- 4. pools 与全局硬顶


def test_pools_sum_exceeds_max_running_by_design() -> None:
    """评审 M1：方案自身数字自相矛盾（15 + 1 + 1 = 17 > max_running 15）。

    处理方式不是拒绝启动，而是**以 max_running 为全局硬顶、pools 只作配额**，
    并在启动时告警。这条测试把"该矛盾已被识别"固化下来：如果有人把默认值
    悄悄改成一致（例如把 solve 调成 13），本用例会红，提醒同步更新评审结论
    与文档，而不是让矛盾无声消失。
    """
    cfg = OrchestrationConfig()
    pool_total = sum(cap for _, cap in cfg.pools)
    assert pool_total == 17
    assert cfg.max_running == 15
    assert pool_total > cfg.max_running

    notes = cfg.warnings()
    assert len(notes) == 1
    assert "17" in notes[0] and "15" in notes[0]

    # 告警而非拒绝启动：max_running 才是硬顶。
    cfg.validate()


def test_pools_within_max_running_is_silent() -> None:
    """反向断言：pools 之和不超过硬顶时不得产生噪音告警（SRE：告警必须可行动）。"""
    cfg = OrchestrationConfig(
        max_running=20,
        pools=(("solve", 15), ("supervision", 1), ("audit", 1)),
    )
    assert cfg.warnings() == ()


# --------------------------------------------------- 5. 活跃态 output_path 唯一


def test_output_path_uniqueness_index_is_partial_not_global(conn: sqlite3.Connection) -> None:
    """评审 H7：约束必须是"活跃态唯一"，不能退化成全局唯一。

    行为断言在 ``test_schema.py``（终态可复用同一 output_path）。这里只钉
    schema 的形状，因为"有人为了省事把它改成普通唯一索引"正是最可能的重构
    事故，而行为测试未必能覆盖到。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_tasks_output_active'"
    ).fetchone()
    assert row is not None, "部分唯一索引 idx_tasks_output_active 丢失"
    ddl = " ".join(row[0].split()).lower()

    assert ddl.startswith("create unique index"), ddl
    assert "on tasks(output_path)" in ddl
    assert " where state not in (" in ddl
    # 四个终态必须全部豁免，少一个就会挡住该终态的重派。
    for terminal in ("'succeeded'", "'failed'", "'cancelled'", "'interrupted'"):
        assert terminal in ddl, f"{terminal} 未出现在部分索引的 WHERE 子句中"

    # 普通索引仍在（查重用），两者不互斥。
    plain = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_tasks_output'"
    ).fetchone()
    assert plain is not None


# ---------------------------------------------------------------------------
# 6. 跨层：RECLAIMABLE_STATES 与 _ALLOWED 的一致性
#
# 为什么写在这里而不是 contracts / state_machine 任一模块：RECLAIMABLE_STATES
# 可由 _ALLOWED 派生，但 contracts 不能 import state_machine（依赖方向相反，
# 会成环）。于是这条约束既不能写成注释（不执行）、也不能写成派生值（不允许），
# 只能写成测试。所有跨层不变量统一放本文件。
# ---------------------------------------------------------------------------


def test_reclaimable_states_can_return_to_queue() -> None:
    """方向 A：可回收 ⇒ 有 -> QUEUED 出边。

    防守"新增了回收态却忘了给边"——patrol() 会扫到它却回收不了。
    """
    for state in RECLAIMABLE_STATES:
        assert TaskState.QUEUED in _ALLOWED[state], (
            f"{state} 被列为可回收，但转移表里没有 -> QUEUED 的边；"
            "patrol() 会扫到它却无处可放"
        )


def test_queue_returning_states_are_classified() -> None:
    """方向 B：非终态且有 -> QUEUED 出边 ⇒ 必须被显式分类。

    这是**更危险的那个方向**：有人给 _ALLOWED 加了一条 -> QUEUED 的边（例如让
    某个新状态可以重跑），但没想清楚它算 retry 还是 reclaim，于是
    RECLAIMABLE_STATES 静默过时，patrol() 少扫一个本该回收的状态——而所有测试
    都是绿的，因为没有任何断言要求"这张表的新边必须被分类"。

    终态豁免：终态任务没有活跃持有者，回到队列只能是调用方 retry（如 FAILED），
    不可能是 patrol 回收，所以不要求进 RECLAIMABLE_STATES。
    """
    unclassified = {
        state
        for state in TaskState
        if TaskState.QUEUED in _ALLOWED[state]
        and state not in RECLAIMABLE_STATES
        and state not in TERMINAL_STATES
    }
    assert not unclassified, (
        f"{sorted(s.name for s in unclassified)} 有 -> QUEUED 的出边，"
        "但既不在 RECLAIMABLE_STATES 也不是终态。请明确它属于哪一种："
        "patrol 回收（加入 RECLAIMABLE_STATES）还是调用方 retry（说明为何豁免）。"
    )


# ---------------------------------------------------------------------------
# 7. 跨层：handoff 上限三处口径必须一致
#
# 同一个"最多转手几次"在三处出现：TaskCard.max_handoffs（契约默认）、
# OrchestrationConfig.handoff_cap（引擎配置）、transition(handoff_cap=...)
# （状态机守卫默认）。三者一旦不一致，默认卡就会在某一层被意外拒绝——
# 曾经出现过 card=0 而 cap=2，导致默认卡第一次崩溃恢复就被
# BLOCKED->QUEUED 的守卫拒掉（0 < 0 为假），恢复路径被彻底堵死。
# ---------------------------------------------------------------------------


def test_handoff_cap_is_consistent_across_layers() -> None:
    from agent.orchestration.contracts import TaskCard

    card = TaskCard(task_id="t", goal="g", output_path="/tmp/o.md", dod=("x",))
    config_cap = OrchestrationConfig().handoff_cap
    assert card.max_handoffs == config_cap, (
        f"TaskCard.max_handoffs={card.max_handoffs} 与 "
        f"OrchestrationConfig.handoff_cap={config_cap} 不一致；"
        "默认卡会在其中一层被意外拒绝"
    )
    assert card.max_handoffs >= 1, (
        "max_handoffs 必须 >= 1，否则默认卡第一次崩溃恢复就会被 "
        "BLOCKED->QUEUED 守卫拒掉（handoff_count=0 时 0 < 0 为假）"
    )
