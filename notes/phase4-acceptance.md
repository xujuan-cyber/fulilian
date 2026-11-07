# 阶段 4 验收记录 · `supervisor.py` + `redispatch.py`

> 验收人：team-lead｜时点：2026-11-01 11:1x｜依据：`orchestration-phase4-decisions.md` §四
> 方式：主控独立重跑 + 变异验证 + 监督员两轮独立审计。

## 结论：通过（含 4 处修正，其中 2 处是真缺陷）

全量 **277 passed / 2 skipped / 1 xfailed**（阶段 3b 结束时 257）。

| 文件 | 测试数 |
|---|---|
| `test_supervisor.py` | 10 |
| `test_redispatch.py` | 6 |
| `test_store.py`（新增 cancel 段） | +4 |

---

## 一、前置项：`_ALLOWED[CLAIMED]` 补边（主控完成）

按阶段 3b 的裁定，补了 `CLAIMED → {BLOCKED, CANCELLED}` 两条边，删掉两处绕路：

| 删掉的绕路 | 原状 |
|---|---|
| `_block_expired` 的 `CLAIMED → FAILED → QUEUED` 回退 | 补边前无 BLOCKED 边 |
| `cancel()` 的 `RUNNING` 前置检查 | 补边前无 CANCELLED 边 |

四处同步：`state_machine._ALLOWED`、钉表测试字面量、`pr1-acceptance.md` §2、`store.py`。

**补边的意义**：绕路不只是代码丑——一个从未执行过的任务会白耗一次重试预算，且 handoff 预算完全不计账，同一个"领取后立刻死"的事件记到了两个不同的账本里。补边后统一为"租约过期且无人持有 = 故障 → BLOCKED → 由 redispatch 决定是否转手"。

---

## 二、验收中发现的缺陷一：终态任务不清租约（真缺陷）

**发现方式**：监督员报"`Store.cancel()` 全仓零测试"（`grep "\.cancel(" tests/` 零命中），主控补了 4 条测试，第一条即红：

```
AssertionError: 取消后不该还挂着持有者
assert 'w1' is None
```

**根因**：`cancel()` 与 `complete()` 落终态时都不清 `claimed_by` / `lease_expires`。`_block_expired` 和 `redispatch` 会清（它们要释放以便重新领取），**只有终态路径漏了**。

**影响**：`idx_tasks_holder` 会把已结束的任务算成"某 worker 手上还在跑"；`lease_expires` 留着是一条指向过去的租约，任何按 lease 扫描的查询都会把它当活任务。当前无生产调用方，属潜在缺陷。

**修复**：两条路径统一补 `claimed_by = NULL, lease_expires = NULL`，写进决议 S7b。

**这条存在了三个阶段没被发现，唯一原因就是 `cancel()` 没有测试。** 监督员那条"覆盖缺口"看着像流程问题，实际直接挖出了数据缺陷。

---

## 三、验收中发现的缺陷二：僵尸告警会折叠（真缺陷）

**发现方式**：`supervisor-core` 主动报告"同小时多个空闲僵尸会折叠成一条"。

**根因**：空闲僵尸的 `current_task_id` 是 `None`，而 `finding_id = sha1(f"{kind}:{task_id}:{bucket}")`——同一小时内所有空闲僵尸算出**同一个 id**，去重后 10 个死 worker 只报 1 条。

**影响**：告警数量不随故障规模增长，运维会以为"只有一台机器挂了"。这是**检测能力的上限被去重逻辑压死**，比误报更危险——误报只是噪声，漏报是沉默。

**修复**：`_finding_id` 增加 `subject` 参数，worker 级告警传 `worker_id`。新增 `test_orphan_findings_do_not_collapse_across_workers`，变异验证：

```
忽略 subject 后返回码: 1
FAILED test_orphan_findings_do_not_collapse_across_workers
=> 测试能抓住折叠
已还原: True
```

---

## 四、另外两处修正

**S2 前提是我写错的**：原文写"`record()` 用 `INSERT OR IGNORE`"，但 `events` 表没有 `finding_id` 列、也没有唯一索引——`INSERT OR IGNORE` 在无冲突约束的表上等于普通 INSERT，一行都拦不住。`supervisor-core` 改成 `BEGIN IMMEDIATE` 内先查后插，正确。决议已修正。

**`RedispatchPlan` 扩了第 6 字段** `new_route_fingerprint`：原签名不带新指纹，`apply()` 无法写回，下次 `plan()` 会拿旧指纹比对把"已换路线"再判成"没换"——豁免会无限重复。已追认并写进决议。

---

## 五、换路线豁免的两条边界（`redispatch-core` 提出，主控裁定）

**豁免是"不记账"，不是"免死金牌"。** 豁免只影响"是否消耗 handoff 预算"，不解除"预算已耗尽"的封锁。若为豁免把 `handoff_count` 归零骗守卫，`handoff_cap` 就彻底失效——每次换个指纹就能再派一次，无限重派。

代价：已在 cap 的任务换路线仍抛 `IllegalTransitionError`。接受——那种情况正确处置是人工介入。

**指纹必须写回**：`COALESCE(:route_fingerprint, route_fingerprint)`，`None` 时保原值不写 NULL。关键断言是"apply 后再 plan 传同一指纹，`route_changed is False`"——它证明豁免不会自激。

---

## 六、技术债（P1，已升级）

**`Store` 无公开只读接口，三个模块在借用私有成员**：

| 模块 | 私有成员 | 处数 |
|---|---|---|
| `dispatcher.py` | `_conn` | 1 |
| `worker.py` | `_now` | 1 |
| `supervisor.py` | `_conn`、`_write_tx` | 4 |
| `redispatch.py` | `_conn`、`_write_tx`、`_record_event` | 3 |

从 P2 升级为 **P1**：这是同一问题的第三次出现，且已经从"一个模块偷看"扩散到四个模块。根因明确——`Store` 没有任何公开读接口，冻结 API 下无法干净实现。

**建议**：阶段 5 前先做一次 `Store` 公开只读接口的补全（`sample_ids` / `now` / `read_task` / `record_event`），把四处私有访问一次性替换掉。这属于净减法，不新增能力。

## 七、其余遗留

| 项 | 说明 |
|---|---|
| `workers` 表仍无写入方 | `_WORKER_HEARTBEAT_TTL=300.0` 是常量，worker 真正登记后应改成可配置 |
| `precision` 只是上界估计 | 无人工作业反馈前不能当真实精确率汇报，已在 docstring 写明 |
| `events` 无 `(kind, finding_id)` 唯一索引 | 当前靠事务内先查后插；加索引后可简化回 `INSERT OR IGNORE` |

## 八、阶段 4 完成度

| 计划产出 | 状态 |
|---|---|
| `supervisor.py`（先只硬约束） | 完成，10 条测试 |
| `redispatch.py`（cursor 续跑、route_fingerprint、换路线豁免） | 完成，6 条测试 |
| 验收：僵尸可判定 / 转手上限 / 换路线豁免 / events TTL | 全部通过 |
| 验收：误报三指标"达标" | **只能保证可算**，达标需真实运行数据 |

**仍未接线**：`agent/orchestration/` 生产引用数仍为 0。

---

## 九、监督员第二轮：抓到我引入的第三个缺陷

### 9.1 `finding_id` 撞车（我修 `subject` 时引入）

**监督员实测**：同一 worker 同时命中"任务不存在"（`stale_worker`）与"心跳已停"（`stale_heartbeat`）时，两条 finding 的 `task_id` 不同（`None` 与 `'gone'`）却算出**同一个 `finding_id`**（`c4db36c1`）。

后果：`record()` 写 2 行同 id，`metrics()` 按 id 去重只计 1（分母失真），`mark_actioned` 一次命中两条。

**根因**：我上一轮修"折叠"时给 `_finding_id` 加了 `subject=worker_id`，但**只区分了 worker，没区分形态**。一个 worker 可以同时处于两种 orphan 形态。

**修复**：`subject = f"{worker_id}#{form}"`，`form ∈ {dead_holder, stale_worker, stale_heartbeat}`。从构造上保证 `(worker, 形态)` 唯一。

**变异验证（第一版做错了）**：我第一次只把 `stale_heartbeat` 一处退回 `str(worker_id)`，测试**没红**——因为另外两处仍带形态，id 依然不同。必须**三处全退回**才复现：

```
三处 subject 全部退回 worker_id 后: 返回码 = 1
FAILED test_orphan_forms_do_not_collide_for_same_worker
已还原: True
```

**这条值得记**：变异验证的力度必须匹配缺陷的成因。只改一处就宣布"测试能抓"，等于没验。

### 9.2 我写的一条测试是"假测试"

监督员报 MINOR："`COALESCE` 的 `None` 分支无测试"。我去补了一条，变异（去掉 COALESCE）后**测试没红**。

查下来：`_apply_exempt` 只在 `route_changed=True` 时可达，而 `route_changed` 要求新指纹非 `None`——**`COALESCE` 的 `None` 分支根本不可达**。我那条测试走的是非豁免路径，压根不执行 COALESCE。

**处置**：测试改名为 `test_non_exempt_redispatch_keeps_route_fingerprint`，docstring 明确写"它验证的是非豁免路径不抹指纹，不是 COALESCE"；并在 `redispatch.py` 注明该分支不可达、保留 COALESCE 属防御。

**结论**：不可达分支写不出有效测试，硬写只会得到"看起来在测、实际没执行到"的假测试——比没有测试更危险。

### 9.3 笔记与产物不符（第三次）

监督员指出 `notes/phase4-supervisor-core.md` 三处与产物不符：称 682 行/9 passed（实际 701 行/10 passed）、sha256 不符、仍写着"空闲僵尸折叠成一条"（代码已改为不折叠）。

**这是同类问题第三次出现**（前两次在阶段 2a、3b）。根因是笔记在交付后被后续改动覆盖，但没人回头同步。

**处置**：笔记不作为验收依据，以代码 + 测试为准。已在本记录中声明。

### 9.4 监督员已实证通过项

- **S1 纯只读**：自建四类现场，`tasks`/`events`/`workers` 三表 sha256 前后全同，trace 只出现 SELECT
- **并发去重**：6 进程同时 `record()` 同一 finding → 仅 1 行，余者返回 0
- **豁免不自激**：注入删除写回后 `route_changed` 由 `False` 变 `True`（断言真会红）
- **越界检查**：禁改文件 mtime 均早于本轮

---

## 十、最终数字

全量 **279 passed / 2 skipped / 1 xfailed**。

| 文件 | 测试数 |
|---|---|
| `test_supervisor.py` | 11 |
| `test_redispatch.py` | 7 |
| `test_store.py`（cancel 段） | +4 |
