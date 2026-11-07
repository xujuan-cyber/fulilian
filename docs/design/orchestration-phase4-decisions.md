# 阶段 4 冻结决议 · `supervisor.py` + `redispatch.py`

> 主控裁定，实现者不得自行改动。
> 上游：`orchestration-implementation-plan.md` §阶段 4（产出 `supervisor.py` / `redispatch.py`；风险"误报会摧毁信任 → 两阶段上线，先只告警不裁决"）。

---

## 零、已完成的前置项（不在本阶段派发范围内）

`_ALLOWED[CLAIMED]` 补边已由主控完成：`CLAIMED → {BLOCKED, CANCELLED}` 两条边落地，并删掉了两处绕路：

| 删掉的绕路 | 位置 | 原状 |
|---|---|---|
| `_block_expired` 的 `CLAIMED → FAILED → QUEUED` 回退分支 | `store.py` | 补边前 CLAIMED 无 BLOCKED 边 |
| `cancel()` 的 `RUNNING` 前置检查 | `store.py` | 补边前 CLAIMED 无 CANCELLED 边 |

同步改了三处：`state_machine._ALLOWED`、钉表测试字面量、`orchestration-pr1-acceptance.md` §2 转移表。
全量 **240 passed / 2 skipped / 1 xfailed**。

**本阶段所有实现都必须基于补边后的语义**：`CLAIMED` 崩溃与 `RUNNING` 崩溃走同一条 `→ BLOCKED` 路径。

---

## 一、两个模块的边界（这是本阶段最重要的约束）

| 模块 | 做 | **不做** |
|---|---|---|
| `supervisor.py` | 扫描异常、产出 findings、记录误报指标、清理过期 events | **不改任务状态、不判死、不重派** |
| `redispatch.py` | 决定重派策略（续跑点、路由指纹、豁免判定）、调用 `store.redispatch` | 不扫描、不告警 |

**计划明确"先只告警不裁决"**。判死仍归 `store.patrol()`，重派动作仍归 `store.redispatch()`。`supervisor` 只回答"哪里看起来不对"，不回答"该怎么处置"。

理由：误报会摧毁信任。如果 supervisor 直接裁决，一次误判就会改坏真实任务；只告警的话，误报的代价只是噪声。

---

## 二、公开 API（冻结）

```python
# ---- supervisor.py ----
class Severity(enum.Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str          # 稳定标识：sha1(f"{kind}:{task_id}:{bucket}")[:16]
    kind: str                # 'stale_lease' | 'retry_exhausted' | 'handoff_exhausted' | 'orphan_worker'
    task_id: str | None
    severity: Severity
    detail: str
    detected_at: float
    actioned: bool = False


class Supervisor:
    def __init__(self, store: Store, *, now: Callable[[], float] = time.time) -> None: ...
    def scan(self, *, limit: int = 100) -> list[Finding]:
        """只读扫描，产出 findings。**不修改任何任务状态。**"""
    def record(self, findings: Sequence[Finding]) -> int:
        """把 findings 写进 events（kind='supervisor_finding'），返回写入条数。"""
    def mark_actioned(self, finding_id: str, *, note: str = "") -> None:
        """人工反馈：标记某条告警已被处置。用于计算可行动率。"""
    def metrics(self, *, window_seconds: float = 86400) -> dict[str, float]:
        """误报三指标：precision / actionable_rate / repeat_rate。"""
    def sweep_events(self, *, older_than: float) -> int:
        """删除过期 events，返回删除条数。"""


# ---- redispatch.py ----
@dataclass(frozen=True, slots=True)
class RedispatchPlan:
    task_id: str
    resume_from_cursor: str | None
    route_changed: bool
    consumes_handoff: bool
    reason: str
    #: 新增（原决议遗漏，执行者报回后补）：不带新指纹的话 ``apply()`` 无法写回
    #: ``route_fingerprint``，下次 ``plan()`` 会拿旧指纹比对，把"已换路线"再判成
    #: "没换"——豁免会无限重复。带默认值以免破坏已有构造点。
    new_route_fingerprint: str | None = None


class Redispatcher:
    def __init__(self, store: Store, *, now: Callable[[], float] = time.time) -> None: ...
    def plan(self, task_id: str, *, new_route_fingerprint: str | None = None) -> RedispatchPlan:
        """只读：算出该怎么重派，**不执行**。"""
    def apply(self, plan: RedispatchPlan) -> None:
        """执行：调 store.redispatch（必要时传 handoff_cap）。"""
```

---

## 三、七条实现决议

### S1 · `scan()` 必须纯只读

不得 `UPDATE` 任何表、不得调 `store.patrol()`。违反这条就等于 supervisor 开始裁决了。

**测试必须证明这一点**：扫描前后对 `tasks` 全表做快照比对，必须逐字节相同。

### S2 · finding_id 必须稳定且去重

`finding_id = sha1(f"{kind}:{task_id}:{bucket}")[:16]`，其中 `bucket = int(detected_at // 3600)`（按小时分桶）。

作用：同一任务同一原因在**同一小时内重复扫描**产出同一个 id，`record()` 去重后就不会刷屏。这直接决定"重复率"指标能不能达标。

**原决议的错误**（执行者报回后修正）：原文写"`record()` 用 `INSERT OR IGNORE`"，但 `events` 表**没有 `finding_id` 列、也没有唯一索引**——`INSERT OR IGNORE` 在无冲突约束的表上等于普通 INSERT，一行都拦不住。

正确做法：`BEGIN IMMEDIATE` 内**先查后插**（查 `kind='supervisor_finding'` 且 payload 里 finding_id 相同的行）。同一个写事务里查与插之间没有别的写者，等价于唯一约束。将来若给 `events` 加 `(kind, finding_id)` 唯一索引，可以简化回 `INSERT OR IGNORE`。

### S3 · 三指标的算法必须写死并注释

| 指标 | 定义 | 数据来源 |
|---|---|---|
| `precision` | 被标记为真阳性的 finding 数 / 总 finding 数 | 需 `mark_actioned` 之外的正向信号；**本阶段用 `actioned=True` 近似**，并在 docstring 写明这是上界估计 |
| `actionable_rate` | `actioned=True` 的数量 / 总数 | `mark_actioned` 写入 |
| `repeat_rate` | 同 `(kind, task_id)` 出现 >1 个不同 bucket 的比例 | events 里 `supervisor_finding` 的分布 |

**必须写明局限**：`precision` 在没有人工作业反馈前只是上界估计，不能当作真实精确率汇报。计划要求"误报三指标达标"，本阶段只能保证**指标可算**，达标要等真实运行数据。

### S4 · 换路线豁免的判定

`route_fingerprint` 变化 = 换了执行路线（换模型/换工具集）。语义：**同一个方案反复失败才该收手，换方案不该被前一个方案的失败次数拖累**。

```python
route_changed = (new_route_fingerprint is not None
                 and new_route_fingerprint != current_route_fingerprint)
consumes_handoff = not route_changed
```

换路线时 `consumes_handoff=False`，但仍要 `redispatch`（任务确实要回去重跑），只是**不消耗 handoff 预算**。

实现上 `store.redispatch` 目前总是 `handoff_count + 1`。所以 `Redispatcher.apply()` 在豁免时需要自己写一条不递增的 UPDATE——**这允许在 `redispatch.py` 里写 SQL，但必须走 `transition()` 校验**，且必须带 `lease_epoch` 或状态条件防并发。

### S5 · `cursor_json` 续跑

`plan()` 读出任务的 `cursor_json`，放进 `RedispatchPlan.resume_from_cursor`；`apply()` 时保留它不动（不清空）。

**不得**在重派时清空 `cursor_json`——那会让"续跑"退化成"从头再来"，一个跑了 80% 的任务白费。

### S6 · `sweep_events` 的保留策略

只删 `created_at < now - older_than` 的 events，且**必须保留** `kind IN ('task_terminal', 'supervisor_finding')` 之外的策略由调用方决定——本阶段实现为：删除 `created_at` 过期的所有 events，但 `supervisor_finding` 保留双倍时长（因为指标要用）。

参数化：`sweep_events(older_than=...)` 内部对 `supervisor_finding` 用 `older_than * 2`。

### S7b · 终态不持有租约（主控在验收中追加）

`complete()` 与 `cancel()` 落终态时**必须同时清 `claimed_by` 和 `lease_expires`**。

理由：不清的话，`idx_tasks_holder` 会把已结束的任务算成"某 worker 手上还在跑"，而 `workers.current_task_id` 才是持有关系的权威来源；`lease_expires` 留着就是一条指向过去的租约，任何按 lease 扫描的查询都会把它当活任务。

这条是补 `Store.cancel()` 测试时发现的——**`cancel()` 从落地到现在的三个阶段里没有任何直接测试**，所以"落终态不清租约"一直没被发现。`_block_expired` 和 `redispatch` 本来就会清（它们要释放以便重新领取），只有终态路径漏了。

### S7 · 不得 import `worker.py` / `launcher.py`

`supervisor` 与 `redispatch` 只依赖 `store.py`（和 `contracts.py`）。避免把执行层拖进监督层，否则阶段 5 的进程隔离会牵连到监督逻辑。

---

## 四、验收

| # | 指标 | 判定 |
|---|---|---|
| ① | 僵尸可判定 | 造一个租约过期的 RUNNING 任务，`scan()` 产出 `kind='stale_lease'` 的 finding |
| ② | `scan()` 纯只读 | 扫描前后 `tasks` 全表快照逐字节相同 |
| ③ | finding 去重 | 同一小时内扫两次，`record()` 只写一条 |
| ④ | 转手上限生效 | `handoff_count == handoff_cap` 时 `store.redispatch` 抛 `IllegalTransitionError` |
| ⑤ | 换路线豁免生效 | `route_changed=True` 时 `consumes_handoff=False`，且 apply 后 `handoff_count` 不变 |
| ⑥ | 续跑点保留 | `apply()` 后 `cursor_json` 与重派前一致 |
| ⑦ | events TTL 生效 | 造新旧两类 event，`sweep_events` 后只删旧的，`supervisor_finding` 保留更久 |
| ⑧ | 三指标可算 | `metrics()` 返回三个键且取值在 `[0,1]` |

### 必须新增的测试（函数名固定）

```
test_scan_detects_stale_lease
test_scan_does_not_modify_tasks
test_record_deduplicates_within_bucket
test_redispatch_blocked_at_handoff_cap
test_route_change_exempts_handoff
test_cursor_json_survives_redispatch
test_sweep_events_respects_ttl
test_metrics_returns_three_ratios
```

---

## 五、禁止事项

1. **不得改 `state_machine.py` / `contracts.py` / `schema.py` / `worker.py` / `launcher.py` / `control.py` / `dispatcher.py`**。
2. `store.py` **只允许**在 `redispatch.py` 需要时新增方法（如 `redispatch_without_handoff()`），不得修改已有方法的行为。改前先报主控。
3. 不得让 `supervisor.scan()` 产生任何写操作。
4. 不得吞异常。
5. 不得为了让测试通过而放宽断言。
6. 不得跑全量 `tests/`。

## 六、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```
Python `./venv/bin/python`。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

**落盘后必须验证文件真的变了**（读回关键行），不要只看脚本打印 OK——本阶段主控就踩过"脚本报 OK 但 `if not fail` 拦住没写盘"的坑。
