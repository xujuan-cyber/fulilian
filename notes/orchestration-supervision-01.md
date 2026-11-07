# 独立监督 · 第 01 号（静态审计：计划 → 任务卡 → 落点）

> 监督员：`supervisor`（只读角色，对应方案 §4.6）。审计时点：2026-10-31，worker 交付前。
> 审计对象：`docs/design/orchestration-plan-review-2026-10-31.md`（评审）、`docs/design/orchestration-implementation-plan.md`（实施计划）、任务卡 #1–#4。
> 取证方式：逐条读源码核对，不采信任务卡自述；未运行任何测试（worker 仍在写，中间态无意义）。

---

## 判定

**有条件通过** —— 三张实施卡的落点与评审的阻断项主干一致（B2 拆表、B3 控制指令表、B1 的 `lease_epoch` 列均已落到 #4），方向没有偏；但**契约卡 #2 漏了 4 个计划明文要求在 PR-1 就定型的字段**、**阶段 0 的漂移面漏了 2 个文件**、**计划 §6.3 的"不变量测试骨架"无人认领**，这三处若不补，PR-1 的"契约一次定型、避免阶段 2 返工"目标不成立。

---

## 覆盖度矩阵

图例：✅ 已覆盖 ｜ ◐ 部分覆盖 ｜ ✗ 本阶段内应覆盖但无人认领 ｜ ○ 本阶段外（计划已排到后续阶段，不算漏）

| 条目 | 覆盖 | 落点 | 说明 |
|---|---|---|---|
| B1 fencing token | ◐ | #4 `lease_epoch`/`claimed_at`（`schema.py:145-146`） | 列有了，但**写回校验的契约方无归属**：评审要求"fenced worker 的产物一律作废"写进 worker 契约（§2 B1 末段），#2 `WorkerCapability` 未要求携带 `epoch`，#3 `transition()` 也只收 `lease_expired`。阶段 5 验收才提"产物作废"，PR-1 无位置 |
| B2 拆 `deliveries` | ✅ | #4（`schema.py:203-221`，含 `idx_deliveries_task` 一任务一投递） | 与评审 §2 B2 的 DDL 逐列一致 |
| B3 `task_commands` | ◐ | #4（`schema.py:225-236`） | 表已建。但 `list/steer/stop` 语义降级（"入队指令、最多一个 heartbeat 生效"）必须写进 tool description（评审 §2 B3 末段），无任何卡承担；`TaskCommand` 契约也未被 #2 要求 |
| H1 worker 三档承载 | ○ | 阶段 3（计划 §2） | 本阶段外。但 `OrchestrationConfig` 未预留"承载模式"开关，阶段 3 需改 config 的公开面 |
| H2 空队列写放大 | ○ | 阶段 2 验收③ | 本阶段外 |
| H3 aging + bottom_level | ◐ | #4 config `aging`；`schema.py:153` `bottom_level`、`schema.py:166-167` 排序索引已去 `tier` | 卡片正文只写"aging"，**未列 `bottom_level`**；实现者自行读了计划才补上。卡片与实际产出不一致 = 验收标准悬空 |
| H4 token 预算 | ◐ | #2 `budget_tokens`/`budget_usd`；#4 "预算" | 字段级已覆盖。批次级/全局闸门（评审 §3 H4 第 3、4 条）属阶段 2/4，本阶段外 |
| H5 `cancel_requested_at` | ✅ | #4（`schema.py:147`） | 且**未**新增 `CANCEL_REQUESTED` 状态枚举，符合"加列不加状态"的原意 |
| H6 平台陷阱（fork/Windows 进程树） | ○ | 阶段 5 | 本阶段外 |
| H7 活跃态唯一索引 | ✅ | #4（`schema.py:176-179`，`WHERE state NOT IN terminal`） | 与评审 §3 H7 建议逐字对应 |
| H8 `card_hash` + 列/JSON 双真相 | ◐ | #4 实际有 `card_hash`（`schema.py:133`） | **卡片未列 `card_hash`**；且"列是唯一真相、`card_json` 仅供重放审计"这条契约没有写进任何卡的验收，#2 也未要求 |
| M1 pools 数字自相矛盾 | ○ | 阶段 6 验收 | 本阶段外。但 config 无 `pools` 字段，`sum(pools) <= max_running` 不变式在 PR-1 无处落 |
| M2 supervisor `depth=0` | ✗ | — | `TaskCard` 无 `depth` 字段/语义说明，#2 未要求。评审 §7 把"§4.6 监督"列为待改章节，契约不定义 depth 则阶段 4 无法表达父子树 |
| M3 `patrol()` 跳过 supervisor | ○ | 阶段 4 | 本阶段外 |
| M4 worktree 隔离 | ✅ | #2 `worktree` 字段 | — |
| M5 `can_write_own_output` | ✗ | — | 评审 §4 M5 要求把 `can_write_shared` 拆两个能力位；#2 明确列了 `WorkerCapability` 却未提拆分。这是**阶段 1 契约项**，不是后续阶段 |
| M6 依赖失败传播 | ✅ | #3（`state_machine.py:122` 有 `QUEUED→BLOCKED` 且带 `dependency_failed` 守卫） | 覆盖方式优于卡片描述（用守卫而非新增状态） |
| M7 `depends_on` 前向引用 | ✗ | — | #2 `validate_card` 未要求"允许批内前向引用、批次插入后整体校验"。按字面实现会拒绝合法 DAG，属**阶段 1 契约项** |
| M8 `events`/`dispatch_log` TTL | ◐ | #4（`schema.py:256-278` 两表已建） | 表在，TTL 策略与清理函数无要求；属阶段 4，可接受，但需在 schema 注释里留位（已有索引，未见 TTL 列） |
| M9 schema 迁移机制 | ✅ | #4 `schema_version` + migration runner（`schema.py:283`） | — |
| M10 幂等键 | ◐ | #2 `idempotency_key`；#4 实际是 `idempotency_key`+`queueing_lock`+`lock` 三列（`schema.py:148-150`） | **口径已分裂**：计划 §1.2① 明确"修订 M10：拆 `queueing_lock`（排队去重）+ `lock`（运行互斥）"，#2 卡未同步。契约与 schema 对同一件事两种说法，正是本次改造要消灭的问题 |
| M11 `route_fingerprint` 算法 | ○ | 阶段 4 | schema 有列（`schema.py:139`），算法归属阶段 4，本阶段外 |
| M12 双计数不变式 | ◐ | #3 收 `attempts`/`max_retries` | `handoff_count` 与不变式 `attempts >= handoff_count + 1` 无测试归属（见"偏离风险 R2"）。另：`schema.py:137` `attempts DEFAULT 1`，与"执行次数（含首次）"的零点未定义 |
| M13 三键合两键 | ✅ | #4 aging + schema 去 `tier` 排序 | 与 H3 同源，实现方向正确 |
| M14 `batch_limit=5` / `hard_cap=15` | ✅ | #4 config 卡逐字命中 | — |
| M15 `trace_id`/`span_id` | ◐ | 实际有（`schema.py:151-152`） | 卡片未列，同 H3/H8 的"实现者自觉"问题 |
| M16 frozen + 可变默认值 | ✗ | — | 评审 §4 M16 给了明确解法（`output_schema` 改 JSON 字符串或 `eq=False`+显式 `__hash__`），#2 卡只说"frozen dataclass"。`TaskCard` 若含 `dict` 字段，`frozen=True` 后 `hash()` 抛 `TypeError`，这是**必踩的实现陷阱**，且属阶段 1 |
| M17 `StrEnum` | ✅ | #2 卡明确 "StrEnum/IntEnum" | — |
| M18 `_ALLOWED` 用限定名 | ✅ | #3 实际用 `TaskState.X`（`state_machine.py:38-61`） | 卡片未明说，实现正确 |
| §6.3 改动 3：`test_invariants.py` 骨架 | ✗ | — | 评审 §6.3 把它列为"**第一个 PR 的范围**"的第三项改动，五条断言（含 `attempts>=handoff+1`、`card_json` 派生列一致、`output_path` 活跃态唯一）。**没有任何任务卡覆盖**，`tests/orchestration/` 至今无此文件 |
| §1.3 独立建库 / 不改 `journal_mode` | ◐ | #4 实际做对了（`config.py:52` `orchestration.db`；`schema.py:375-385` 显式不碰 journal mode） | 但**卡片与验收标准里一个字都没有**，全靠实现者读了评审。无回归防护 = 阶段 2 有人"顺手优化"就会复现 §1.3 的排他锁冲突 |
| §1.2(c) `_recent_subagents` 迁移映射 | ○ | 阶段 7 | 本阶段外。计划 §2 阶段 7 已列删除项，但评审要求的"映射表补一行 `_recent_subagents → tasks` 终态记录"仍无人补文档 |

**汇总**：✅ 10 项、◐ 10 项、✗ 5 项、○ 8 项。5 个 ✗ 全部落在阶段 0/1 的范围内，其中 4 个（M2/M5/M7/M16）是**契约卡 #2 的字段清单缺口**，1 个（§6.3）是**无人认领的独立交付物**。

---

## 偏离风险

**R1 · 阶段 0 的漂移面漏了两个文件，"同一个错误数字"修了一半**
- 依据：`AGENTS.md:1135` 与 `tools/delegate_tool.py:4857` 与 `fulilian_cli/tips.py:132` 三处都写"default 3"，`fulilian_cli/config_defaults.py:2069` 实际是 `10`。计划 §2 阶段 0 只点了 `delegate_tool.py` L3708（"default 2 for parity…"，实际默认 `1`，见 `config_defaults.py:2077`），任务卡 #1 写"AGENTS.md 改 2 处、delegate_tool.py 改 1 处"——即 L3708。结果：**AGENTS.md 的"3"被修掉，而 `delegate_tool.py:4857` 的"3"和 `tips.py:132` 的"3"留着**，其中 `tips.py:132` 是直接呈现给用户的提示文案。
- **实测已发生（审计时点）**：`git diff` 显示 `AGENTS.md:1135/1144` 与 `delegate_tool.py:3708` 已按卡改完（10 / 1 / 1），而 `delegate_tool.py:4857` 仍是 `(default 3)`、`tips.py:132` 仍是 `up to 3`。即"改了三处、漏了两处"已成事实，不是假设。
- 建议动作：把 `tools/delegate_tool.py:4857`、`fulilian_cli/tips.py:132` 纳入 #1 范围；新增的一致性断言测试必须覆盖三个文件（AGENTS.md / delegate_tool.py / tips.py），否则它只能防住"AGENTS.md 再次漂移"，防不住真正的复发面。

**R2 · `tests/orchestration/test_invariants.py` 无人认领，而它是计划里的"第一个 PR 第三项"**
- 依据：评审 §6.3 明确"改动 3：加一个不变量测试骨架（纯测试，无生产代码）"，五条断言并列出了理由（"这类不变量最容易在重构中被静默破坏"）；实施计划 §2 阶段 1 的产出清单里**没有它**，四张卡也都没有。
- 建议动作：追加一张卡或并入 #4，先把五条断言的空壳落地（可 `skip` 占位）。否则阶段 2 的 store 一写，`attempts >= handoff_count + 1`、`card_json` 派生列一致这两条就再也没有低成本补测的窗口。

**R3 · 契约卡 #2 的字段清单比计划少 4 项，其中 3 项是"以后加就要改契约版本"的**
- 依据：计划 §1.2⑦ 明确"`TaskCard.handoff_policy`——**在 PR-1 的契约里就要留位置**，否则阶段 5 加这个能力时要改契约版本"；#2 卡列的是 `budget_tokens/budget_usd/idempotency_key/worktree`，**无 `handoff_policy`**。另三处：M5 `can_write_own_output`、M7 前向引用校验、M16 `output_schema` 的 JSON 字符串化，均为评审点名"阶段 1 契约"的项。
- 建议动作：向 `worker-contracts` 补发这 4 项，明确"字段先占位、语义留到阶段 5"是允许的，但**契约版本一旦发布就不再改**。这一条若不纠，PR-1 的"一次定型"承诺当场失效。

**R4 · M10 已经分裂成两套说法（`idempotency_key` vs `queueing_lock`+`lock`）**
- 依据：计划 §1.2① 依据 procrastinate 的实测**修订**了 M10；`schema.py:148-150` 已按修订实现三列；#2 卡仍是单个 `idempotency_key`。
- 建议动作：由 #2 统一暴露 `queueing_lock` 与 `lock` 两个键（`idempotency_key` 要么删除、要么在注释里写死"= queueing_lock 的别名，仅为兼容"）。让契约与 schema 各说各话，等于在 PR-1 就埋下第五套真相源。

**R5 · 卡片验收被系统性弱化，主控复核时会失去判据**
- 依据：计划 §2 阶段 0 验收 = "测试能真正捕获漂移（**人为改错文档必须变红**）+ `delegate_tool.py` 仍 4965 行 + 运行期默认值零变化"；#1 卡只剩"新测试全绿，且不改变任何运行期默认值"。阶段 1 验收 = "契约 ≥15 / 状态机 ≥17（**含穷举**）/ config+schema ≥18"；#3 卡改为"分支覆盖 100%"，#4 卡改为"建表断言所有表/索引/CHECK 生效"。"分支覆盖 100%"在 `state_machine.py` 这种 `if` 分支表上是**比穷举更弱**的指标（覆盖到分支不等于覆盖到每条边的语义）。
- 建议动作：验收一律回抄计划原文口径；主控按 §3.4 自己重跑并比对用例数，不接受"看起来全绿"。

**R6 · 跨成员依赖的兜底没有定义，当前已处于 `ImportError` 中间态**
- 依据：计划 §3.2 只写"等待文件出现（最多重试 6 次 × 30s）"，**没写超时后怎么办**。实测 19:47 时 `agent/orchestration/contracts.py` 仍不存在，而 `state_machine.py:19` 已经 `from agent.orchestration.contracts import TERMINAL_STATES, TaskState` → 该模块此刻 import 即失败。
- 建议动作：给 `contracts.py` 一个硬截止时间；超时后 #3/#4 要么改为延迟导入（函数内 import）并显式标注 TODO，要么由主控临时接管枚举定义——**但绝不能允许各自复制一份枚举**（计划已明令禁止，且那是第五套真相源）。好消息是 #3 目前守住了这条线，用的是 import 而非复制。

**R7 · `lease_epoch` 与"租约挂 worker"两套机制并存，语义边界没写死**
- 依据：评审 B1 = 逐任务 `lease_epoch` 递增做 fencing；计划 §1.2① 又采纳 procrastinate 的"**租约应挂在 worker 上、任务继承**"；`schema.py:239-253` 已建 `workers.last_heartbeat`。两者不是替代关系：worker 级心跳只能决定"谁该被 reclaim"，**不能**阻止被 fence 的 worker 写回。
- 建议动作：在 schema/契约注释里写死一句"`lease_epoch` 逐任务递增、每次 claim +1、所有写回带 epoch 校验；`workers.last_heartbeat` 只用于判死与回收，不参与写权限判定"。否则阶段 2 的实现者很可能二选一，选掉 fencing。

**R8 · `attempts` 的零点未定义（`DEFAULT 1`）**
- 依据：`schema.py:137` `attempts INTEGER NOT NULL DEFAULT 1`；评审 M12 定义"`attempts` = 执行次数（含首次）"。任务入队尚未执行时，它是 0 还是 1？两种解释都能自圆其说，但会让 `attempts >= handoff_count + 1` 这条不变式在机检时得出相反结论。
- 建议动作：在 #4 的建表测试里钉死语义（建议：入队 = 0，claim 时 +1），并与 #3 的 `max_retries` 判据对齐。

---

## 评审自身的事实性错误

**硬错误：无。** 抽查了评审中可验证的 13 处断言，全部成立，包括容易出错的三处：

- `delegate_tool.py` 4965 行（评审说"差 1 行"）— 实测 `wc -l` = 4965 ✅
- "异步满载拒绝在 L910 是 docstring，真正分支在 L4370–4384" — 实测 L904–917 为 `_get_max_async_children` docstring（含 "REJECTED (not queued)"），L4367–4385 为回退同步执行分支 ✅
- "`_transaction` 记录了 fd 泄漏教训 L197–213" — 实测 `async_delegation.py:197-213` docstring 明写"`with conn:` 只提交不关闭" ✅
- `cancel()` 三条 `unsupported=True` 分支（`subagent_lifecycle.py:314/324/328`）、`_REGISTRY` L159 九态、`apply_durability_barriers` docstring（`fulilian_state.py:2923`）、`claim_completion_delivery` L494、`_handle_control_action` L466/L474、120 个测试文件 — 均与评审一致 ✅

**两处轻微不精确（不影响结论，建议下版顺手改）：**

1. `_recent_subagents` 实际在 `tools/delegate_tool.py:162`（容量常量 `_RECENT_SUBAGENTS_CAP = 200` 在 L161），评审 §1.2(c) 写"L166 起"，漂移 4 行。评审自己主张"行号引用应改符号引用"（§1.2b），这里正好自证一次。
2. 评审 §1.1 末行把 `_capability`（`agent/subagent_lifecycle.py:492`）与 `claim_completion_delivery`（`tools/async_delegation.py:494`）并列进"投递租约值得保留"。前者是 **handle 能力签名 HMAC**（`subagent_id|parent_session_id|created_at`），与投递无关。归类含混，不是事实错误，但会让读者误以为投递链路已有 HMAC 保护。

**一处覆盖遗漏（这条比错误更要紧，已直接导致任务卡范围不全）：**

- 评审 §1.2(a) 把"文档漂移"的核查收缩到 AGENTS.md 两处，**漏了 `tools/delegate_tool.py:4857` 与 `fulilian_cli/tips.py:132`** 这两处同样写"default 3"的地方。评审的结论"文档确已漂移"没错，但**漂移面的枚举不全**，于是计划 §2 阶段 0 只修 1 处代码注释，任务卡 #1 照抄。这正是"同一件事三种说法"在本轮修复里被复现了一次——建议把这条当作 R1 的根因记录在案。

---

# 第二阶段：产物审计

> 审计时点：2026-10-31 20:07（`contracts.py` / `state_machine.py` 在 20:04 仍在改动，以下结论以 20:07 复跑为准）。
> 审计原则：不采信任何自我报告，全部自己重跑、自己读代码、自己造变异。

## 最终判定

**有条件通过** —— 只有 1 个必修项（`schema.py` 的静默降级 fallback，见「阻塞项 B-1」，3 行即可修掉），修完即可进 PR。状态机、契约、schema、四源一致性测试均实测达标，且我做了变异探针验证「测试确实能失败」。

## 我实际做了什么（不复述汇报）

| 核验手段 | 结果 |
|---|---|
| 自己重跑 `tests/orchestration` + `tests/agent/test_delegation_config_contract.py` | **154 passed, 2 skipped, 1 xfailed**（1.88s）。主控报的是 150——差 4 是因为 `state_machine.py` / `contracts.py` 在 20:04 又新增 3 个用例；以本次 20:07 复跑为准 |
| 变异探针 4 组（就地改 `_ALLOWED` 后直接调测试函数） | **4/4 全部变红**：多加 `QUEUED→BLOCKED`、删 `BLOCKED→FAILED`、给 `SUCCEEDED` 加出边、整表清空，均被 `test_allowed_table_matches_spec_literal` 抓到 |
| 分层检查 `grep -rn "from tools\|import tools" agent/orchestration/` | **无输出** |
| 回归：主控改的 `tips.py` 文案 | `tests/fulilian_cli/fulilian_cli/test_tips.py` **6 passed**，无既有断言依赖旧文案 |

## 1 · 状态机逐条对照（权威规格 vs 实现 vs 测试字面量）

| 当前态 | 规格（主控给定） | `_ALLOWED` | 测试字面量 | 一致 |
|---|---|---|---|---|
| QUEUED | {CLAIMED, CANCELLED} | {CLAIMED, CANCELLED} | 同 | ✅ |
| CLAIMED | {RUNNING, QUEUED, FAILED} | {RUNNING, QUEUED, FAILED} | 同 | ✅ |
| RUNNING | {BLOCKED, SUCCEEDED, FAILED, INTERRUPTED, CANCELLED, QUEUED} | 六条全在 | 同 | ✅ |
| BLOCKED | {QUEUED, CANCELLED, FAILED} | {QUEUED, CANCELLED, FAILED} | 同 | ✅ |
| FAILED | {QUEUED} | {QUEUED} | 同 | ✅ |
| SUCCEEDED / INTERRUPTED / CANCELLED | {} | {} | 同 | ✅ |
| **QUEUED → BLOCKED** | **必须不存在** | **不存在** | **不存在** | ✅ |

- **字面量测试独立性**：`test_allowed_table_matches_spec_literal` 的 `expected` 是手抄的 `frozenset` 字面量（`tests/orchestration/test_state_machine.py:54-76`），不是 `from state_machine import _ALLOWED` 自比自；另有 `assert set(_ALLOWED) == set(TaskState)` 防止漏表态。**这是本轮最关键的防线，已确认有效**（见上表变异探针）。
- 唯一可忽略的脆弱点：该测试用 `from ... import _ALLOWED` 在导入时绑定对象，若有代码在运行时**重新赋值** `state_machine._ALLOWED`（而非就地修改），测试看不见。改源码必然重新导入，实际不构成风险，仅记录在案。

## 2 · 测试是否「能失败」

| 检查点 | 结论 |
|---|---|
| `test_allowed_table_matches_spec_literal` 独立于实现 | ✅ 硬编码字面量 + 变异探针 4/4 变红 |
| `test_delegation_config_contract.py` 覆盖 4 个漂移源 | ✅ AGENTS.md×2（L103-117）、`delegate_tool.py` schema 注释（L120-125）、`tips.py` 文案（L128-133），外加运行期取值函数两条（L151-159），**且每个解析器都配了「喂被改坏的样本」的反向自检**（L174-218），避免「解析器恒等」式自证 |
| `test_invariants.py` 的 xfail 是否 `strict=True` | ✅ 唯一一条 xfail 显式 `strict=True`（L90-97），并配套 `test_schema_currently_allows_terminal_without_completed_at` 反向断言——缺口被补上时两条会同时变红，不会静默留下过期 xfail |

## 3 · 分层

`grep` 无输出，`agent/orchestration/` 对 `tools.*` 零依赖 ✅。`tests/agent/test_delegation_config_contract.py` 里 import `tools.delegate_tool` 属测试侧，合规。

## 4 · 主控 3 处改动（当普通变更审）

| 改动 | 判定 | 依据 |
|---|---|---|
| `tools/delegate_tool.py:4857` 注释 "default 3"→"default 10" | ✅ 正确 | 与 `_DEFAULT_MAX_CONCURRENT_CHILDREN = 10`（L122）、`config_defaults.py:2069` 一致；且有 `test_delegate_tool_schema_comment_matches_code_constant` 守住 |
| `fulilian_cli/tips.py:132` "up to 3"→"up to 10" | ✅ 正确 | 同上；`test_tips.py` 6 passed 无回归 |
| `contracts.py` `TERMINAL_STATES` 注释 | ✅ 语义正确，⚠️ 轻微反向耦合 | 注释准确说明「终结 ≠ 无出边」（`FAILED` 仍在 `_ALLOWED` 里）；但 L70 写「判断有无出边请查 `state_machine._ALLOWED`」——契约层文档指向上层模块，虽无 import 循环，仍属文档层反向依赖，建议改成「请查状态机的转移表」（不点名） |

## 5 · 遗留缺口（2 skip + 1 xfail）是否诚实

| 项 | 原因 | 阶段归属 | 判定 |
|---|---|---|---|
| `test_attempts_gte_handoff_count_plus_one` | 两列存在但无写入方，只能构造人工数据（等于测测试自己） | 阶段 2 `store.claim` | ✅ 诚实，不是掩盖 |
| `test_derived_columns_match_card_json` | 无 insert 路径，`card_hash` 无人写 | 阶段 2 `store.insert` | ✅ 诚实 |
| `test_terminal_state_without_completed_at_is_rejected`（xfail strict） | schema 未强制「终态 ⇒ completed_at 非空」 | 现在就缺，补 CHECK 后自动转 XPASS 提醒 | ✅ 缺口被显式登记，且配了反向断言 |

**结论：没有「用 skip 掩盖没做」的情况。** 三条都写了「为什么现在不能测」和「什么时候能测」。

## 与第一阶段判定的变化

| 第一阶段风险 | 现状 | 说明 |
|---|---|---|
| R1 阶段 0 漂移面漏 2 处 | **已消除** | 4 个漂移源全部修好且被测试钉住；第一阶段「实测已发生」的漏改已被补上 |
| R2 `test_invariants.py` 无人认领 | **已消除** | 文件存在（207 行），5 条不变量齐全，2 skip + 1 xfail 均有阶段归属 |
| R3 契约卡漏 handoff_policy / M5 / M16 | **已消除** | `handoff_policy`（L164）、`can_write_own_output`（L191）、`output_schema` 强制 JSON 字符串（L149 + `validate_card` L267-276）全部落地，且有测试 |
| R6 跨成员依赖无兜底 | **已消除** | `contracts.py` 已落地，`state_machine.py` / `schema.py` 走 import 而非复制枚举 |
| R7 lease_epoch 语义边界 | **基本消除** | `TaskHandle.lease_epoch` 注释写明「每次写回都必须带上它」；schema 注释亦写「Every write-back must carry the epoch」。worker 心跳与 epoch 的分工建议阶段 2 补一句 |
| R4 M10 口径分裂 | **仍在** | `contracts.py:175` 仍只有 `idempotency_key`，而 `schema.py:148-150` 是 `idempotency_key`+`queueing_lock`+`lock` 三列。契约层没有表达「排队去重」与「运行互斥」两个键 |
| R5 验收口径弱化 | **已可接受** | 每个断言都能落到具体行为（IntegrityError、变异探针），不再是「看起来对」 |
| R8 `attempts` 零点 | **部分缓解** | `state_machine.py:17-27` 已写死「`attempts` 由 `store.claim()` 递增、状态机不负责」；但 schema `DEFAULT 1`（见 N3）仍与之语义不一致 |

## 新问题

**N1 · `block_reason` 是一个不存在的列（文档 ↔ schema 矛盾）**
`state_machine.py:31` 写「依赖失败的原因写进 `block_reason` 数据列」，但 `schema.py` 的 `tasks` 表没有 `block_reason`（只有 `error`，`schema.py:175`）。阶段 2 实现者会照着文档找列、找不到，然后要么加列（schema v2 churn）、要么静默改用 `error`——两条路都会让「依赖失败」和「执行失败」混在一起。
→ 建议：文档改成 `error`（或约定 `error` 里 `dependency_failed:` 前缀），二者择一写死。

**N2 · 「租约过期」在同一个 docstring 里指向两个不同目标态**
`state_machine.py:9` 说 `RUNNING -> QUEUED` 的守卫是 `lease_expired=True`（判死回收）；`state_machine.py:40` 又说「`RUNNING` 租约过期 → `BLOCKED` → 可 redispatch」。两条边在表里都存在，所以状态机允许两种走法，但**没有一句话说明什么时候用哪条**。阶段 4 的 `patrol()` 会二选一，选错就是「任务被回收但没记录原因」或「BLOCKED 堆积无人重派」。
→ 建议：补一句分工（例如 inline 快路径直接 `QUEUED`；需留痕/需人工决策走 `BLOCKED`）。

**N3 · 两处默认值不一致（同一字段两个默认）**
- `contracts.py:159` `tier: TaskTier = TaskTier.T2`（=2），而 `schema.py:139` `tier INTEGER NOT NULL DEFAULT 3`。若某条插入路径漏写 `tier`，落库值是 T3，与卡片声明的 T2 不符。
- `schema.py:152` `tasks.attempts DEFAULT 1`，而 `schema.py:225` `deliveries.attempts DEFAULT 0`；结合 M12「attempts = 执行次数（含首次）」，任务入队尚未执行时记 1 是「预支了一次执行」。
→ 建议：`tier` 默认值二选一；`attempts` 明确「入队 0、claim +1」（与 `state_machine.py:19` 的说法对齐）。

**N4 · 契约层注释反向指向状态机**
见 §4 第 3 行。非阻塞，一句话可改。

## 不能进 PR 的阻塞项

**B-1 · `schema.py` 保留了一条「静默降级」的重复枚举路径**

- **证据**：`schema.py:64-81` 定义 `_FALLBACK_TASK_STATES` / `_FALLBACK_TERMINAL_STATES`（与 `contracts.TaskState` 重复的字面量）；`schema.py:102-106` 用 `except Exception` 捕获后静默回退；`schema.py:117` 在**模块导入时**就把结果固化成 `TASK_STATES`。对应的守卫测试 `tests/orchestration/test_schema.py:161-165` 在 import 失败时是 `pytest.skip`，**即这条路径永远测不出来**。
- **后果**：`contracts.py` 一旦因任何原因 import 失败（重构中途、循环 import、`TERMINAL_STATES` 改名），`apply_schema()` 会用这份字面量建库、写入 `schema_version=1`，**不报任何错**。阶段 2 在这套库上跑，CHECK 约束与实际枚举不一致，现场无迹可循——这正是评审 M9 说的「静默失败」，也正是本次改造要消灭的「多套真相源」。
- **为什么算阻塞而不是瑕疵**：这个 PR 的唯一价值主张就是「收敛真相源」。在收敛动作里内嵌一份带静默回退的副本，等于把被修的病原样搬进修复本身。而且它当前是**死代码**（`contracts.py` 已落地，正常路径不会走到），留着只有风险没有收益。
- **修复**（3 行）：删掉两个 `_FALLBACK_*` 常量与 `try/except`，让 `ImportError` 直接冒泡；同时把 `test_schema.py:161-165` 的 `except Exception: pytest.skip(...)` 改成失败断言。若坚持保留 fallback，则必须 `raise SchemaError(...) from exc`，不允许静默。

## 一句话

**状态机与测试的质量超出预期——「字面量钉表 + 穷举 + 反向断言」三层防线，我用 4 组变异探针验证过确实能失败，这是本轮最值得保留的资产；唯一拦路的是 `schema.py` 里那条静默回退的重复枚举，它把本次要消灭的问题原样搬回了修复本身，删掉即可进 PR。**

## 第一阶段矩阵更正（20:09，以此为准）

产物已落地，下列行的旧标注作废：

- M5 can_write_own_output：✗ → 已落地（contracts.py:191，WorkerCapability 已拆分两个能力位）
- M16 output_schema 哈希陷阱：✗ → 已落地（contracts.py:149 强制 JSON 字符串，validate_card 校验）
- §6.3 test_invariants.py 骨架：✗ → 已落地（207 行，5 条不变量，2 skip + 1 xfail 均有阶段归属）
- M2 supervisor depth：✗ → 字段已落地（TaskCard.depth），父子树语义留阶段 4
- M7 depends_on 前向引用：✗ → 行为上已允许（validate_card 不校验引用存在性），批次级整体校验留阶段 2
- M1 pools 不变式：○ → 已落地（config.pools + warnings() + test_invariants 已钉住）

其余 ✗/○ 行不变：B1 的 fenced 产物作废契约、B3 的 tool description 语义降级仍未归属。
