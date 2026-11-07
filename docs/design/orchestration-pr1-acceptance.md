# PR-1 验收报告 · 子智能体编排子系统（阶段 0 + 阶段 1）

> 验收人：team-lead（主控）｜验收时点：2026-10-31 21:15｜分支 `FuLILian`（工作区未提交）
> 验收口径：**只看证据，不看汇报**。文件内容、测试输出、分层检查三项全部由主控独立执行，不采信成员自述。
> 关联文档：`orchestration-plan-review-2026-10-31.md`（评审）、`orchestration-implementation-plan.md`（实施计划）、`notes/orchestration-supervision-01.md`（独立监督）

---

## 一、验收结论

**有条件通过 —— 可以合并进 PR，但附 3 项必须跟进。**

"有条件"指的不是代码有缺陷，而是：PR-1 的契约已按评审定型，但**其中 5 个字段/约束的强制力要等到阶段 2 才生效**（`lease_epoch` 的写回校验、`attempts` 的递增、`deliveries` 的投递 CAS、`queueing_lock` 的去重、`output_path` 活跃唯一）。在此之前，它们是"表结构上有、行为上没有"。这一点必须在 PR 描述里写清，否则阶段 2 的接手者会误以为已经生效。

| 维度 | 结果 |
|---|---|
| 测试 | **151 passed / 2 skipped / 1 xfailed**（主控独立执行） |
| 状态机与规格一致性 | 逐条比对通过（8 状态 × 全部出边） |
| 分层方向 | `agent/orchestration/` 对 `tools.*` **零 import** |
| 既有文件改动面 | 3 个文件共 5 行，**全部是注释/文案，零逻辑改动** |
| 大文件完整性 | `tools/delegate_tool.py` 仍 4965 行 |
| 契约字段完备性 | 评审 B1/B2/B3 + H4/H5/H7/H8 + M4/M5/M10/M16 全部落地 |

---

## 二、交付物

### 新增（纯新增，无调用方，可独立回滚）

| 文件 | 行数 | 职责 |
|---|---|---|
| `agent/orchestration/contracts.py` | 281 | 8 态枚举 + `TaskCard` / `WorkerCapability` / `TaskHandle` + `validate_card` |
| `agent/orchestration/state_machine.py` | 149 | 转移表 + `IllegalTransitionError` + 两条守卫 |
| `agent/orchestration/config.py` | 262 | `OrchestrationConfig` 单点默认值 + `from_mapping` + `warnings()` |
| `agent/orchestration/schema.py` | 402 | DDL（6 表 / 10 索引）+ `apply_schema` + `configure_connection` + migration runner |
| `tests/orchestration/test_contracts.py` | 355 | 35 函数 / 49 参数化用例 |
| `tests/orchestration/test_state_machine.py` | 278 | TC01–TC14 + 钉表 + 穷举 |
| `tests/orchestration/test_config.py` | 170 | 21 用例 |
| `tests/orchestration/test_schema.py` | 291 | 24 用例（含 CHECK 与部分唯一索引实测） |
| `tests/orchestration/test_invariants.py` | 207 | 7 条不变量护栏（2 skip + 1 xfail） |
| `tests/agent/test_delegation_config_contract.py` | 228 | 17 用例，钉住 4 个漂移源 |
| **合计** | **2663** | — |

### 修改（既有文件，全部是口径修正）

```
AGENTS.md              | 4 ++--     max_concurrent_children default 3→10；max_spawn_depth default 2→1
tools/delegate_tool.py | 4 ++--     L3708 注释 default 2→1；L4857 注释 default 3→10
fulilian_cli/tips.py   | 2 +-       用户可见提示 "up to 3"→"up to 10"
```

**零运行期行为变更**：三处都是注释或文案，`_DEFAULT_MAX_CONCURRENT_CHILDREN = 10` 与 `MAX_DEPTH = 1` 本身未动——改的是"说法"，让它与"事实"一致。

---

## 三、验收证据

### 1. 测试（主控执行，非成员自述）

```
$ ./venv/bin/python -m pytest tests/orchestration tests/agent/test_delegation_config_contract.py -q
151 passed, 2 skipped, 1 xfailed in 3.03s
```

skip / xfail 的构成（逐条核对过，无"用 skip 掩盖没做"）：

| 标记 | 对象 | 原因 | 归属 |
|---|---|---|---|
| skip | `attempts >= handoff_count + 1` | 无写入方 | 阶段 2 |
| skip | `card_json` 派生列 == 列值 | `card_hash` 校验在 insert 路径 | 阶段 2 |
| xfail(strict) | 终态缺 `completed_at` 未被 schema 强制 | 已知缺口，补上约束会 XPASS 变红 | 阶段 2 |

### 2. 状态机逐条比对

`_ALLOWED` 实测内容与规格完全一致：

```
QUEUED      -> {CLAIMED, CANCELLED}
CLAIMED     -> {RUNNING, QUEUED, FAILED, BLOCKED, CANCELLED}   # 阶段 4 补后两条边
RUNNING     -> {BLOCKED, SUCCEEDED, FAILED, INTERRUPTED, CANCELLED, QUEUED}
BLOCKED     -> {QUEUED, CANCELLED, FAILED}
FAILED      -> {QUEUED}
SUCCEEDED / INTERRUPTED / CANCELLED -> {}
```

守卫只剩两条：`RUNNING→QUEUED` 需 `lease_expired`；`FAILED→QUEUED` 需 `attempts <= max_retries`。

### 3. 分层

```
$ grep -rn "from tools\|import tools" agent/orchestration/
CLEAN
```

### 4. 断言测试"能失败"（本轮最重要的验证）

成员提供了三条 RED 证据：改坏 `tips.py`、改坏 `AGENTS.md`、改坏 `delegate_tool.py` 注释，对应测试分别变红，改回后转绿。**这条比"测试通过"更有价值**——它证明测试真的在读那四个文件，而不是自说自话。

---

## 四、过程记录：4 次实质纠偏

这一节是本报告的核心。交付物本身没有意外，**意外全部发生在派发与执行过程中**，且每一次都值得沉淀。

### 纠偏 1 · 派发设计缺陷：共享接口成了单点依赖（责任在主控）

我让 `worker-contracts` 产出 `contracts.py`，另外两个成员"等文件出现再用"。结果两个成员阻塞在等待上，其中一个开始自己反推状态表。

**根因**：接口是三个成员的公共契约，却被派给其中一个成员生产。正确做法是**接口由主控先冻结并落盘**，worker 只实现不定义。

### 纠偏 2 · 126 个测试全绿，但转移表是错的

`worker-statemachine` 交付时报告 30 测试全绿，我核对 `_ALLOWED` 发现与规格 5 处不符：`QUEUED→BLOCKED`（多余）、`CLAIMED` 三条全错、`RUNNING` 漏 `INTERRUPTED`、`BLOCKED` 漏 `FAILED`、`INTERRUPTED→QUEUED`（应为终态）。

**测试为什么没抓住**：因为测试断言的也是同一张错表。这叫**自洽的错误**——实现与测试对同一个错误理解达成一致，绿灯反而成了伪证。

**处置**：不只是改表，而是新增 `test_allowed_table_matches_spec_literal()`，把规格表**硬编码**进测试。穷举测试只能保证"实现 == 表"，钉表测试才能保证"表 == 规格"。这是本轮方法论上最有价值的一条。

### 纠偏 3 · Phase 0 的漂移面漏了一半（监督员抓的）

我派发的范围是 `AGENTS.md` 两处 + `delegate_tool.py` 一处注释。监督员静态审计时指出还有 `delegate_tool.py:4857` 与 `fulilian_cli/tips.py:132`，我复核确认——**后者是用户直接看到的文案**，比文档漂移更严重。

**教训**：修"同一个错误数字"时，不能只改自己记得的位置，要用 grep 反查全仓。而正确的解法不是多改几处，是**让测试去钉**——现在 17 个用例覆盖 4 个源，任何人再写错都会红。

### 纠偏 4 · 跨成员语义漂移，发生在注释里（测试抓不到）

`worker-statemachine` 指出 `worker-contracts` 在消息里说过"`INTERRUPTED` 走恢复流程重新入队"，而最终表里 `INTERRUPTED` 是空出边终态。

**这类漂移最危险**：代码错会被测试抓，注释错不会。一个错的注释会让下一个人在测试变红时选择改测试而不是改实现。

**处置**：在 `contracts.py` 与 `state_machine.py` 各钉一段语义说明：

| 触发 | 路径 | 自动恢复 |
|---|---|---|
| 进程被杀 / 卡死（租约过期） | `RUNNING → BLOCKED → QUEUED` | **是** |
| 用户 `stop` | `RUNNING → INTERRUPTED` | 否（终结） |
| 用户取消 | `RUNNING → CANCELLED` | 否（终结） |

---

## 五、对方案与评审的修正（3 条，均已在代码中体现）

这三条是执行过程中"反向修正规格"的案例——**worker 的判断优于我的评审稿**。

### 修正 1 · `max_retries` 的 off-by-one（方案原文缺陷）

方案 §4.2 写 `FAILED → QUEUED 需 attempts < max_retries`，而 §4.1 定义 `max_retries: int = 1`、`attempts` = 执行次数（含首次）。

两者组合：`attempts=1, max_retries=1` → 拒绝。即 **`max_retries=1` 的真实效果是"零重试"**，与字段名直接矛盾。

**修正**：守卫改为 `attempts <= max_retries`，`max_retries=1` 真的允许 1 次重试（共 2 次执行）。已加 `test_max_retries_semantics` 钉住。

### 修正 2 · 评审 §5.3 的 `SUCCEEDED → BLOCKED` 是错的

我在评审里建议"audit 抽检 SUCCEEDED 失败后回退为 BLOCKED"。这条与终态不可逆、`completed_at`、`output_path` 活跃唯一索引三者全冲突。

**修正**：audit 发现问题应**新建 correction 任务并 `depends_on` 原任务**，不改原任务状态。评审稿该条作废。

### 修正 3 · 依赖失败的收敛路径：`CANCELLED` 而非 `BLOCKED`

成员从评审 M6 推断出 `QUEUED → BLOCKED`，我驳回：

- `BLOCKED` 的语义是"**跑过**、被判死或需人工决策、**可回收重派**"；
- 依赖失败的下游**根本没跑过，也不可回收**（依赖不成功，重派多少次都一样）。

所以收敛是 `QUEUED → CANCELLED`，把 `block_reason="dependency_failed:<task_id>"` 写进数据，不占状态位。"让参数有意义"不构成加边的理由——那是尾巴摇狗。

---

## 六、独立监督的结论与局限

### 监督员第一阶段（静态审计）：有条件通过

覆盖度矩阵：✅ 10 项、◐ 10 项、✗ 5 项、○ 8 项。抓到的实质问题：Phase 0 漂移面漏 2 文件、`test_invariants.py` 无人认领、契约卡缺 M2/M5/M7/M16 四项。

**这三条全部被采纳并修复**：漂移面已补齐、`test_invariants.py` 已交付、M5（`can_write_own_output`）与 M16（`output_schema: str`）已在契约中落地。

### 局限（必须说明，否则会误读监督结论）

监督员的矩阵是**19:47 的快照**，此后执行仍在推进。经主控复核，5 个 ✗ 中有 3 个已消解（M5、M16、§6.3），**真正延后的只有 M2 与 M7**。另有一条 Ⓜ 标记失真：矩阵把 M6 记为"✅ 用 `QUEUED→BLOCKED` 覆盖"，但该边已被我驳回，实际覆盖方式是 `QUEUED→CANCELLED`。

**这说明监督机制本身也需要被审计**——监督员的结论是输入，不是判决。

---

## 七、明确延后项（带阶段归属，不是"忘了"）

| 项 | 内容 | 归属 | 为什么不能现在做 |
|---|---|---|---|
| B1 后半 | `lease_epoch` 的**写回校验**（fenced worker 产物作废） | 阶段 2 | 校验点在 `store` 的每次 UPDATE，PR-1 无 store |
| B3 后半 | `list/steer/stop` 的跨进程语义 + tool description 改写 | 阶段 3 | 需要 worker 进程模型先定 |
| M2 | `TaskCard.depth` 的父子树语义 | 阶段 4 | 监督任务卡的生成逻辑在阶段 4 |
| M7 | `depends_on` 允许批内前向引用 | 阶段 2 | 校验在 `enqueue`，PR-1 无 enqueue |
| M8 | `events` / `dispatch_log` TTL | 阶段 4 | 需要 patrol 的清理周期 |
| H1 | worker 三档承载（inline / embedded / daemon） | 阶段 3 | — |
| H2 | 空队列写放大（先读后写 + 退避） | 阶段 2 | 需要真实 claim 路径才能压测 |
| H6 | fork/线程 + Windows 进程树 | 阶段 5 | 独立灰度阶段 |

---

## 八、阶段 2 的硬门禁

PR-1 把"表"建好了，阶段 2 要让"行为"生效。以下五条**不满足则阶段 2 不算完成**：

1. **`attempts` 每次 claim 必须 +1** —— 否则 `FAILED → QUEUED` 是无限循环，而状态机完全放行、穷举测试全绿。对应 `test_invariants.py` 第 1 条从 skip 转真断言。
2. **每次写回必须带 `lease_epoch` 校验** —— 否则 B1 的僵尸写回问题原样存在。
3. **claim 前先读后写** —— 否则空队列时 15 worker × 5Hz 的写事务会把 SQLite 单写者打满。
4. **`test_lease_expiry_lands_in_blocked_not_interrupted`** —— 崩溃必须落 `BLOCKED`（可自动恢复），不能落 `INTERRUPTED`（用户意图）。状态机拦不住"用错意图"的调用方，只能在调用侧钉。
5. **端到端吸收态** —— 连续 claim/fail N 次后，任务落 `FAILED` 且不再被 claim 到。这条比"`attempts` 恰好 +1"更强：`+1` 只保证计数对，吸收态保证**计数被真正用于终止**。若 `store` 递增了 `attempts` 但 claim 的 `WHERE` 没读它，两个 bug 会互相抵消，单看 `+1` 测试仍然是绿的。

---

## 九、流程结论（三条，供后续阶段复用）

**1. 测试绿 ≠ 交付对。** 实现与测试可能对同一个错误理解达成一致，形成"自洽的错误"。防线是**对着规格逐行比对产物**，而不是看测试报告。规格里能被硬编码的东西（转移表、默认值、文案），就要硬编码进测试。

**2. 注释是规格的一部分。** 本轮唯一一个测试完全抓不到的偏差，是"`INTERRUPTED` 可恢复"这句注释。它会让人在测试变红时选择改测试。凡是被下游当规格读的注释，都要和代码同等审查。

**3. 共享接口由主控冻结，不派给 worker。** 接口是多方公共契约，派给其中一方生产，必然产生等待、重复定义、以及"谁说了算"的模糊。这一条是本次派发最大的设计失误。

---

## 十、下一步

阶段 2（存储与领取，约 2 周）可以启动，前置条件是本 PR 合并。启动时需注意：

- `store.py` 是本项目**第一个真正有并发语义的模块**，建议先写 8 进程抢同一任务的压测脚本，再写实现；
- `schema.py` 已有 `apply_schema`，但**迁移 runner 只做了雏形**，阶段 2 要补齐 `schema_version` 的升级路径；
- 队列独立建库（`orchestration.db`）已定，阶段 2 不要再讨论是否复用 `state.db`。

---

## 十一、补记

### 1. 最终测试数字

152 → **154 passed / 2 skipped / 1 xfailed**（补入跨层双向断言后）。

### 2. 两处测试润色（主控直接改，仅测试文件，零生产代码变更）

| 文件 | 改动 | 理由 |
|---|---|---|
| `test_state_machine.py:78` | 集合不等断言 → 拆出 `missing` / `extra` 并给可执行提示，末尾加"不要改这条断言来消红" | 原来只报"集合不等"，看到红的最短路径是改断言。本轮已吃过一次"改测试消红"的亏 |
| `test_contracts.py:56` | 成员顺序断言（列表比对）→ 集合比对 | `StrEnum` 成员顺序无语义；顺序敏感会红在"合法地新增一个状态"上，那是变更探测器 |

### 3. 跨层不变量：双向断言，两个方向挡不同的错

执行中发现一个结构性缺口：**有些约束在架构上无处安放**。`RECLAIMABLE_STATES` 可由 `state_machine._ALLOWED` 派生，但 `contracts.py` 不能 import `state_machine.py`（依赖方向相反，会成环）。这条派生既不能写成注释（不执行）、也不能写成派生值（不允许），**只能写成测试**。约定：跨层不变量统一放 `tests/orchestration/test_invariants.py`。

初版只写了方向 A（可回收 ⇒ 有回队列的边），监督员指出这是**假风险**——只验证了"新回收态没给边"，不验证"表加了新边但没分类"。补为两条：

| 方向 | 断言 | 挡住的错误 |
|---|---|---|
| A | 可回收 ⇒ 有 `-> QUEUED` 边 | 新增回收态却忘给边，`patrol()` 扫到却无处可放 |
| B | 非终态且有 `-> QUEUED` 边 ⇒ 必须被分类 | **更危险**：给表加了新边但没想清算 retry 还是 reclaim，集合静默过时，`patrol()` 少扫一个该回收的状态——而所有测试仍是绿的 |

终态豁免：终态任务没有活跃持有者，回到队列只能是调用方 retry（如 `FAILED`），不可能是 `patrol()` 回收。

阶段 2 可把方向 A 升级为等式，但**减项必须用 `TERMINAL_STATES` 而非硬编码 `{FAILED}`**——前者表达"终态无活跃持有者"（原因），后者表达"我们知道 FAILED 是特例"（现象）。用原因写的等式在 `INTERRUPTED -> QUEUED` 落地时会自动要求同步，不会在正确改动上误红。

### 4. 监督员第二阶段：抓到一个真阻塞项，改变了验收结论

`supervisor` 两阶段都交付了，且第二阶段**改变了结论**——这是本次派发里唯一一次"独立第三方拦下了主控已经准备放行的东西"。

**第一阶段（静态审计）**：抓到 `delegate_tool.py:4857` 与 `fulilian_cli/tips.py:132` 两处我漏掉的漂移文件，后者是用户直接可见的文案。

**第二阶段（产物审计）**：判定"有条件通过"，指出唯一阻塞项 B-1 —— `schema.py:64-106` 保留了一条 `except Exception` 静默回退到 `_FALLBACK_TASK_STATES` 的路径，且模块导入时就固化成 `TASK_STATES`；对应的守卫测试在 import 失败时是 `pytest.skip`，**这条路径永远测不出来**。

它的判词是本次审计最有力的一句：

> 这个 PR 的唯一价值主张就是"收敛真相源"。在收敛动作里内嵌一份带静默回退的副本，等于把被修的病原样搬进修复本身。

**已修复**（主控执行）：
1. 删除 `_FALLBACK_TASK_STATES` / `_FALLBACK_TERMINAL_STATES` 两个常量与 `try/except`，让 `ImportError` 直接冒泡；
2. `test_schema.py` 的守卫测试从 `pytest.skip` 改为硬导入 + 断言；
3. 新增 `test_schema_has_no_fallback_state_literals`，防止后人把 fallback 加回来。

修复后：**156 passed / 2 skipped / 1 xfailed**。

**流程教训**：这个缺陷之所以能活到验收，是因为"暂时性兼容代码"从来不会被主动删除——`contracts.py` 落地后那条 fallback 立刻变成死代码，但没有任何机制提醒删除。**临时方案必须带删除条件，否则它比没有方案更危险**：它会在无人知晓的情况下成为事实标准。
