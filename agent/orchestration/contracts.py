"""编排子系统公共契约（Phase 1a）。

本模块只定义**数据结构与校验规则**，不包含任何调度、存储或执行逻辑，也
不依赖 ``tools.*``——分层方向是 ``agent ← tools``，反向 import 会让编排层
重新耦合到具体的 delegate 实现上。

字段口径来自：
- 方案 §4.1（TaskCard / WorkerCapability / TaskHandle）
- 评审 ``docs/design/orchestration-plan-review-2026-10-31.md``
  - M16：``output_schema`` 必须是 JSON 字符串（frozen dataclass 里 dict 不可 hash）
  - M17：用 ``enum.StrEnum``，``str(TaskState.QUEUED) == "QUEUED"`` 而不是 ``"TaskState.QUEUED"``
  - M5：``can_write_shared`` 与 ``can_write_own_output`` 拆开（supervisor 要写自己的 output_path）
  - H4：补 ``budget_tokens`` / ``budget_usd``
  - M10：补 ``idempotency_key``
  - M4：补 ``worktree``
- 实施计划 §1.2 ⑦：``handoff_policy`` 两档语义（tool / handoff）在 PR-1 预留

约定：所有集合类字段用 ``tuple``，保证 frozen dataclass 可 hash；时间戳用
Unix 秒（float），与现有 ``async_delegations`` 表一致。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Final, Literal

__all__ = [
    "PUBLIC_CONTRACT_VERSION",
    "TaskState",
    "TERMINAL_STATES",
    "RECLAIMABLE_STATES",
    "Isolation",
    "TaskRole",
    "TaskTier",
    "HandoffPolicy",
    "TaskCard",
    "WorkerCapability",
    "TaskHandle",
    "CardValidationError",
    "validate_card",
]

#: 公共契约版本。字段语义发生不兼容变化时递增；只增字段不递增。
PUBLIC_CONTRACT_VERSION: Final[int] = 1


class TaskState(StrEnum):
    """任务执行状态。

    刻意**不包含** ``CANCEL_REQUESTED``：评审 H5 的结论是"取消请求"应该记在
    ``cancel_requested_at`` 列上，由 worker 在迭代边界收敛到 ``CANCELLED``，
    而不是新增一个状态名。
    """

    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"


#: 本次执行已终结（``completed_at`` 必须已落库）。
#: 注意：终结 ≠ 状态图无出边——``FAILED``/``INTERRUPTED`` 仍可经
#: ``_ALLOWED`` 开新的 attempt；判断有无出边请查 ``state_machine._ALLOWED``，
#: 不要用本集合判空。
TERMINAL_STATES: Final[frozenset[TaskState]] = frozenset(
    {
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.INTERRUPTED,
        TaskState.CANCELLED,
    }
)

#: 可回收重派的状态。注意：
#: - ``QUEUED`` 无持有者，不算"可回收"（它本来就在队列里）；
#: - ``INTERRUPTED`` 是空出边终态，**不可回收**——重跑必须新建任务。
#:   它承载的是"用户主动中断"，自动恢复会违背用户意图。
#: - 崩溃/卡死（租约过期）走的是 ``RUNNING -> BLOCKED``，不是 ``INTERRUPTED``。
#: - ``FAILED -> QUEUED`` 是**调用方 retry**，不是 reclaim；``FAILED`` 无持有者，故不在此集合。
#: 注意：本集合可由 ``state_machine._ALLOWED`` 推导（"有 -> QUEUED 出边的状态"的子集），
#: 但分层约束不允许 contracts 反向 import state_machine，故此处以常量声明 + 单向断言兜底
#: （tests/orchestration/test_contracts.py::test_reclaimable_states_can_return_to_queue）。
RECLAIMABLE_STATES: Final[frozenset[TaskState]] = frozenset(
    {
        TaskState.CLAIMED,
        TaskState.RUNNING,
        TaskState.BLOCKED,
    }
)


class Isolation(StrEnum):
    """执行单元形态。

    ``INLINE`` = 父进程内直接执行（默认，CLI 单任务）；
    ``PROCESS`` = 独立子进程（阶段 5 的灰度项，属**故障隔离**而非安全沙箱）。
    """

    INLINE = "inline"
    PROCESS = "process"


class TaskRole(StrEnum):
    """任务角色。与 ``delegate_task(role=...)`` 的既有取值保持一致（小写）。"""

    LEAF = "leaf"
    ORCHESTRATOR = "orchestrator"
    SUPERVISOR = "supervisor"
    AUDIT = "audit"
    STAT = "stat"


class TaskTier(IntEnum):
    """任务层级。数值越小越优先（T1 最优先）。"""

    T1 = 1
    T2 = 2
    T3 = 3


#: 控制权语义：``tool`` = 父保持控制权（agents-as-tools）；
#: ``handoff`` = 移交控制权（父不再管）。见实施计划 §1.2 ⑦。
HandoffPolicy = Literal["tool", "handoff"]

_HANDOFF_POLICIES: Final[frozenset[str]] = frozenset({"tool", "handoff"})


@dataclass(frozen=True, slots=True)
class TaskCard:
    """任务卡：入队时刻的**不可变**快照。

    所有序列/集合字段用 ``tuple`` 而非 ``list``/``dict``，因为 frozen dataclass
    的 ``__hash__`` 要求全部字段可 hash（评审 M16）。
    """

    task_id: str
    goal: str
    dod: tuple[str, ...]
    output_path: str

    # ── 上下文与范围 ────────────────────────────────────────────────────
    context: str = ""
    scope: str = ""
    #: JSON 字符串（不是 dict）。阶段 3 的终局校验会 ``json.loads`` 后比对。
    output_schema: str | None = None
    allowed_toolsets: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    # ── 调度属性 ────────────────────────────────────────────────────────
    role: TaskRole = TaskRole.LEAF
    tier: TaskTier = TaskTier.T2
    pool: str = "solve"
    #: ``None`` = 自动推断（``allowed_toolsets is None`` → ``PROCESS`` 保守路径）。
    #: 不要回填 ``INLINE``：默认在主进程里跑，一次段错误就拖垮整队。
    isolation: Isolation | None = None
    is_key: bool = False
    priority: int = 0
    handoff_policy: HandoffPolicy = "tool"

    # ── 限额 ────────────────────────────────────────────────────────────
    budget_seconds: float | None = None
    budget_tokens: int | None = None
    budget_usd: float | None = None
    max_handoffs: int = 2
    max_retries: int = 1
    depth: int = 0

    # ── 幂等与隔离（评审 M10 / M4） ─────────────────────────────────────
    idempotency_key: str | None = None
    worktree: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerCapability:
    """worker 的能力位。

    ``can_write_shared`` 与 ``can_write_own_output`` 必须分开（评审 M5）：
    supervisor/audit 不允许写共享产出，但**必须**能写自己的 ``output_path``，
    否则它们永远交不出报告。
    """

    role: TaskRole = TaskRole.LEAF
    can_delegate: bool = False
    can_write_shared: bool = False
    can_write_own_output: bool = True
    can_steer: bool = False


@dataclass(frozen=True, slots=True)
class TaskHandle:
    """worker 持有的租约句柄。

    ``capability`` 是 HMAC 字符串（不是能力位）：它把 ``task_id`` /
    ``worker_id`` / ``lease_epoch`` 绑在一起，写回时由 store 校验。
    ``lease_epoch`` 即评审 B1 要求的 fencing token——**每次写回都必须带上它**。
    """

    task_id: str
    worker_id: str
    lease_epoch: int
    capability: str
    contract_version: int = PUBLIC_CONTRACT_VERSION
    issued_at: float = 0.0
    lease_expires_at: float | None = None


class CardValidationError(ValueError):
    """任务卡校验失败。"""


def _check_positive_budget(card: TaskCard, field_name: str) -> None:
    value = getattr(card, field_name)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardValidationError(f"{field_name} 必须是数字或 None，实际为 {value!r}")
    if value <= 0:
        raise CardValidationError(f"{field_name} 必须 > 0，实际为 {value!r}")


def _check_non_negative_int(card: TaskCard, field_name: str) -> None:
    value = getattr(card, field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CardValidationError(f"{field_name} 必须是整数，实际为 {value!r}")
    if value < 0:
        raise CardValidationError(f"{field_name} 必须 >= 0，实际为 {value!r}")


#: ``task_id`` 允许的字符集：进文件名、进 SQL 参数、进日志，必须是最窄的
#: 安全子集（阶段 1.5 冻结决议 §2.3，安全项，不得省略）。
_TASK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._-]{1,128}")


def validate_card(card: TaskCard) -> None:
    """校验任务卡；失败抛 :class:`CardValidationError`。

    规则（阶段 1.5 冻结决议 §2.3）：
    - ``task_id`` 只允许 ``[A-Za-z0-9._-]``，长度 1–128（安全项）；
    - ``goal`` 去空白后非空；
    - ``output_path`` 必须是绝对路径，且 ``normpath(p) == p``（拒绝 ``..`` 段）；
    - ``dod`` 必须是 ``tuple``；传 ``list`` 直接报错，**不得静默转换**；
    - ``role`` / ``isolation`` / ``tier`` 必须是合法枚举值（isolation 允许 None）；
    - ``priority`` 必须是 ``int`` 且非 bool；
    - ``budget_seconds`` / ``budget_tokens`` / ``budget_usd`` 若给出必须 > 0；
    - ``max_handoffs`` / ``max_retries`` / ``depth`` 必须 >= 0；
    - ``output_schema`` 若给出必须是可 ``json.loads`` 的字符串；
    - ``handoff_policy`` 必须是 ``tool`` 或 ``handoff``。
    """
    if not isinstance(card, TaskCard):
        raise CardValidationError(f"期望 TaskCard，实际为 {type(card).__name__}")

    if not isinstance(card.task_id, str) or not _TASK_ID_PATTERN.fullmatch(card.task_id):
        raise CardValidationError(
            "task_id 只允许 [A-Za-z0-9._-] 且长度 1–128，"
            f"实际为 {card.task_id!r}"
        )

    if not isinstance(card.goal, str) or not card.goal.strip():
        raise CardValidationError("goal 不能为空或纯空白")

    # 枚举字段必须真的是枚举实例：裸字符串/裸 int 靠 ``==`` 也能过，但那是
    # "看起来对"，落库与 hash 时才会炸。TaskTier 是 IntEnum，故 2 不等于 T2 的实例。
    if not isinstance(card.role, TaskRole):
        raise CardValidationError(f"role 必须是 TaskRole，实际为 {card.role!r}")
    if card.isolation is not None and not isinstance(card.isolation, Isolation):
        raise CardValidationError(
            f"isolation 必须是 Isolation 或 None，实际为 {card.isolation!r}"
        )
    if not isinstance(card.tier, TaskTier):
        raise CardValidationError(f"tier 必须是 TaskTier，实际为 {card.tier!r}")

    # bool 是 int 的子类，必须先拦 bool，否则 True 会被当成优先级 1。
    if isinstance(card.priority, bool) or not isinstance(card.priority, int):
        raise CardValidationError(
            f"priority 必须是 int（不接受 bool），实际为 {card.priority!r}"
        )

    if not isinstance(card.output_path, str) or not card.output_path:
        raise CardValidationError("output_path 不能为空")
    if not os.path.isabs(card.output_path):
        raise CardValidationError(f"output_path 必须是绝对路径，实际为 {card.output_path!r}")
    if os.path.normpath(card.output_path) != card.output_path:
        raise CardValidationError(
            "output_path 必须是规范路径（不含 '..' 段或重复分隔符），"
            f"实际为 {card.output_path!r}"
        )

    if isinstance(card.dod, str) or not isinstance(card.dod, tuple):
        raise CardValidationError(
            "dod 必须是 tuple[str, ...]，不接受 list/str，且不做静默转换，"
            f"实际为 {type(card.dod).__name__}"
        )
    if not card.dod:
        raise CardValidationError("dod（definition of done）不能为空")
    for index, item in enumerate(card.dod):
        if not isinstance(item, str) or not item.strip():
            raise CardValidationError(f"dod[{index}] 必须是非空字符串，实际为 {item!r}")

    _check_positive_budget(card, "budget_seconds")
    _check_positive_budget(card, "budget_tokens")
    _check_positive_budget(card, "budget_usd")

    _check_non_negative_int(card, "max_handoffs")
    _check_non_negative_int(card, "max_retries")
    _check_non_negative_int(card, "depth")

    if card.output_schema is not None:
        if not isinstance(card.output_schema, str):
            raise CardValidationError(
                "output_schema 必须是 JSON 字符串或 None（不接受 dict），"
                f"实际为 {type(card.output_schema).__name__}"
            )
        try:
            json.loads(card.output_schema)
        except (ValueError, TypeError) as exc:
            raise CardValidationError(f"output_schema 不是合法 JSON：{exc}") from exc

    if card.handoff_policy not in _HANDOFF_POLICIES:
        raise CardValidationError(
            f"handoff_policy 必须是 {sorted(_HANDOFF_POLICIES)} 之一，实际为 {card.handoff_policy!r}"
        )
