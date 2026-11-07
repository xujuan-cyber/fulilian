"""监督层（阶段 4）：**只告警，不裁决**。

冻结决议：``docs/design/orchestration-phase4-decisions.md``（S1-S7）。

本模块只回答"哪里看起来不对"，不回答"该怎么处置"：

* 判死仍归 ``store.patrol()``（租约过期 -> ``BLOCKED``）；
* 重派仍归 ``store.redispatch()`` / ``redispatch.Redispatcher``；
* 本模块只产出 :class:`Finding`、把 findings 记进 ``events``、算误报三指标、
  清过期 events。**不改任务状态、不判死、不重派。**

分工的理由是"误报会摧毁信任"（实施计划 §阶段 4）：只告警时，一次误判的代价
是噪声；一旦开始裁决，一次误判就改坏真实任务。所以两阶段上线，本阶段只做前者。
:meth:`Supervisor.scan` 因此是**纯只读**的（S1），连 ``store.patrol()`` 都不调。

两个公开入口，写在这里以免后来者又绕回私有成员：

1. :meth:`Supervisor.scan` 走 :meth:`Store.query`。该入口**只接受 SELECT**，
   写语句会直接抛 ``ValueError``——S1 的"纯只读"从"靠约定"变成"靠约束"。
2. ``record()`` / ``mark_actioned()`` / ``sweep_events()`` 走
   :meth:`Store.write_tx`：那是库自己定义的 ``BEGIN IMMEDIATE`` 语义，重写一份
   只会让两边的事务边界慢慢漂开。

（阶段 4.5 之前这两处直接访问 ``store._conn`` / ``store._write_tx()``，四个模块
共 9 处私有访问；现已全部迁到公开接口。）

S7：本模块只依赖 ``store``（与 ``contracts`` 的枚举），**不** import
``worker.py`` / ``launcher.py``——执行层一旦被拖进监督层，阶段 5 的进程隔离
就会牵连到监督逻辑。
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agent.orchestration.contracts import TaskState
from agent.orchestration.store import Store

__all__ = [
    "Finding",
    "Severity",
    "Supervisor",
    "SupervisorError",
]


# ------------------------------------------------------------------ 常量与契约

#: findings 在 ``events`` 里的 kind（S2/S3 的数据来源）。
EVENT_FINDING = "supervisor_finding"

#: 人工反馈落成独立事件，而不是回头改 finding 的 payload——审计行只追加不改写。
EVENT_ACTIONED = "supervisor_actioned"

#: 指标要用到的两类事件（S6 的"保留双倍时长"对它们同时生效）。
_METRIC_KINDS: tuple[str, ...] = (EVENT_FINDING, EVENT_ACTIONED)

#: S2：按小时分桶。``bucket = int(detected_at // 3600)``。
_BUCKET_SECONDS = 3600

#: ``orphan_worker`` 的心跳阈值：登记为 idle/busy/draining 的 worker 若
#: ``last_heartbeat`` 早于 ``now - 该值``，视为僵尸登记。默认 300s = 60 个
#: ``worker.Worker(heartbeat_interval=5.0)`` 周期。本阶段 ``workers`` 表还没有
#: 写入方，等 worker 真正登记后应改成可配置（冻结 API 没有这个旋钮，先做常量）。
_WORKER_HEARTBEAT_TTL = 300.0

class SupervisorError(Exception):
    """监督层错误基类（目前只用于参数校验，异常一律不吞）。"""


class Severity(enum.Enum):
    """告警等级。只影响排序与展示，**不影响任何状态**。"""

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Finding:
    """一条告警。**描述**异常，不携带任何处置动作。"""

    finding_id: str          # 稳定标识：sha1(f"{kind}:{task_id}:{bucket}")[:16]
    kind: str                # 'stale_lease' | 'retry_exhausted' | 'handoff_exhausted' | 'orphan_worker'
    task_id: str | None
    severity: Severity
    detail: str
    detected_at: float
    actioned: bool = False


#: 排序用：CRITICAL 先出，便于人先看要紧的。
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.WARN: 1,
    Severity.INFO: 2,
}


# ------------------------------------------------------------------- SQL 常量

#: S1：只读。候选集与 ``store.patrol`` 同源（CLAIMED/RUNNING + 租约已过期），
#: 但这里**只读不写**——判死是 patrol 的事。
_STALE_LEASE_SQL = """
SELECT task_id, state, lease_epoch, lease_expires, claimed_by
  FROM tasks
 WHERE state IN (?, ?)
   AND lease_expires IS NOT NULL
   AND lease_expires < ?
 ORDER BY lease_expires ASC, task_id ASC
 LIMIT ?
"""

#: 自动重试已用尽的 FAILED（``fail()`` 在 ``attempts > max_retries`` 时不再回队）。
_RETRY_SQL = """
SELECT task_id, state, attempts, card_json
  FROM tasks
 WHERE state = ?
 ORDER BY task_id ASC
 LIMIT ?
"""

#: 转手预算已用尽的 BLOCKED（``store.redispatch`` 会抛 IllegalTransitionError）。
_HANDOFF_SQL = """
SELECT task_id, state, handoff_count, card_json
  FROM tasks
 WHERE state = ?
 ORDER BY task_id ASC
 LIMIT ?
"""

#: 孤儿之一：任务还占着 CLAIMED/RUNNING，登记的持有者却已 dead。
_ORPHAN_DEAD_HOLDER_SQL = """
SELECT t.task_id, t.state, t.lease_epoch, w.worker_id, w.state
  FROM tasks t
  JOIN workers w ON w.worker_id = t.claimed_by
 WHERE t.state IN (?, ?)
   AND w.state = ?
 ORDER BY t.task_id ASC
 LIMIT ?
"""

#: 孤儿之二：worker 认为自己持有某任务，但库里已不归它（或任务已不存在）。
#: ``LEFT JOIN`` 是刻意的：任务行被删掉时仍要报出来，``task_id`` 落 ``None``。
_ORPHAN_STALE_WORKER_SQL = """
SELECT w.worker_id, w.state, w.current_task_id,
       t.task_id, t.claimed_by, t.state
  FROM workers w
  LEFT JOIN tasks t ON t.task_id = w.current_task_id
 WHERE w.state IN (?, ?)
   AND w.current_task_id IS NOT NULL
   AND (t.task_id IS NULL
        OR t.claimed_by IS NOT w.worker_id
        OR t.state NOT IN (?, ?))
 ORDER BY w.worker_id ASC
 LIMIT ?
"""

#: 孤儿之三：登记还在（idle/busy/draining），心跳却早就停了。任务若有租约问题
#: 会另以 ``stale_lease`` 报出，这条只负责"僵尸登记"本身。
_ORPHAN_STALE_HEARTBEAT_SQL = """
SELECT worker_id, state, current_task_id, last_heartbeat
  FROM workers
 WHERE state IN (?, ?, ?)
   AND last_heartbeat < ?
 ORDER BY worker_id ASC
 LIMIT ?
"""

#: S2 的去重读侧。``events`` 没有 ``finding_id`` 列，加唯一索引需要 schema 迁移，
#: 本阶段禁止——所以按 ``task_id`` 取本任务的 finding 行（走 idx_events_task），
#: 在 Python 里比对 ``finding_id``，再决定插不插。
_RECORDED_SQL = """
SELECT payload FROM events
 WHERE kind = ? AND task_id IS ?
"""

_INSERT_EVENT_SQL = """
INSERT INTO events (task_id, kind, payload, created_at)
VALUES (?, ?, ?, ?)
"""

#: S3 的数据来源。走 idx_events_kind(kind, created_at)。
_METRIC_EVENTS_SQL = """
SELECT kind, payload FROM events
 WHERE kind IN (?, ?) AND created_at >= ?
"""

#: 人工反馈要用全量（不设时间窗）：finding 可能比窗口更老，但它确实存在。
_ALL_METRIC_EVENTS_SQL = """
SELECT kind, payload FROM events
 WHERE kind IN (?, ?)
"""

#: S6：普通事件按 ``older_than`` 过期。
_SWEEP_SQL = """
DELETE FROM events
 WHERE created_at < ? AND kind NOT IN (?, ?)
"""

#: S6：指标事件保留双倍时长。
_SWEEP_METRIC_SQL = """
DELETE FROM events
 WHERE created_at < ? AND kind IN (?, ?)
"""


# --------------------------------------------------------------------- 工具


def _finding_id(
    kind: str,
    task_id: str | None,
    detected_at: float,
    *,
    subject: str | None = None,
) -> str:
    """S2 的稳定标识：``sha1(f"{kind}:{subject}:{bucket}")[:16]``。

    ``subject`` 默认取 ``task_id``；worker 级告警（``orphan_worker``）必须显式传
    ``f"{worker_id}#{form}"``，其中 ``form`` 是三种形态之一（``dead_holder`` /
    ``stale_worker`` / ``stale_heartbeat``）。

    **为什么必须带 form**：同一个 worker 可能同时命中两种形态——比如它以为自己
    持有某任务，而该任务已被删除（``stale_worker``），同时它的心跳也早停了
    （``stale_heartbeat``）。只传 ``worker_id`` 的话两条 finding 会算出同一个
    id，``record()`` 写 2 行同 id，``metrics()`` 按 id 去重只计 1（分母失真），
    ``mark_actioned`` 一次命中两条。带上 form 后每个 (worker, 形态) 各有独立 id。

    **为什么需要 subject**：空闲僵尸 worker 的 ``current_task_id`` 是 ``None``，
    若 id 只含 ``task_id``，同一小时内所有空闲僵尸会算出同一个 id，去重后
    10 个死 worker 只报 1 条——告警数量随故障规模**不增长**，这是检测盲区。

    ``task_id`` 为 ``None`` 时 f-string 落 ``"None"``——这是刻意的：换成空串会让
    "任务缺失"与"task_id 恰好是空串"撞成一个 id。
    """
    key = subject if subject is not None else task_id
    bucket = int(detected_at // _BUCKET_SECONDS)
    raw = f"{kind}:{key}:{bucket}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _parse_payload(raw: object) -> dict[str, object] | None:
    """解析 events 的 payload；坏行返回 ``None``（投影层字段级降级）。

    这里只解析本模块自己写进去的 ``supervisor_finding`` / ``supervisor_actioned``，
    但保留降级分支：一条损坏的历史行不该让整个 ``metrics()`` 抛错。
    """
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _card_limits(card_json: object) -> tuple[int, int] | None:
    """从 ``card_json`` 取 ``(max_retries, max_handoffs)``；坏行返回 ``None``。

    投影层允许字段级降级（边界同 ``control._goal_from_card``）：一行损坏的卡片
    不该让整次扫描失明。降级只影响这两个依赖卡片的 kind——若该任务同时被占用，
    它仍会以 ``stale_lease`` 出现，不会彻底消失。
    """
    data = _parse_payload(card_json)
    if data is None:
        return None
    try:
        return int(data["max_retries"]), int(data["max_handoffs"])
    except (KeyError, TypeError, ValueError):
        return None


def _payload_finding_id(raw: object) -> str | None:
    data = _parse_payload(raw)
    if data is None:
        return None
    value = data.get("finding_id")
    return None if value is None else str(value)


# ----------------------------------------------------------------- Supervisor


class Supervisor:
    """只读扫描 + 告警记账。**不碰任务状态。**"""

    def __init__(
        self, store: Store, *, now: Callable[[], float] = time.time
    ) -> None:
        self._store = store
        self._store = store
        self._now = now

    # -- 扫描（S1：纯只读）-------------------------------------------------

    def scan(self, *, limit: int = 100) -> list[Finding]:
        """只读扫描，产出 findings。**不修改任何任务状态。**

        S1：本方法只发 SELECT。不 UPDATE、不 INSERT、不 BEGIN IMMEDIATE，也不调
        ``store.patrol()``——一旦这里开始写，supervisor 就从"告警"变成"裁决"，
        而计划要求两阶段上线，本阶段只做告警。

        ``limit`` 是**每类查询的扫描行数上限**（口径与 ``store.patrol(limit=...)``
        一致：patrol 也是"扫 limit 个候选"），不是 finding 总数上限；因此返回值
        最多 ``6 * limit`` 条（``orphan_worker`` 单独占三条查询）。每条查询都带
        稳定 ORDER BY，结果可复现。

        Raises:
            ValueError: ``limit <= 0``。
        """
        if limit <= 0:
            raise ValueError(f"limit 必须 > 0，实际为 {limit}")
        now = self._now()
        findings: list[Finding] = []
        findings.extend(self._scan_stale_leases(now, limit))
        findings.extend(self._scan_retry_exhausted(now, limit))
        findings.extend(self._scan_handoff_exhausted(now, limit))
        findings.extend(self._scan_orphan_workers(now, limit))
        findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.kind, f.task_id or ""))
        return findings

    def _make(
        self,
        kind: str,
        task_id: str | None,
        severity: Severity,
        detail: str,
        now: float,
        *,
        subject: str | None = None,
    ) -> Finding:
        return Finding(
            finding_id=_finding_id(kind, task_id, now, subject=subject),
            kind=kind,
            task_id=task_id,
            severity=severity,
            detail=detail,
            detected_at=now,
        )

    def _scan_stale_leases(self, now: float, limit: int) -> list[Finding]:
        """租约过期的 CLAIMED/RUNNING：判死的候选，但**不由这里判**。"""
        rows = self._store.query(
            _STALE_LEASE_SQL,
            (
                TaskState.CLAIMED.value,
                TaskState.RUNNING.value,
                now,
                int(limit),
            ),
        ).fetchall()
        out: list[Finding] = []
        for row in rows:
            task_id, state, epoch, expires, holder = row
            overdue = now - float(expires)
            out.append(
                self._make(
                    "stale_lease",
                    str(task_id),
                    Severity.CRITICAL,
                    f"state={state} lease_epoch={int(epoch)} "
                    f"holder={holder or '-'} 租约已过期 {overdue:.0f}s"
                    "（判死归 store.patrol，本层不处置）",
                    now,
                )
            )
        return out

    def _scan_retry_exhausted(self, now: float, limit: int) -> list[Finding]:
        """``attempts > max_retries`` 的 FAILED：自动重试已用尽，需要人。"""
        rows = self._store.query(
            _RETRY_SQL, (TaskState.FAILED.value, int(limit))
        ).fetchall()
        out: list[Finding] = []
        for row in rows:
            task_id, _state, attempts, card_json = row
            limits = _card_limits(card_json)
            if limits is None:
                continue  # 卡片损坏：判不了上限，交给卡片哈希审计，不猜。
            max_retries, _max_handoffs = limits
            if int(attempts) <= max_retries:
                continue
            out.append(
                self._make(
                    "retry_exhausted",
                    str(task_id),
                    Severity.WARN,
                    f"attempts={int(attempts)} > max_retries={max_retries}，"
                    "自动重试已用尽，停在 FAILED 等人工决策",
                    now,
                )
            )
        return out

    def _scan_handoff_exhausted(self, now: float, limit: int) -> list[Finding]:
        """``handoff_count >= max_handoffs`` 的 BLOCKED：再重派会被状态机拒绝。"""
        rows = self._store.query(
            _HANDOFF_SQL, (TaskState.BLOCKED.value, int(limit))
        ).fetchall()
        out: list[Finding] = []
        for row in rows:
            task_id, _state, handoff_count, card_json = row
            limits = _card_limits(card_json)
            if limits is None:
                continue
            _max_retries, max_handoffs = limits
            if int(handoff_count) < max_handoffs:
                continue
            out.append(
                self._make(
                    "handoff_exhausted",
                    str(task_id),
                    Severity.WARN,
                    f"handoff_count={int(handoff_count)} >= max_handoffs={max_handoffs}，"
                    "store.redispatch 会抛 IllegalTransitionError",
                    now,
                )
            )
        return out

    def _scan_orphan_workers(self, now: float, limit: int) -> list[Finding]:
        """三个方向的孤儿：持有者已死；worker 仍以为自己持有；登记还在但心跳已停。

        ``workers`` 表在本阶段还没有写入方，所以"没有登记行"**不算**异常——否则
        每个在跑的任务都会被误报，告警立刻失去可信度。只有明确 ``dead`` 的持有者、
        ``current_task_id`` 与 ``tasks`` 不一致的 worker、以及心跳早于
        :data:`_WORKER_HEARTBEAT_TTL` 的登记行才算孤儿。

        已知局限：心跳过期这条以 worker 为主语，``task_id`` 取它的
        ``current_task_id``（空闲 worker 为 ``None``）。S2 的 id 公式只含
        ``(kind, task_id, bucket)``，所以同一小时内多个**空闲**僵尸 worker 会折叠
        成一条 finding——这是刻意的取舍（否则 N 个死 worker 每小时刷 N 条），
        明细在 ``detail`` 里只留先扫到的那一个。
        """
        out: list[Finding] = []
        dead = self._store.query(
            _ORPHAN_DEAD_HOLDER_SQL,
            (
                TaskState.CLAIMED.value,
                TaskState.RUNNING.value,
                "dead",
                int(limit),
            ),
        ).fetchall()
        for row in dead:
            task_id, state, epoch, worker_id, worker_state = row
            out.append(
                self._make(
                    "orphan_worker",
                    str(task_id),
                    Severity.CRITICAL,
                    f"持有者 worker={worker_id} 状态 {worker_state}，"
                    f"任务仍占着 {state}（lease_epoch={int(epoch)}）",
                    now,
                    subject=f"{worker_id}#dead_holder",
                )
            )

        stale = self._store.query(
            _ORPHAN_STALE_WORKER_SQL,
            (
                "busy",
                "draining",
                TaskState.CLAIMED.value,
                TaskState.RUNNING.value,
                int(limit),
            ),
        ).fetchall()
        for row in stale:
            worker_id, worker_state, current_task_id, task_id, claimed_by, state = row
            if task_id is None:
                detail = (
                    f"worker={worker_id}（{worker_state}）仍认为持有 "
                    f"task={current_task_id}，但该任务已不存在"
                )
            else:
                detail = (
                    f"worker={worker_id}（{worker_state}）仍认为持有 "
                    f"task={task_id}，但库里 claimed_by={claimed_by or '-'} "
                    f"state={state}"
                )
            out.append(
                self._make(
                    "orphan_worker",
                    None if task_id is None else str(task_id),
                    Severity.WARN,
                    detail,
                    now,
                    subject=f"{worker_id}#stale_worker",
                )
            )

        heartbeat = self._store.query(
            _ORPHAN_STALE_HEARTBEAT_SQL,
            (
                "idle",
                "busy",
                "draining",
                now - _WORKER_HEARTBEAT_TTL,
                int(limit),
            ),
        ).fetchall()
        for row in heartbeat:
            worker_id, worker_state, current_task_id, last_heartbeat = row
            idle_for = now - float(last_heartbeat)
            out.append(
                self._make(
                    "orphan_worker",
                    None if current_task_id is None else str(current_task_id),
                    Severity.WARN,
                    f"worker={worker_id}（{worker_state}）心跳已停 {idle_for:.0f}s"
                    f"（> {_WORKER_HEARTBEAT_TTL:.0f}s），登记未注销",
                    now,
                    subject=f"{worker_id}#stale_heartbeat",
                )
            )
        return out

    # -- 记账 ---------------------------------------------------------------

    def record(self, findings: Sequence[Finding]) -> int:
        """把 findings 写进 events（``kind='supervisor_finding'``），返回写入条数。

        S2 的去重：``finding_id`` 已按小时分桶，同一任务同一原因在同一小时内重复
        扫描得到同一个 id。去重**不是** ``INSERT OR IGNORE`` 字面量——``events``
        没有 ``finding_id`` 列，也没有对应唯一索引，光加 ``OR IGNORE`` 不会拦下
        任何一行（加索引需要 schema 迁移，本阶段禁止）。这里用等价的"同一事务内
        先查后插"：``BEGIN IMMEDIATE`` 期间没有别的写者，所以查与插之间不会有人
        插进同一条 finding。

        ``created_at`` 取**写入时刻**（``now``），``detected_at`` 留在 payload 里：
        前者是审计行的创建时间，后者是分桶依据，两者不该互相冒充。
        """
        items = list(findings)
        if not items:
            return 0
        now = self._now()
        written = 0
        with self._store.write_tx() as conn:
            for finding in items:
                if self._is_recorded(conn, finding):
                    continue
                payload = json.dumps(
                    {
                        "actioned": finding.actioned,
                        "detail": finding.detail,
                        "detected_at": finding.detected_at,
                        "finding_id": finding.finding_id,
                        "kind": finding.kind,
                        "severity": finding.severity.value,
                        "task_id": finding.task_id,
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
                cursor = conn.execute(
                    _INSERT_EVENT_SQL,
                    (finding.task_id, EVENT_FINDING, payload, now),
                )
                written += cursor.rowcount
        return written

    def _is_recorded(self, conn, finding: Finding) -> bool:
        rows = conn.execute(
            _RECORDED_SQL, (EVENT_FINDING, finding.task_id)
        ).fetchall()
        return any(_payload_finding_id(row[0]) == finding.finding_id for row in rows)

    def mark_actioned(self, finding_id: str, *, note: str = "") -> None:
        """人工反馈：标记某条告警已被处置。用于计算可行动率。

        落一条 ``kind='supervisor_actioned'`` 的事件，**不改** finding 那行：
        events 是审计流水，只追加。重复标记幂等（不重复写），未知 ``finding_id``
        抛 :class:`LookupError`——静默成功会让调用方以为反馈生效了。

        Raises:
            ValueError: ``finding_id`` 为空。
            LookupError: 库里没有这条 finding。
        """
        if not finding_id:
            raise ValueError("finding_id 不能为空")
        now = self._now()
        with self._store.write_tx() as conn:
            rows = conn.execute(_ALL_METRIC_EVENTS_SQL, _METRIC_KINDS).fetchall()
            known = False
            already = False
            for kind, raw in rows:
                data = _parse_payload(raw)
                if data is None or data.get("finding_id") != finding_id:
                    continue
                if kind == EVENT_FINDING:
                    known = True
                else:
                    already = True
            if not known:
                raise LookupError(f"未知 finding_id：{finding_id}")
            if already:
                return
            payload = json.dumps(
                {"finding_id": finding_id, "note": note},
                sort_keys=True,
                ensure_ascii=False,
            )
            conn.execute(_INSERT_EVENT_SQL, (None, EVENT_ACTIONED, payload, now))

    # -- 指标（S3）---------------------------------------------------------

    def metrics(self, *, window_seconds: float = 86400) -> dict[str, float]:
        """误报三指标：``precision`` / ``actionable_rate`` / ``repeat_rate``。

        算法写死如下（S3，三个键、取值均在 ``[0, 1]``）：

        ``precision``
            被处置的 finding 数 / 窗口内 finding 总数。
        ``actionable_rate``
            ``actioned=True`` 的 finding 数 / 窗口内 finding 总数。
        ``repeat_rate``
            窗口内同 ``(kind, task_id)`` 出现 **> 1 个不同 bucket** 的分组数 /
            分组总数。反映"同一原因反复刷屏"的比例。

        **局限（必须照读，不得当作真实精确率汇报）**：本阶段没有人工标注的真阳
        性信号，``precision`` 用 ``actioned=True`` 近似，只是**上界估计**——被处置
        不等于当初判断正确（人也可能处置了一条误报），真实精确率只可能更低。同时
        S3 给 ``precision`` 与 ``actionable_rate`` 的定义在本阶段共用同一个分子
        分母，两者数值必然相等；保留两个键是为了等真阳性信号接入后只改一个。
        计划要求"误报三指标达标"，本阶段只能保证**指标可算**，达标要等真实运行
        数据。

        无样本时返回 ``0.0``（不是 ``NaN``）：调用方要先看样本量再解读数值。

        Raises:
            ValueError: ``window_seconds <= 0``。
        """
        if window_seconds <= 0:
            raise ValueError(f"window_seconds 必须 > 0，实际为 {window_seconds}")
        since = self._now() - window_seconds
        rows = self._store.query(
            _METRIC_EVENTS_SQL, (*_METRIC_KINDS, since)
        ).fetchall()

        # finding_id -> (kind, task_id, bucket)
        findings: dict[str, tuple[str, str | None, int]] = {}
        actioned: set[str] = set()
        for kind, raw in rows:
            data = _parse_payload(raw)
            if data is None:
                continue
            fid = data.get("finding_id")
            if fid is None:
                continue
            fid = str(fid)
            if kind == EVENT_ACTIONED:
                actioned.add(fid)
                continue
            try:
                bucket = int(float(data["detected_at"]) // _BUCKET_SECONDS)
            except (KeyError, TypeError, ValueError):
                continue
            findings[fid] = (
                str(data.get("kind", "")),
                None if data.get("task_id") is None else str(data["task_id"]),
                bucket,
            )

        total = len(findings)
        handled = len(set(findings) & actioned)
        ratio = handled / total if total else 0.0

        buckets: dict[tuple[str, str | None], set[int]] = {}
        for kind_name, task_id, bucket in findings.values():
            buckets.setdefault((kind_name, task_id), set()).add(bucket)
        repeated = sum(1 for seen in buckets.values() if len(seen) > 1)
        repeat_rate = repeated / len(buckets) if buckets else 0.0

        return {
            "precision": min(max(ratio, 0.0), 1.0),
            "actionable_rate": min(max(ratio, 0.0), 1.0),
            "repeat_rate": min(max(repeat_rate, 0.0), 1.0),
        }

    # -- 清理（S6）---------------------------------------------------------

    def sweep_events(self, *, older_than: float) -> int:
        """删除过期 events，返回删除条数。

        S6：普通事件按 ``older_than`` 过期；``supervisor_finding`` 保留
        ``older_than * 2``，因为三指标要用。``supervisor_actioned`` 同理——它的
        保留期若短于 finding，``precision`` 会因为丢了"已处置"信号而虚低。

        Raises:
            ValueError: ``older_than < 0``。
        """
        if older_than < 0:
            raise ValueError(f"older_than 不能为负，实际为 {older_than}")
        now = self._now()
        cutoff = now - older_than
        cutoff_metric = now - older_than * 2
        deleted = 0
        with self._store.write_tx() as conn:
            deleted += conn.execute(
                _SWEEP_SQL, (cutoff, *_METRIC_KINDS)
            ).rowcount
            deleted += conn.execute(
                _SWEEP_METRIC_SQL, (cutoff_metric, *_METRIC_KINDS)
            ).rowcount
        return deleted
