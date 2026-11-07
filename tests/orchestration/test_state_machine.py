"""``agent.orchestration.state_machine`` 的单元测试。

用例编号对应方案 §6.2 的 14 条状态机用例（TC01–TC14），另加评审要求的守卫
用例、1 条"钉住整表"用例、1 条穷举用例。

三层防线，缺一不可：

1. ``test_allowed_table_matches_spec_literal`` —— 表 == 规格（硬编码字面量）。
   表被悄悄改掉时它变红。**这条最重要**：穷举只能证明"实现与表一致"，
   表本身错了它照样绿，那就是"自洽的错误"。
2. ``test_exhaustive_transition_table`` —— 实现 == 表。表里加边但实现没放行、
   或实现放行了表外边的漂移，都会变红。
3. TC01–TC14 —— 语义正确性，人能读懂的那一层。
"""

from __future__ import annotations

import pytest

from agent.orchestration.contracts import TERMINAL_STATES, TaskState
from agent.orchestration.state_machine import (
    _ALLOWED,
    IllegalTransitionError,
    assert_not_terminal,
    is_terminal,
    transition,
)


def _satisfied_kwargs(current: TaskState, target: TaskState) -> dict[str, object]:
    """给出让条件边放行的最小上下文。

    ``_ALLOWED`` 里有三条边带守卫：不满足守卫时它们仍然抛错，这是设计意图，
    所以穷举"表内边都成功"必须显式满足守卫。``max_retries`` 无默认值，
    因此任何一次调用都必须带上它。
    """
    kwargs: dict[str, object] = {"max_retries": 1}
    if current is TaskState.RUNNING and target is TaskState.QUEUED:
        kwargs["lease_expired"] = True
    if current is TaskState.FAILED and target is TaskState.QUEUED:
        kwargs["attempts"] = 0
    if current is TaskState.BLOCKED and target is TaskState.QUEUED:
        kwargs["handoff_count"] = 0
        kwargs["handoff_cap"] = 2
    return kwargs


# --------------------------------------------------------------------------- #
# 规格字面量：表与规格的一致性
# --------------------------------------------------------------------------- #


def test_allowed_table_matches_spec_literal() -> None:
    """钉住整表：``_ALLOWED`` 必须逐字等于方案 §4.2 的转移表。

    这里的 expected 是**手工抄写**的规格字面量，不是从 ``_ALLOWED`` 推导出来的。
    任何一方被改动，这条都会红。
    """
    expected: dict[TaskState, frozenset[TaskState]] = {
        TaskState.QUEUED: frozenset({TaskState.CLAIMED, TaskState.CANCELLED}),
        TaskState.CLAIMED: frozenset(
            {
                TaskState.RUNNING,
                TaskState.QUEUED,
                TaskState.FAILED,
                TaskState.BLOCKED,
                TaskState.CANCELLED,
            }
        ),
        TaskState.RUNNING: frozenset(
            {
                TaskState.BLOCKED,
                TaskState.SUCCEEDED,
                TaskState.FAILED,
                TaskState.INTERRUPTED,
                TaskState.CANCELLED,
                TaskState.QUEUED,
            }
        ),
        TaskState.BLOCKED: frozenset(
            {TaskState.QUEUED, TaskState.CANCELLED, TaskState.FAILED}
        ),
        TaskState.FAILED: frozenset({TaskState.QUEUED}),
        TaskState.SUCCEEDED: frozenset(),
        TaskState.INTERRUPTED: frozenset(),
        TaskState.CANCELLED: frozenset(),
    }

    missing = set(TaskState) - set(_ALLOWED)
    extra = set(_ALLOWED) - set(TaskState)
    assert not missing and not extra, (
        f"转移表与状态枚举不同步：缺 {sorted(s.name for s in missing)}，"
        f"多 {sorted(s.name for s in extra)}。请补 _ALLOWED 的对应条目；"
        "不要改这条断言来消红。"
    )
    for state in TaskState:
        assert _ALLOWED[state] == expected[state], f"{state} 的出边与规格不符"
    assert _ALLOWED == expected


# --------------------------------------------------------------------------- #
# TC01–TC14：方案 §6.2 的 14 条用例
# --------------------------------------------------------------------------- #


def test_tc01_queued_to_claimed() -> None:
    """TC01 QUEUED -> CLAIMED：允许。"""
    assert (
        transition(TaskState.QUEUED, TaskState.CLAIMED, max_retries=1)
        is TaskState.CLAIMED
    )


def test_tc02_queued_to_running_rejected() -> None:
    """TC02 QUEUED -> RUNNING：拒绝（跳步，必须先领取）。"""
    with pytest.raises(IllegalTransitionError) as excinfo:
        transition(TaskState.QUEUED, TaskState.RUNNING, max_retries=1)
    assert excinfo.value.current is TaskState.QUEUED
    assert excinfo.value.target is TaskState.RUNNING


def test_tc03_claimed_to_running() -> None:
    """TC03 CLAIMED -> RUNNING：允许。"""
    assert (
        transition(TaskState.CLAIMED, TaskState.RUNNING, max_retries=1)
        is TaskState.RUNNING
    )


def test_tc04_claimed_to_queued() -> None:
    """TC04 CLAIMED -> QUEUED：允许（放弃领取 / 租约过期回收）。"""
    assert (
        transition(TaskState.CLAIMED, TaskState.QUEUED, max_retries=1)
        is TaskState.QUEUED
    )


def test_tc05_running_to_blocked() -> None:
    """TC05 RUNNING -> BLOCKED：允许。"""
    assert (
        transition(TaskState.RUNNING, TaskState.BLOCKED, max_retries=1)
        is TaskState.BLOCKED
    )


def test_tc06_running_to_succeeded() -> None:
    """TC06 RUNNING -> SUCCEEDED：允许。"""
    assert (
        transition(TaskState.RUNNING, TaskState.SUCCEEDED, max_retries=1)
        is TaskState.SUCCEEDED
    )


def test_tc07_running_to_queued_allowed_when_lease_expired() -> None:
    """TC07 RUNNING -> QUEUED：租约过期（判死）时允许。"""
    assert (
        transition(
            TaskState.RUNNING, TaskState.QUEUED, max_retries=1, lease_expired=True
        )
        is TaskState.QUEUED
    )


def test_tc08_running_to_queued_rejected_when_lease_alive() -> None:
    """TC08 RUNNING -> QUEUED：租约未过期时拒绝（普通回收不得触发）。"""
    with pytest.raises(IllegalTransitionError):
        transition(
            TaskState.RUNNING, TaskState.QUEUED, max_retries=1, lease_expired=False
        )


def test_tc09_blocked_to_queued() -> None:
    """TC09 BLOCKED -> QUEUED：允许（回收重派）。"""
    assert (
        transition(TaskState.BLOCKED, TaskState.QUEUED, max_retries=1)
        is TaskState.QUEUED
    )


def test_tc10_succeeded_has_no_outgoing_edge() -> None:
    """TC10 SUCCEEDED -> 任何：拒绝（终态不可逆）。"""
    for target in TaskState:
        if target is TaskState.SUCCEEDED:
            continue
        with pytest.raises(IllegalTransitionError):
            transition(TaskState.SUCCEEDED, target, max_retries=1)


def test_tc11_cancelled_has_no_outgoing_edge() -> None:
    """TC11 CANCELLED -> 任何：拒绝（终态不可逆）。"""
    for target in TaskState:
        if target is TaskState.CANCELLED:
            continue
        with pytest.raises(IllegalTransitionError):
            transition(TaskState.CANCELLED, target, max_retries=1)


def test_tc12_failed_to_queued_guarded_by_attempts() -> None:
    """TC12 FAILED -> QUEUED：attempts <= max_retries 允许，否则拒绝。"""
    assert (
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=1, max_retries=1)
        is TaskState.QUEUED
    )
    with pytest.raises(IllegalTransitionError):
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=2, max_retries=1)


def test_tc13_failed_to_running_rejected() -> None:
    """TC13 FAILED -> RUNNING：拒绝（必须回队列重新派发）。"""
    with pytest.raises(IllegalTransitionError):
        transition(TaskState.FAILED, TaskState.RUNNING, max_retries=1)


def test_tc14_same_state_rejected() -> None:
    """TC14 任意 -> 同一状态：拒绝，幂等交给调用方。"""
    for state in TaskState:
        with pytest.raises(IllegalTransitionError) as excinfo:
            transition(state, state, max_retries=1)
        assert "同态" in excinfo.value.reason


# --------------------------------------------------------------------------- #
# 额外用例：评审要求，不是方案原文
# --------------------------------------------------------------------------- #


def test_running_to_queued_allowed_when_lease_expired() -> None:
    """评审：租约过期是 RUNNING -> QUEUED 的唯一放行条件。"""
    assert (
        transition(
            TaskState.RUNNING, TaskState.QUEUED, max_retries=1, lease_expired=True
        )
        is TaskState.QUEUED
    )


def test_failed_to_queued_rejected_when_attempts_exhausted() -> None:
    """评审：重试次数用尽后 FAILED -> QUEUED 必须拒绝。"""
    with pytest.raises(IllegalTransitionError) as excinfo:
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=2, max_retries=1)
    assert "attempts=2" in str(excinfo.value)


def test_blocked_to_cancelled_allowed() -> None:
    """评审 M6：依赖失败传播，下游必须能收敛，不能永远 QUEUED。"""
    assert (
        transition(TaskState.BLOCKED, TaskState.CANCELLED, max_retries=1)
        is TaskState.CANCELLED
    )


def test_max_retries_semantics() -> None:
    """``max_retries`` 是"允许的重试次数"：``max_retries=1`` → 最多 2 次执行。

    ``attempts`` 含首次（评审 M12），所以第 1 次失败后 ``attempts=1`` 仍可重试，
    第 2 次失败后 ``attempts=2`` 才拒绝。边界 ``attempts == max_retries`` 放行。
    """
    # max_retries=1：首次(attempts=1)失败后可重试一次
    assert (
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=1, max_retries=1)
        is TaskState.QUEUED
    )
    # 第 2 次(attempts=2)失败后不再重试
    with pytest.raises(IllegalTransitionError):
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=2, max_retries=1)

    # max_retries=0：零重试，首次失败即终结
    with pytest.raises(IllegalTransitionError):
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=1, max_retries=0)

    # 边界放行：attempts == max_retries
    assert (
        transition(TaskState.FAILED, TaskState.QUEUED, attempts=3, max_retries=3)
        is TaskState.QUEUED
    )


# --------------------------------------------------------------------------- #
# P0：BLOCKED -> QUEUED 的 handoff_cap 守卫（阶段 1.5 冻结决议 §一）
# --------------------------------------------------------------------------- #


def test_blocked_to_queued_rejected_when_handoff_cap_reached() -> None:
    """P0：``BLOCKED -> QUEUED`` 必须有转手上限，否则崩溃循环无解。

    ``handoff_count == handoff_cap`` 拒绝，``handoff_count == handoff_cap - 1``
    放行——边界必须严格是 ``<``，写成 ``<=`` 会多放一次。
    """
    assert (
        transition(
            TaskState.BLOCKED,
            TaskState.QUEUED,
            max_retries=1,
            handoff_count=1,
            handoff_cap=2,
        )
        is TaskState.QUEUED
    )

    with pytest.raises(IllegalTransitionError) as excinfo:
        transition(
            TaskState.BLOCKED,
            TaskState.QUEUED,
            max_retries=1,
            handoff_count=2,
            handoff_cap=2,
        )
    assert "handoff_count=2" in str(excinfo.value)
    assert "handoff_cap=2" in str(excinfo.value)


def test_blocked_to_queued_guard_is_default_off_the_crash_loop() -> None:
    """默认参数（``handoff_count=0, handoff_cap=2``）下首次回收必须放行。

    守卫不能误伤正常路径：刚进 BLOCKED 的任务 handoff_count 是 0。
    """
    assert (
        transition(TaskState.BLOCKED, TaskState.QUEUED, max_retries=1)
        is TaskState.QUEUED
    )


def test_transition_requires_max_retries() -> None:
    """§2.2：``max_retries`` 无默认值，调用方必须显式给出重试口径。

    默认值朝"放行"方向偏是最危险的默认，所以宁可变红也不给默认。
    """
    with pytest.raises(TypeError):
        transition(TaskState.QUEUED, TaskState.CLAIMED)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# 穷举：实现与转移表不得漂移
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("current", list(TaskState))
def test_exhaustive_transition_table(current: TaskState) -> None:
    """穷举全部 (from, to) 组合：表内成功，表外抛 IllegalTransitionError。"""
    allowed = _ALLOWED[current]
    for target in TaskState:
        kwargs = _satisfied_kwargs(current, target)
        if target in allowed:
            assert transition(current, target, **kwargs) is target
        else:
            with pytest.raises(IllegalTransitionError):
                transition(current, target, **kwargs)


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def test_is_terminal_matches_contracts() -> None:
    """``is_terminal`` 直接复用 contracts 的 TERMINAL_STATES，不另立真相源。"""
    for state in TaskState:
        assert is_terminal(state) is (state in TERMINAL_STATES)


def test_assert_not_terminal() -> None:
    """终态下断言失败，非终态下静默通过。"""
    for state in TaskState:
        if state in TERMINAL_STATES:
            with pytest.raises(IllegalTransitionError):
                assert_not_terminal(state)
        else:
            assert assert_not_terminal(state) is None


def test_non_task_state_arguments_raise_type_error() -> None:
    """传入裸字符串必须显式报错，而不是被静默接受（评审 M18 的类型混用风险）。"""
    with pytest.raises(TypeError):
        transition("QUEUED", TaskState.CLAIMED, max_retries=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        transition(TaskState.QUEUED, "CLAIMED", max_retries=1)  # type: ignore[arg-type]
