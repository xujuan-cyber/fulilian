"""重派策略：续跑点、路由指纹、换路线豁免。

边界（阶段 4 决议 §一，本模块最重要的约束）::

    只回答"该怎么重派"，不扫描、不告警、不判死。
    ``BLOCKED`` 的判定归 ``store.patrol()``，状态落库归 ``store.redispatch()``。

只依赖 ``store`` / ``contracts`` / ``state_machine``，**不** import ``worker.py``
或 ``launcher.py``（S7）：执行层不进监督层，否则阶段 5 的进程隔离会牵连监督
逻辑。

三条不许"简化"的决议：

* **S4 换路线豁免**：``route_fingerprint`` 变化 = 换了执行方案（换模型/换工具
  集）。同一个方案反复失败才该收手，换方案不该被前一个方案的失败次数拖累。
  ``route_changed=True`` 时 ``consumes_handoff=False``——任务照样回去重跑，但
  **不递增** ``handoff_count``。``store.redispatch()`` 总是 ``+1``，所以豁免
  路径由本模块自己写 UPDATE（决议 §三 S4 明确允许）。
  豁免是"不记账"，**不是"免死金牌"**：``handoff_cap`` 的守卫在豁免路径上照常
  生效。``handoff_count`` 已耗尽的任务即使换了路线也会抛
  ``IllegalTransitionError``——那不是 bug，正确处置是人工介入，别改成归零骗守卫。
* **S5 续跑点**：``cursor_json`` 原样保留。清空它会把"续跑"降级成"从头再来"，
  一个跑到 80% 的任务白白作废。``plan()`` 把它读进
  ``RedispatchPlan.resume_from_cursor``；``apply()`` 的 UPDATE 里根本没有
  ``cursor_json`` 这一列，所以不可能被写掉。
* **S6 转手上限**：``handoff_count >= handoff_cap`` 时 ``transition()`` 抛
  ``IllegalTransitionError``，本模块**不吞、不降级**。换路线只豁免"递增"，
  不豁免状态机本身。

豁免路径需要"同一事务内 SELECT + 带条件 UPDATE"，因此用到三个**公开**接口：
``Store.query()``（只读，仅 SELECT）/ ``Store.write_tx()``（``BEGIN IMMEDIATE``）
/ ``Store.record_event()``（与状态变更同事务写审计事件）。

阶段 4.5 之前这三个是私有成员（``_conn`` / ``_write_tx`` / ``_record_event``），
属于技术债；现已随 ``Store`` 公开接口的引入一并迁走。

``RedispatchPlan.new_route_fingerprint`` 是阶段 4 追加的字段（原冻结签名写漏）：
``apply()`` 必须在同一条 UPDATE 里写回它，否则下次 ``plan()`` 仍拿旧指纹比对，
"已换路线"会被判成"没换"，豁免就会无限重复。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from agent.orchestration.contracts import TaskState
from agent.orchestration.state_machine import transition
from agent.orchestration.store import NotClaimableError, Store, StoreError

__all__ = ["RedispatchPlan", "Redispatcher"]


_PLAN_SQL = (
    "SELECT state, cursor_json, route_fingerprint, handoff_count, card_json "
    "FROM tasks WHERE task_id = ?"
)

#: 豁免路径：与 ``Store.redispatch`` 的唯一差别是**没有** ``handoff_count + 1``。
#: ``AND state = ? AND lease_epoch = ?`` 是并发闸——期间若被 claim 走（epoch
#: 会 +1）或状态已变，``rowcount`` 就不是 1，绝不按"看起来成功"提交。
_EXEMPT_UPDATE = """
UPDATE tasks SET
    state = :queued,
    -- COALESCE 而不是直接赋值：指纹为 None 时保持原值，绝不写成 NULL。
    -- 注意：该 None 分支在当前调用链下**不可达**（豁免路径要求 route_changed=True，
    -- 而它要求新指纹非 None）。保留 COALESCE 是防御：将来若有人放宽 route_changed
    -- 的判定（例如允许"显式置空"），这里不会静默把已有指纹抹成 NULL。
    -- 写掉旧指纹等于把"上次用的方案"抹了，下次比对就没有基线了。
    route_fingerprint = COALESCE(:route_fingerprint, route_fingerprint),
    claimed_by = NULL,
    lease_expires = NULL,
    block_reason = NULL,
    updated_at = :now
WHERE task_id = :task_id
  AND state = :blocked
  AND lease_epoch = :lease_epoch
"""


def _card_limits(card_json: str) -> tuple[int, int]:
    """从 ``card_json`` 快照取 ``(max_retries, max_handoffs)``。

    只读这两个整数字段，不重建 ``TaskCard``：重派只关心状态机的两条守卫，
    重建整个 card 会把无关字段的形状问题也拖进来。
    """
    raw = json.loads(card_json)
    return int(raw["max_retries"]), int(raw["max_handoffs"])


@dataclass(frozen=True, slots=True)
class RedispatchPlan:
    """一次重派的决策结果。``plan()`` 产出、``apply()`` 消费，本身不落库。"""

    task_id: str
    resume_from_cursor: str | None
    route_changed: bool
    consumes_handoff: bool
    reason: str
    #: 换了路线时的**新**指纹；``None`` 表示"没换/不改该列"。
    #: 带默认值是为了不破坏已有的构造点。
    new_route_fingerprint: str | None = None


class Redispatcher:
    """把"要不要转手、从哪儿续跑"算清楚，然后交给 ``store`` 落库。"""

    def __init__(
        self, store: Store, *, now: Callable[[], float] = time.time
    ) -> None:
        self._store = store
        self._now = now

    def plan(
        self, task_id: str, *, new_route_fingerprint: str | None = None
    ) -> RedispatchPlan:
        """只读：算出该怎么重派，**不执行**（一行都不改）。

        非 ``BLOCKED`` 直接拒绝：重派的前提是已经判死落 ``BLOCKED``（决议 §一
        把判死留给 ``patrol()``），对着 ``RUNNING`` 算重派方案没有意义。

        ``new_route_fingerprint=None`` 表示"方案没变"，此时必然消耗一次
        handoff 预算。
        """
        row = self._store.query(_PLAN_SQL, (task_id,)).fetchone()
        if row is None:
            raise StoreError(f"任务不存在：{task_id}")
        current = TaskState(row["state"])
        if current is not TaskState.BLOCKED:
            raise NotClaimableError(
                f"redispatch 需要 BLOCKED，task_id={task_id} 实际 {current}"
            )

        current_route = row["route_fingerprint"]
        route_changed = (
            new_route_fingerprint is not None
            and new_route_fingerprint != current_route
        )
        consumes_handoff = not route_changed
        handoff_count = int(row["handoff_count"])
        _, handoff_cap = _card_limits(row["card_json"])

        if route_changed:
            reason = (
                f"路由指纹 {current_route!r} -> {new_route_fingerprint!r}："
                f"换方案豁免 handoff 预算（handoff_count={handoff_count} 保持不变，"
                f"cap={handoff_cap}）"
            )
        else:
            reason = (
                f"路由指纹未变（{current_route!r}）："
                f"消耗一次 handoff 预算（{handoff_count} -> {handoff_count + 1}，"
                f"cap={handoff_cap}）"
            )

        return RedispatchPlan(
            task_id=task_id,
            resume_from_cursor=row["cursor_json"],
            route_changed=route_changed,
            consumes_handoff=consumes_handoff,
            reason=reason,
            new_route_fingerprint=new_route_fingerprint,
        )

    def apply(self, plan: RedispatchPlan) -> None:
        """执行计划。异常一律外抛（S6：不吞、不降级）。

        ``consumes_handoff=True`` 直接交给 ``store.redispatch()``：状态机校验、
        ``handoff_count + 1``、``BLOCKED`` 条件 UPDATE 都在那一条语句里，另写
        一份副本只会多一处会漂移的实现。这条路径不写 ``route_fingerprint``——
        ``plan()`` 只在指纹**没变**时才给 ``consumes_handoff=True``，没有新值
        可写。
        """
        if plan.consumes_handoff:
            self._store.redispatch(plan.task_id)
            return
        self._apply_exempt(plan)

    def _apply_exempt(self, plan: RedispatchPlan) -> None:
        """``BLOCKED -> QUEUED``，但 ``handoff_count`` 不动（S4）。

        仍然走 ``transition()``：换路线豁免的是"递增"，不是状态机。所以
        ``handoff_count >= handoff_cap`` 时这里同样抛 ``IllegalTransitionError``
        ——预算已经用尽的任务不会因为再换一次方案就复活。

        同时写回 ``plan.new_route_fingerprint``：不写回的话下一轮 ``plan()`` 会
        拿旧指纹比对，把"已换路线"判成"没换"，豁免无限重复。
        """
        with self._store.write_tx() as conn:
            row = conn.execute(
                "SELECT state, lease_epoch, attempts, handoff_count, card_json, "
                "route_fingerprint FROM tasks WHERE task_id = ?",
                (plan.task_id,),
            ).fetchone()
            if row is None:
                raise StoreError(f"任务不存在：{plan.task_id}")
            current = TaskState(row["state"])
            if current is not TaskState.BLOCKED:
                raise NotClaimableError(
                    f"redispatch 需要 BLOCKED，task_id={plan.task_id} 实际 {current}"
                )
            max_retries, handoff_cap = _card_limits(row["card_json"])
            handoff_count = int(row["handoff_count"])
            transition(
                current,
                TaskState.QUEUED,
                max_retries=max_retries,
                attempts=int(row["attempts"]),
                handoff_count=handoff_count,
                handoff_cap=handoff_cap,
            )
            cursor = conn.execute(
                _EXEMPT_UPDATE,
                {
                    "queued": TaskState.QUEUED.value,
                    "blocked": TaskState.BLOCKED.value,
                    "route_fingerprint": plan.new_route_fingerprint,
                    "now": self._now(),
                    "task_id": plan.task_id,
                    "lease_epoch": int(row["lease_epoch"]),
                },
            )
            if cursor.rowcount != 1:
                raise NotClaimableError(
                    f"redispatch 被并发抢先：task_id={plan.task_id} "
                    f"已不在 BLOCKED 或 lease_epoch 已变"
                )
            self._store.record_event(
                conn,
                plan.task_id,
                "redispatch_exempt",
                {
                    "route_fingerprint": row["route_fingerprint"],
                    "handoff_count": handoff_count,
                    "reason": plan.reason,
                },
            )
