# 阶段 4 · `supervisor.py` 交付说明

改动仅三处：`agent/orchestration/supervisor.py`（新建，682 行）、
`tests/orchestration/test_supervisor.py`（新建，396 行）、本文件。`redispatch.py` /
`store.py` / `schema.py` / `state_machine.py` / `contracts.py` / `worker.py` /
`launcher.py` / `control.py` / `dispatcher.py` / `tools/` 均未碰（store.py 10:35、
state_machine.py 10:33、redispatch.py 10:45 早于本次落盘）。

## 1. `inspect.signature`（与决议 §二 逐项一致）

```
Severity: ['INFO=info', 'WARN=warn', 'CRITICAL=critical']
Finding: [('finding_id','str'), ('kind','str'), ('task_id','str | None'),
          ('severity','Severity'), ('detail','str'), ('detected_at','float'),
          ('actioned','bool')]
Supervisor.__init__(self, store: 'Store', *, now: 'Callable[[], float]' = <built-in function time>) -> 'None'
Supervisor.scan(self, *, limit: 'int' = 100) -> 'list[Finding]'
Supervisor.record(self, findings: 'Sequence[Finding]') -> 'int'
Supervisor.mark_actioned(self, finding_id: 'str', *, note: 'str' = '') -> 'None'
Supervisor.metrics(self, *, window_seconds: 'float' = 86400) -> 'dict[str, float]'
Supervisor.sweep_events(self, *, older_than: 'float') -> 'int'
```

注解带引号是包内统一 `from __future__ import annotations`（PEP 563）；参数名/顺序/
默认值与冻结签名逐字相同。

## 2. `scan()` 的完整 SQL（`supervisor.py:107-173`，全部 SELECT）

```sql
-- stale_lease
SELECT task_id, state, lease_epoch, lease_expires, claimed_by FROM tasks
 WHERE state IN (?,?) AND lease_expires IS NOT NULL AND lease_expires < ?
 ORDER BY lease_expires ASC, task_id ASC LIMIT ?;
-- retry_exhausted（Python 侧比 attempts > max_retries）
SELECT task_id, state, attempts, card_json FROM tasks
 WHERE state = ? ORDER BY task_id ASC LIMIT ?;
-- handoff_exhausted（Python 侧比 handoff_count >= max_handoffs）
SELECT task_id, state, handoff_count, card_json FROM tasks
 WHERE state = ? ORDER BY task_id ASC LIMIT ?;
-- orphan A：持有者 dead，任务仍占着 CLAIMED/RUNNING
SELECT t.task_id,t.state,t.lease_epoch,w.worker_id,w.state FROM tasks t
  JOIN workers w ON w.worker_id=t.claimed_by
 WHERE t.state IN (?,?) AND w.state=? ORDER BY t.task_id LIMIT ?;
-- orphan B：worker 以为持有，库里已不归它（任务行缺失时 task_id=None）
SELECT w.worker_id,w.state,w.current_task_id,t.task_id,t.claimed_by,t.state
  FROM workers w LEFT JOIN tasks t ON t.task_id=w.current_task_id
 WHERE w.state IN (?,?) AND w.current_task_id IS NOT NULL
   AND (t.task_id IS NULL OR t.claimed_by IS NOT w.worker_id
        OR t.state NOT IN (?,?)) ORDER BY w.worker_id LIMIT ?;
-- orphan C：登记还在（idle/busy/draining），心跳早于 now-300s
SELECT worker_id,state,current_task_id,last_heartbeat FROM workers
 WHERE state IN (?,?,?) AND last_heartbeat < ? ORDER BY worker_id LIMIT ?;
```

`limit` 是**每类查询的扫描行数上限**（口径同 `store.patrol(limit=...)`），故返回值
≤ `6*limit`。

## 3. S1–S7 落点（真实行号）

| 决议 | 落点 |
|---|---|
| S1 纯只读 | `scan` 277；`_scan_*` 320/348/374/400 只发 SELECT；不调 `patrol()`。证据：test:159 |
| S2 id 稳定分桶 | `_finding_id` 214、`_BUCKET_SECONDS` 62；去重 `record` 497 + `_RECORDED_SQL` 176 |
| S3 三指标 | `metrics` 584；"只是**上界估计**"在 598；两指标同分子分母的事实写在 600–601 |
| S4 换路线豁免 | **不在本模块**（`redispatch.py`）。边界声明在模块 docstring 7–8 |
| S5 `cursor_json` | **不在本模块**。`scan` 不读不写 `cursor_json` |
| S6 events TTL | `sweep_events` 659；`_METRIC_KINDS` 59、`_SWEEP_SQL` 199、`_SWEEP_METRIC_SQL` 205 |
| S7 不 import 执行层 | 39–40 只有 `contracts.TaskState` + `store.Store`；声明在 25–27 |

`orphan_worker` 的三个方向：`_ORPHAN_DEAD_HOLDER_SQL` 136、`_ORPHAN_STALE_WORKER_SQL`
148、`_ORPHAN_STALE_HEARTBEAT_SQL` 164；心跳阈值 `_WORKER_HEARTBEAT_TTL` 68（300s =
60 个 `heartbeat_interval=5.0` 周期）。

## 4. `pytest tests/orchestration/test_supervisor.py -q`

```
.........                                                                [100%]
9 passed in 0.52s
```

9 条 = 决议要求的 5 条固定名 + `mark_actioned` 幂等/未知 id + 补的三条 finding 测试
（retry 322 / handoff 349 / orphan 382）。

## 5. 变异证明（每条都真红过，还原后复跑 9 passed）

| # | 注入 | 结果 |
|---|---|---|
| A | `scan()` 里插 `UPDATE tasks SET updated_at = updated_at WHERE 0`（零行写） | `test_scan_does_not_modify_tasks` 红：`AssertionError: scan() 发出了写语句：['UPDATE tasks SET updated_at = updated_at WHERE 0']` |
| B | 同上改成 `updated_at = updated_at + 1`（真改数据） | 红：`AssertionError: scan() 改动了 tasks 表`（快照摘要不一致） |
| C | `_scan_retry_exhausted` 的 `if int(attempts) <= max_retries:` 改成 `if True:` | `test_scan_detects_retry_exhausted` 红 |
| D | `_scan_handoff_exhausted` 的 `if int(handoff_count) < max_handoffs:` 改成 `if True:` | `test_scan_detects_handoff_exhausted` 红 |
| E | `_ORPHAN_STALE_HEARTBEAT_SQL` 的 `AND last_heartbeat < ?` 改成 `AND 0 AND last_heartbeat < ?` | `test_scan_detects_orphan_worker` 红 |

A 证明语句级探针能抓住**零行**写（数据没变也要红）；B 证明快照比对能抓住**真改**；
C/D/E 证明三类 finding 各有一条测试在守着。还原后 `sha256 = 3f0f2561…d606`。

## 6. 三处需要主控知情的判断

1. **去重不是字面量 `INSERT OR IGNORE`。** `events` 无 `finding_id` 列、无对应唯一
   索引，单加 `OR IGNORE` 一行都拦不住（加索引需 schema 迁移，本阶段禁止）。实现为
   "`BEGIN IMMEDIATE` 内先查后插"，语义等价且无并发窗口。S2 文档措辞由主控修。
2. **`supervisor_actioned` 与 `supervisor_finding` 同享双倍 TTL。** S6 只写了
   finding；理由（"指标要用"）对反馈事件同样成立——反馈先过期会让 `precision` 因
   丢信号而虚低。
3. **`orphan_worker` 的心跳阈值是硬编码常量 300s。** 冻结 API 没有这个旋钮，
   `workers` 表本阶段也没有写入方；等 worker 真正登记后应改成可配置。另：心跳这条
   以 worker 为主语，`task_id` 取 `current_task_id`，故同一小时内多个**空闲**僵尸
   worker 会折叠成一条 finding（S2 的 id 只含 `kind/task_id/bucket`）——刻意取舍，
   避免 N 个死 worker 每小时刷 N 条，局限已写进 `_scan_orphan_workers` docstring。
