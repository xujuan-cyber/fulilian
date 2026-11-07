"""Phase 1a 契约测试：``agent/orchestration/contracts.py``。

覆盖点：
- 版本号与枚举取值（含 ``StrEnum`` 的 ``str()`` 语义，评审 M17）；
- 终态 / 可回收态的集合成员与互斥性；
- ``TaskCard`` 的 frozen / slots / hashable 性质（评审 M16）；
- ``WorkerCapability`` 的 ``can_write_own_output``（评审 M5）；
- ``TaskHandle`` 的版本与 fencing 字段（评审 B1）；
- ``validate_card`` 的每一条失败路径（含阶段 1.5 冻结决议 §2.3 的 7 条）。
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from agent.orchestration import contracts
from agent.orchestration.contracts import (
    PUBLIC_CONTRACT_VERSION,
    RECLAIMABLE_STATES,
    TERMINAL_STATES,
    CardValidationError,
    Isolation,
    TaskCard,
    TaskHandle,
    TaskRole,
    TaskState,
    TaskTier,
    WorkerCapability,
    validate_card,
)


def _card(**overrides: object) -> TaskCard:
    """构造一张合法任务卡，按需覆盖字段。"""
    base: dict[str, object] = {
        "task_id": "t-001",
        "goal": "解析 pcap 并提取 HTTP 会话",
        "dod": ("输出 http_sessions.json", "包含 host 与 uri 字段"),
        "output_path": "/tmp/orchestration/t-001/http_sessions.json",
    }
    base.update(overrides)
    return TaskCard(**base)  # type: ignore[arg-type]


# ── 版本与枚举 ──────────────────────────────────────────────────────────────


def test_public_contract_version_is_one() -> None:
    assert PUBLIC_CONTRACT_VERSION == 1


def test_task_state_members_are_exactly_the_eight_states() -> None:
    # 集合比对而非列表比对：顺序敏感会红在"合法地新增一个状态"上，
    # 那属于变更探测器；"多了/少了"才是真正要拦的。
    assert {state.name for state in TaskState} == {
        "QUEUED",
        "CLAIMED",
        "RUNNING",
        "BLOCKED",
        "SUCCEEDED",
        "FAILED",
        "INTERRUPTED",
        "CANCELLED",
    }


def test_task_state_str_returns_bare_value() -> None:
    # 评审 M17：str(x) 必须是 "QUEUED"，不能是 "TaskState.QUEUED"，
    # 否则落库时会写错值。
    assert str(TaskState.QUEUED) == "QUEUED"
    assert f"{TaskState.CANCELLED}" == "CANCELLED"
    assert "{}".format(TaskState.FAILED) == "FAILED"


def test_task_state_is_str_compatible() -> None:
    assert isinstance(TaskState.RUNNING, str)
    assert TaskState.RUNNING == "RUNNING"
    assert "RUNNING" in {TaskState.RUNNING}


def test_terminal_states_exact_membership() -> None:
    assert TERMINAL_STATES == frozenset(
        {
            TaskState.SUCCEEDED,
            TaskState.FAILED,
            TaskState.INTERRUPTED,
            TaskState.CANCELLED,
        }
    )
    assert isinstance(TERMINAL_STATES, frozenset)


def test_reclaimable_states_exact_membership() -> None:
    assert RECLAIMABLE_STATES == frozenset(
        {TaskState.CLAIMED, TaskState.RUNNING, TaskState.BLOCKED}
    )
    assert isinstance(RECLAIMABLE_STATES, frozenset)


def test_terminal_and_reclaimable_are_disjoint() -> None:
    assert TERMINAL_STATES.isdisjoint(RECLAIMABLE_STATES)


def test_isolation_values() -> None:
    assert [item.value for item in Isolation] == ["inline", "process"]
    assert str(Isolation.PROCESS) == "process"


def test_task_role_values() -> None:
    assert [item.value for item in TaskRole] == [
        "leaf",
        "orchestrator",
        "supervisor",
        "audit",
        "stat",
    ]


def test_task_tier_is_int_enum_with_expected_values() -> None:
    assert (TaskTier.T1, TaskTier.T2, TaskTier.T3) == (1, 2, 3)
    assert TaskTier.T1 < TaskTier.T2 < TaskTier.T3
    assert int(TaskTier.T2) == 2
    assert TaskTier.T1 == 1


# ── TaskCard 结构性质 ──────────────────────────────────────────────────────


def test_task_card_defaults() -> None:
    card = _card()
    assert card.role is TaskRole.LEAF
    assert card.tier is TaskTier.T2
    # §2.1：默认 None（自动推断），不是 INLINE。
    assert card.isolation is None
    assert card.pool == "solve"
    assert card.is_key is False
    assert card.priority == 0
    assert card.handoff_policy == "tool"
    assert card.context == ""
    assert card.scope == ""
    assert card.output_schema is None
    assert card.allowed_toolsets == ()
    assert card.resources == ()
    assert card.depends_on == ()
    assert card.budget_seconds is None
    assert card.budget_tokens is None
    assert card.budget_usd is None
    assert card.max_handoffs == 2
    # §2.2：口径统一为 1，不再是 0。
    assert card.max_retries == 1
    assert card.depth == 0
    assert card.idempotency_key is None
    assert card.worktree is None


def test_task_card_isolation_defaults_to_none() -> None:
    """§2.1：未声明 ``isolation`` 时必须为 ``None``（自动推断），不能默认 INLINE。

    默认 INLINE 会绕过 fail-safe：不写 isolation 的任务在主进程里跑，一次段
    错误就拖垮整队。``None`` 由阶段 2 的推断逻辑落到 ``PROCESS``（保守）。
    """
    assert _card().isolation is None
    # 显式声明仍然照用，不被默认值覆盖。
    assert _card(isolation=Isolation.PROCESS).isolation is Isolation.PROCESS
    assert _card(isolation=Isolation.INLINE).isolation is Isolation.INLINE
    # None 是合法值，校验必须放行。
    assert validate_card(_card()) is None


def test_task_card_max_retries_defaults_to_one() -> None:
    """§2.2：``max_retries`` 三处口径统一为 1（card / transition / config）。"""
    assert _card().max_retries == 1
    assert contracts.TaskCard.__dataclass_fields__["max_retries"].default == 1


def test_task_card_is_frozen() -> None:
    card = _card()
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.goal = "changed"  # type: ignore[misc]


def test_task_card_uses_slots() -> None:
    assert not hasattr(_card(), "__dict__")


def test_task_card_is_hashable_with_full_field_set() -> None:
    card = _card(
        context="上游已确认：pcap 有 3 个 TCP 流",
        scope="只读分析，不写共享目录",
        output_schema=json.dumps({"type": "object"}),
        allowed_toolsets=("terminal", "file"),
        resources=("worktree:repo-a",),
        depends_on=("t-000",),
        role=TaskRole.AUDIT,
        tier=TaskTier.T1,
        isolation=Isolation.PROCESS,
        is_key=True,
        priority=5,
        handoff_policy="handoff",
        budget_seconds=120.0,
        budget_tokens=20000,
        budget_usd=1.5,
        max_handoffs=1,
        max_retries=2,
        depth=1,
        idempotency_key="pcap-t001-v1",
        worktree="/tmp/wt/t-001",
    )
    assert hash(card) == hash(card)
    assert len({card, card}) == 1


def test_task_card_equality_is_value_based() -> None:
    assert _card() == _card()
    assert _card(priority=1) != _card(priority=0)


# ── WorkerCapability / TaskHandle ──────────────────────────────────────────


def test_worker_capability_defaults() -> None:
    cap = WorkerCapability()
    assert cap.role is TaskRole.LEAF
    assert cap.can_delegate is False
    assert cap.can_write_shared is False
    # 评审 M5：默认必须允许写自己的 output_path，否则 supervisor 交不出报告。
    assert cap.can_write_own_output is True


def test_worker_capability_supervisor_can_write_own_output_only() -> None:
    cap = WorkerCapability(role=TaskRole.SUPERVISOR, can_write_own_output=True)
    assert cap.can_write_shared is False
    assert cap.can_write_own_output is True


def test_task_handle_defaults_and_fencing_fields() -> None:
    handle = TaskHandle(
        task_id="t-001",
        worker_id="w-1",
        lease_epoch=3,
        capability="deadbeef",
    )
    assert handle.contract_version == PUBLIC_CONTRACT_VERSION
    assert handle.lease_epoch == 3
    assert handle.capability == "deadbeef"
    assert handle.issued_at == 0.0
    assert handle.lease_expires_at is None


def test_task_handle_is_frozen() -> None:
    handle = TaskHandle(task_id="t", worker_id="w", lease_epoch=1, capability="c")
    with pytest.raises(dataclasses.FrozenInstanceError):
        handle.lease_epoch = 2  # type: ignore[misc]


# ── validate_card：成功路径 ────────────────────────────────────────────────


def test_validate_card_accepts_minimal_card() -> None:
    assert validate_card(_card()) is None


def test_validate_card_accepts_fully_populated_card() -> None:
    card = _card(
        output_schema='{"type": "array"}',
        budget_seconds=0.5,
        budget_tokens=1,
        budget_usd=0.01,
        max_handoffs=2,
        max_retries=3,
        depth=1,
    )
    assert validate_card(card) is None


# ── validate_card：失败路径 ────────────────────────────────────────────────


def test_validate_card_rejects_non_card() -> None:
    with pytest.raises(CardValidationError):
        validate_card({"task_id": "t"})  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_task_id", ["", "   "])
def test_validate_card_rejects_empty_task_id(bad_task_id: str) -> None:
    with pytest.raises(CardValidationError, match="task_id"):
        validate_card(_card(task_id=bad_task_id))


@pytest.mark.parametrize(
    "bad_task_id",
    ["t 001", "t/001", "任务-001", "t:001", "t;001", "a" * 129],
)
def test_validate_card_rejects_non_identifier_task_id(bad_task_id: str) -> None:
    """§2.3 安全项：``task_id`` 只允许 ``[A-Za-z0-9._-]``，长度 1–128。

    它要进文件名、进 SQL 参数、进日志，放任空格 / 斜杠 / 冒号就是注入面。
    """
    with pytest.raises(CardValidationError, match="task_id"):
        validate_card(_card(task_id=bad_task_id))


@pytest.mark.parametrize("good_task_id", ["t-001", "A.b_c-9", "a" * 128, "0"])
def test_validate_card_accepts_identifier_charset(good_task_id: str) -> None:
    """反向断言：合法字符集与长度边界不得误伤。"""
    assert validate_card(_card(task_id=good_task_id)) is None


@pytest.mark.parametrize(
    "bad_path",
    ["relative/out.json", "./out.json", "out.json", ""],
)
def test_validate_card_rejects_relative_output_path(bad_path: str) -> None:
    with pytest.raises(CardValidationError, match="output_path"):
        validate_card(_card(output_path=bad_path))


@pytest.mark.parametrize(
    "bad_path",
    [
        "/tmp/orchestration/../etc/passwd",
        "/tmp//orchestration/t-001/out.json",
        "/tmp/orchestration/./t-001/out.json",
        "/tmp/orchestration/t-001/../t-002/out.json",
    ],
)
def test_validate_card_rejects_path_traversal(bad_path: str) -> None:
    """§2.3 安全项：``normpath(p) != p`` 一律拒绝，堵住 ``..`` 段逃逸。

    绝对路径不够——``/tmp/a/../../etc/passwd`` 也是绝对路径。
    """
    with pytest.raises(CardValidationError, match="output_path"):
        validate_card(_card(output_path=bad_path))


def test_validate_card_rejects_blank_goal() -> None:
    """§2.3：``goal`` 去空白后必须非空，纯空白等同于没写目标。"""
    with pytest.raises(CardValidationError, match="goal"):
        validate_card(_card(goal="   "))


def test_validate_card_rejects_empty_goal() -> None:
    with pytest.raises(CardValidationError, match="goal"):
        validate_card(_card(goal=""))


def test_validate_card_rejects_empty_dod() -> None:
    with pytest.raises(CardValidationError, match="dod"):
        validate_card(_card(dod=()))


def test_validate_card_rejects_blank_dod_entry() -> None:
    with pytest.raises(CardValidationError, match=r"dod\[1\]"):
        validate_card(_card(dod=("ok", "  ")))


def test_validate_card_rejects_string_dod() -> None:
    with pytest.raises(CardValidationError, match="dod"):
        validate_card(_card(dod="输出一份报告"))


def test_validate_card_rejects_list_dod() -> None:
    """§2.3：``dod`` 传 list 直接报错，**不得静默转换**成 tuple。

    静默转换会让"调用方传错了容器类型"永远不被发现，且掩盖 hashability 问题。
    """
    with pytest.raises(CardValidationError, match="dod"):
        validate_card(_card(dod=["输出 http_sessions.json"]))


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("role", "leaf"),
        ("role", "root"),
        ("isolation", "inline"),
        ("tier", 2),
        ("tier", "T2"),
    ],
)
def test_validate_card_rejects_non_enum_scheduling_fields(
    field_name: str, bad_value: object
) -> None:
    """§2.3：``role`` / ``isolation`` / ``tier`` 必须是枚举实例。

    裸字符串靠 ``==`` 也能过，但那只是"看起来对"——落库与 hash 时才会炸。
    """
    with pytest.raises(CardValidationError, match=field_name):
        validate_card(_card(**{field_name: bad_value}))


def test_validate_card_rejects_bool_priority() -> None:
    """§2.3：bool 是 int 的子类，必须单独拦，否则 ``True`` 会被当成优先级 1。"""
    with pytest.raises(CardValidationError, match="priority"):
        validate_card(_card(priority=True))


def test_validate_card_rejects_non_int_priority() -> None:
    with pytest.raises(CardValidationError, match="priority"):
        validate_card(_card(priority="1"))


@pytest.mark.parametrize("field_name", ["budget_seconds", "budget_tokens", "budget_usd"])
@pytest.mark.parametrize("bad_value", [0, -1, -0.5])
def test_validate_card_rejects_non_positive_budget(field_name: str, bad_value: float) -> None:
    with pytest.raises(CardValidationError, match=field_name):
        validate_card(_card(**{field_name: bad_value}))


@pytest.mark.parametrize("field_name", ["max_handoffs", "max_retries", "depth"])
def test_validate_card_rejects_negative_counters(field_name: str) -> None:
    with pytest.raises(CardValidationError, match=field_name):
        validate_card(_card(**{field_name: -1}))


def test_validate_card_rejects_non_json_output_schema() -> None:
    with pytest.raises(CardValidationError, match="output_schema"):
        validate_card(_card(output_schema="{not json"))


def test_validate_card_rejects_dict_output_schema() -> None:
    # 评审 M16：dict 在 frozen dataclass 里不可 hash，契约只接受 JSON 字符串。
    with pytest.raises(CardValidationError, match="output_schema"):
        validate_card(_card(output_schema={"type": "object"}))


def test_validate_card_rejects_unknown_handoff_policy() -> None:
    with pytest.raises(CardValidationError, match="handoff_policy"):
        validate_card(_card(handoff_policy="delegate"))


def test_card_validation_error_is_value_error() -> None:
    assert issubclass(CardValidationError, ValueError)


# ── 分层与导出 ──────────────────────────────────────────────────────────────


def test_contracts_module_does_not_import_tools() -> None:
    source = (contracts.__file__ or "")
    assert source
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "import tools" not in text
    assert "from tools" not in text


def test_reclaimable_states_can_return_to_queue() -> None:
    """可回收 ⇒ 能回到队列。反过来不成立，**不要**断言。

    单向（可回收 ⇒ 有 -> QUEUED 的边）是语义约束：回收动作的定义就是把任务
    放回队列，缺这条边就不是回收，``patrol()`` 会扫到却回收不了。

    反向（有 -> QUEUED 的边 ⇒ 可回收）是策略选择而非语义：``FAILED -> QUEUED``
    是调用方 retry、``FAILED`` 无持有者，将来 ``INTERRUPTED`` 也可能如此。
    把它写成双向等式就是变更探测器——它会在有人做正确改动时变红，并教会团队
    "红了就改测试"。
    """
    # 局部 import：避免本测试模块在 import 期就依赖 state_machine，
    # 也让"contracts 不反向 import state_machine"的分层约束在代码里可见。
    from agent.orchestration.state_machine import _ALLOWED

    for state in RECLAIMABLE_STATES:
        assert TaskState.QUEUED in _ALLOWED[state], (
            f"{state} 被列为可回收，但转移表里它没有 -> QUEUED 的边；"
            "patrol() 会扫到它却回收不了"
        )


def test_contracts_all_is_complete() -> None:
    exported = set(contracts.__all__)
    for name in (
        "PUBLIC_CONTRACT_VERSION",
        "TaskState",
        "TERMINAL_STATES",
        "RECLAIMABLE_STATES",
        "Isolation",
        "TaskRole",
        "TaskTier",
        "TaskCard",
        "WorkerCapability",
        "TaskHandle",
        "CardValidationError",
        "validate_card",
    ):
        assert name in exported
        assert hasattr(contracts, name)
