# 阶段 2a 验收记录 · `store.py`

> 验收人：team-lead｜时点：2026-10-31 23:4x｜依据：`orchestration-phase2a-store-decisions.md` §四
> 方式：主控独立执行测试与压测，逐条对照冻结决议；两份成员报告因 502 中断未产出，**全部结论由主控实测得出**。

---

## 一、结论：通过（含 1 处决议修正）

计划里阶段 2 的四条验收 + 五条硬门禁全部满足。执行过程中发现**冻结决议 D7 本身写错**（要求一条表里不存在的边），已修正并补测试。

| 项 | 结果 |
|---|---|
| `test_store.py` | 8 passed |
| `test_store_multiprocess.py` | 5 passed（60.5s，含空队列 60s 压测） |
| 全量 `tests/orchestration` + 配置契约 | **203 passed / 2 skipped / 1 xfailed** |
| 公开 API 与冻结签名 | 10 个方法 + `ClaimedTask` 5 字段，**逐字一致** |
| 分层 | 无 `tools.*` 依赖 |
| 静默吞异常 | `except Exception` **0 处** |

---

## 二、五条验收的实测证据

### ① 8 进程抢同一批任务，成功数恰为 1

```
$ python scripts/stress_claim.py --workers 8 --tasks 200 --pool solve
{"claims": 200, "unique_claims": 200, "write_txns": 206, "duration": 0.05}
```

`claims == unique_claims == 200`：200 个任务各被领取恰好一次，零重复、零遗漏。

### ② 被 fence 的 worker 写回必须失败

`test_stale_epoch_write_is_fenced` 通过。实现方式是 `UPDATE ... WHERE task_id=? AND lease_epoch=?`，
`rowcount == 0` 抛 `FencedOutError`——不是"先 SELECT 再判断"，没有 TOCTOU 窗口。

### ③ 空队列写放大（10 分钟 < 100 次写事务）

```
$ python scripts/stress_claim.py --workers 15 --duration 60 --idle
# idle: workers=15 probes=900 wal_delta=0 data_version_delta=0
{"claims": 0, "unique_claims": 0, "write_txns": 0, "duration": 60.006}
```

**60 秒 900 次探测、0 次写事务**。折算到 10 分钟阈值 100 次，实际为 0，余量充足。

原因是 D2 的"先读后写"：`SELECT 1 ... LIMIT 1` 探测无行就直接退避返回，**根本不开写事务**。

### ④ kill -9 后重启可接管

拆成两条用例，因为**两条崩溃路径的语义不同**：

| 崩溃时状态 | 路径 | 实测 |
|---|---|---|
| `RUNNING`（已 start） | `→ BLOCKED`（`block_reason='lease_expired'`）`→ redispatch → QUEUED` | `test_sigkill_running_lands_in_blocked_then_redispatch` 通过 |
| `CLAIMED`（未 start） | `→ FAILED →（attempts<=max_retries）QUEUED` | `test_sigkill_claimed_is_requeued_by_retry_budget` 通过 |

两条都用 `Store(now=lambda: 未来)` 注入时钟，**不真 sleep 300 秒**。

### ⑤ 端到端吸收态

`test_end_to_end_absorption` 通过：连续 claim/fail 直到 `attempts > max_retries`，任务落 `FAILED` 且 `claim()` 再也取不到。

---

## 三、决议修正：D7 写错了

**原决议**：`patrol()` 扫到 `CLAIMED` 或 `RUNNING` 的过期任务，**都** `transition(current, BLOCKED)`。

**问题**：`_ALLOWED[CLAIMED]` = `{RUNNING, QUEUED, FAILED}`，**没有 `CLAIMED → BLOCKED` 这条边**。所以"claim 后未 start 就崩溃"的任务，按 D7 实现会直接抛 `IllegalTransitionError`——**这条决议不可实现**。

**执行者的处理**（在 `store.py` 留了 `DEVIATION (reported)` 注释）：走合法边 `CLAIMED → FAILED`，若 `attempts <= max_retries` 再 `FAILED → QUEUED`。

**主控复核：这个方案是对的，而且优于我原来那条。** 理由：

- "领了没跑就死"本质是**一次作废的尝试**，不是故障，不需要 `redispatch` 决策；
- `attempts` 在 claim 时已 +1（D3），所以 `FAILED → QUEUED` 的重试闸会自然收敛，**有界**；
- 若图省事直接走 `CLAIMED → QUEUED`（"放弃领取"边），会绕过 `attempts` 闸，**重新引入无限循环**——正是阶段 1.5 修掉的那类 P0。

已据此修正决策文档 D7，并把原来那条混合用例拆成两条（见上表）。

**这条值得记**：我冻结的决议里出现了一条表里不存在的边，说明**写决议时没有对着 `_ALLOWED` 逐条核对**。上一轮刚因为"文档承诺了不存在的行为"判过 P0，这次自己又犯了一遍，只是方向相反（这次是文档要求不存在的行为）。

---

## 四、实现纪律抽查

| 决议 | 核查方式 | 结果 |
|---|---|---|
| D1 只有 store 设 `journal_mode` | `grep` | 仅在 `store.py:175` 设置 WAL；`schema.py` 仍未碰 |
| D6 状态变更必须走 `transition()` | 脚本：每处 `SET state =` 往前 20 行内必须有 `transition(` | **8 处 UPDATE，8 处都有校验，0 处漏网** |
| 禁止静默吞异常 | `grep "except Exception"` | 0 处 |
| API 冻结 | `inspect.signature` 逐方法比对 | 10/10 一致 |

---

## 五、遗留（不阻塞）

| 项 | 归属 |
|---|---|
| `apply_schema` 的"单事务"注释与逐条提交不符 | 阶段 2b |
| `applied < SCHEMA_VERSION` 无迁移分支（`SchemaMismatchError` 已按决议抛） | 阶段 2b |
| `idx_tasks_claim` 中 `state` 位于 `pool` 之后，无 `pool` 等值时退化 | 阶段 3 全局领取时评估 |
| `deliveries` / `task_commands` 两张表尚无写入方 | 阶段 2b / 3 |

---

## 六、下一步

阶段 2b：`deliveries` 投递 CAS + `task_commands` 控制通道的存储侧 + 迁移 runner 真正落地。
之后阶段 3 的 `dispatcher.py` 可以直接基于本模块的冻结 API 编写，不需要再改 `store.py`。

---

## 七、收尾补记：迁移 runner（阶段 2 最后一项）

计划里阶段 2 的产出是三项：、**迁移 runner**、多进程压测脚本。前两项已在前文验收，本节补第三项。

### 问题

 在  时**静默什么都不做**——库停在旧版本、不报错、不升级（评审 P2-3）。 虽然会因版本不等抛 ，但那是"拒绝启动"，不是"能升级"。

### 实现

 新增：

-  —— 按"升级到哪个版本"注册步骤，当前为空（只有 v1），是后续所有阶段的扩展点。
-  —— 从当前版本逐级升到 （默认 ）。缺步骤抛 （不半升级）； 抛 （不降级）；每步包在  里，失败则 ，库保持原样。

 改为调 ，并把  转成 。

**为什么用  而不是 **： 用 （显式事务），测试里的  是默认隔离级别（隐式事务）。 在两种模式下都能用且能嵌套，不用去猜调用方的隔离级别。

### 测试（，7 条）

新库返回当前版本 / 已是最新时幂等且不产生重复版本行 / 注册步骤后能升级并建表 / 缺步骤抛  且版本停在原处 / 库比代码新时拒绝 / **失败步骤回滚且版本不前进** /  支持只升到中间版本。

### 变异验证

把  换成  后跑 ：



回滚断言不是摆设。还原后全量 **210 passed / 2 skipped / 1 xfailed**。

### 阶段 2 完成状态

| 计划产出 | 状态 |
|---|---|
| （CAS + 租约 + fencing + 先读后写 + 退避） | 完成，验收①–④ 全过 |
| 迁移 runner | 完成，本节 |
| 多进程压测脚本 | 完成（） |
