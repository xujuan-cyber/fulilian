# 子智能体编排子系统 · 开源实现调研与分阶段实施计划

> 前置文档：`docs/design/orchestration-plan-review-2026-10-31.md`（评审意见，含 B1–B3 / H1–H8 / M1–M18）
> 调研时间：2026-10-31；数据来源：GitHub API 实时查询（`gh api`），星数与推送时间均为当日快照。
> 本文回答三件事：① 有没有能直接用的开源实现；② 分几个阶段做、每阶段验收什么；③ 派给谁、怎么判合格。

---

## 1. 开源实现调研

### 1.1 候选清单（按"与我们的问题距离"排序）

| 项目 | 星数 | 许可 | 最后推送 | 它解决什么 | 与 Fulilian 的距离 |
|---|---|---|---|---|---|
| `riverqueue/river` | 5.8k | **MPL-2.0** | 2026-10-31 | Postgres 上的作业队列，含状态机、唯一作业、可恢复作业、事务内完成 | **设计最近**：状态机与重试语义几乎同构 |
| `procrastinate-org/procrastinate` | 1.4k | MIT | 2026-10-31 | Python + Postgres 任务队列，LISTEN/NOTIFY 唤醒、worker 心跳、事件表 | **机制最近**：stalled 检测、保留策略、双锁键 |
| `dbos-inc/dbos-transact-py` | 1.7k | MIT | 2026-10-30 | 数据库支撑的持久化工作流，step 级幂等重放 | 语义最近，但侵入性最强 |
| `janbjorge/pgqueuer` | 1.5k | MIT | 2026-10-29 | Postgres 队列，`FOR UPDATE SKIP LOCKED` | 只借"原子领取"的形态 |
| `temporalio/sdk-python` | 1.2k | MIT | 2026-10-30 | 持久化执行引擎 SDK，activity heartbeat / retry policy | 需自带 server，过重 |
| `coleifer/huey` | 6.1k | MIT | 2026-10-24 | 轻量 Python 任务队列，**支持 SQLite 后端** | **最接近形态，但能力不足**（无反租约/fencing） |
| `langchain-ai/langgraph` | 44.2k | MIT | 2026-10-31 | 图式 agent 编排 + checkpointer | 借 checkpoint 数据模型 |
| `openai/openai-agents-python` | 30.4k | MIT | 2026-10-30 | handoffs / agents-as-tools 两种多智能体语义 | 借语义划分，不借实现 |
| `OpenHands/OpenHands` | 92.3k | MIT | 2026-10-31 | 编码 agent，容器化 runtime | 印证"子进程 ≠ 沙箱" |
| `microsoft/agent-framework` | 14.4k | MIT | 2026-10-30 | 多智能体工作流 + checkpoint | 参考价值中等 |
| `ruvnet/ruflo`（原 claude-flow） | 80.4k | MIT | 2026-10-31 | prompt 级 swarm 编排 | **反例**：无持久化保证 |

### 1.2 逐项适用性评估

#### ① procrastinate —— 机制层面最有价值的参照

我读了它的 `procrastinate/sql/queries.sql`（`gh api` 拉取原文），有三处直接对应我们评审里的判断：

- **`select_stalled_jobs_by_heartbeat`**：从 `procrastinate_workers.last_heartbeat` 判死，而不是逐任务租约。
  → 印证评审 §4.4 的"空转/僵尸"规则，但也提示一个改进：**租约应挂在 worker 上，任务继承**，比每任务一个 `lease_expires` 写放大更小（15 worker × 每任务续租 vs 15 worker × 每 worker 续租）。
- **`select_stalled_jobs_by_started`**：`started_at` 不是列，而是从 `procrastinate_events` 里 `type='started'` 的事件算出来的。
  → 这是 event sourcing 的做法：**状态由事件流推导，而非可变列**。我们的 `tasks.started_at` 是可变列，一旦被覆盖就丢了历史；建议 `events` 表成为 `started_at/completed_at` 的真相源，`tasks` 上的同名列只作缓存（并在文档里标注）。
- **`delete_old_jobs`**：保留策略是一等公民，写在 SQL 里而不是"以后再说"。
  → 直接印证评审 M8：`events`/`dispatch_log` 必须有 TTL，否则单机 SQLite 会被日志撑爆。
- 另外它有 **`lock` 与 `queueing_lock` 两个键**：前者是"运行期互斥"，后者是"排队期去重"。
  → 这比我评审里 M10 的单个 `idempotency_key` 更精确。**修订 M10：拆成 `queueing_lock`（排队去重）与 `lock`（运行互斥）两个键。**

#### ② river —— 状态机与"可恢复作业"值得直接抄

- 状态集（available / running / completed / retryable / discarded / cancelled / scheduled）与我们的 QUEUED/RUNNING/SUCCEEDED/FAILED(→retry)/CANCELLED 基本一一对应，说明方案 §4.2 的转移表方向没错。
- **`resumable jobs`**（`js/docs/resumable-jobs.md` 原文）：*"when an attempt fails or snoozes, River records the last completed step in the job's metadata, and the next attempt skips every step up to and including it"*。
  → 这是对 Anthropic "子代理失败后难以恢复"的工程解法。**我们的 `redispatch` 目前是"整份重跑"，应加 `cursor_json`，让重派从断点续跑。** 这是本次调研里对方案最有价值的一条新增。
- `job_complete_tx.go`：允许在调用方事务内完成任务（避免"做完了但状态没落"的窗口）。
  → 对应我们的 `RUNNING → SUCCEEDED` 写回，应与产出落盘在同一事务边界内考虑。

#### ③ dbos-transact —— 幂等模型可借，框架不可借

DBOS 的 `workflow_id + step_id` 复合键是"至多一次"的经典实现：重放时已完成的 step 直接返回缓存结果。我们的 `lease_epoch` 解决的是"谁有资格写"，DBOS 解决的是"重放时不要重做"——**两者互补，不重叠**。结论：不引入 DBOS，但 `cursor_json` + `lease_epoch` 的组合正是它这两个机制的轻量版。

#### ④ huey —— 最接近形态，恰好是最有说服力的反例

huey 有 SQLite 后端（`SqliteStorage`），是"单机 Python + SQLite 队列"最成熟的实现。但它**没有**：租约、fencing、worker 心跳判死、多进程安全领取（它的 SQLite 后端在多进程下靠表锁，吞吐很差）。

结论：**这说明"用 SQLite 做队列"本身不是问题，问题是 huey 的定位是轻量后台任务，不是需要崩溃恢复的编排。** 我们要的保证比它高一档，所以必须自己写 store 层——但可以把 huey 当作"最小可用基线"，凡是比它更复杂的设计都要问一句"这个复杂度换来了什么保证"。

#### ⑤ pgqueuer / procrastinate / river —— 都要 Postgres

三者的原子领取都依赖 Postgres 特性（`FOR UPDATE SKIP LOCKED` / advisory lock / `LISTEN/NOTIFY`）。SQLite 没有对应物，只能用 `BEGIN IMMEDIATE` + CAS 模拟。这**反向印证**了评审 H2 的判断：SQLite 没有 LISTEN/NOTIFY，所以"push 通知"必须自己造（轮询退避，或进程内条件变量 + 跨进程侧信道）。

#### ⑥ langgraph —— checkpoint 模型值得借

`SqliteSaver` 的 checkpoint 是**追加写 + parent_checkpoint_id 指针**，支持 time-travel 与分支。对比我们的 `tasks` 单行可变状态：单行更新的问题是"看不到中间态"。建议（不进 PR-1，进阶段 4）：`events` 表承担 checkpoint 角色，`tasks` 只存"最新快照"，需要回放时从事件重建。

#### ⑦ openai-agents-python —— 借语义，不借代码

`handoffs`（移交控制权，父不再管）vs `agents-as-tools`（父保持控制权）。方案 §9 已经识别到"现状属 agents-as-tools，runtime 应同时支持两种"。这一条**在 PR-1 的契约里就要留位置**：`TaskCard.role` 只有 leaf/orchestrator 两档，无法表达 handoff。建议在 `TaskCard` 加 `handoff_policy: Literal["tool","handoff"] = "tool"`——否则阶段 5 加这个能力时要改契约版本。

#### ⑧ OpenHands —— 印证"子进程不是沙箱"

OpenHands 的 runtime 是容器化的，不是 `subprocess`。这与评审 H6 的判断一致：**进程隔离只解决"崩溃不拖垮主进程"，不解决"恶意输入"**。取证场景解析畸形样本，若要真隔离必须上容器/gVisor。这一条要在阶段 5 的文档里写死，避免有人误以为 `subprocess` 就够了。

#### ⑨ ruflo（claude-flow，80k★）—— 明确不采纳

它是 prompt 层的 swarm 编排（hive-mind、queen/worker 提示词），没有持久化状态机、没有租约、没有崩溃恢复。星数高是因为它解决的是"让多个 LLM 角色对话"，不是"保证任务在进程崩溃后不丢"。**照抄它会得到一个看起来热闹、但一断电就全丢的系统。**

### 1.3 采纳决策

**结论：不引入任何运行时依赖，只借设计。**

四条理由，按权重排序：

1. **侵入性**。Temporal/DBOS 要求把 agent 循环改写成 workflow/step 函数，等于重写 `run_conversation`。而本项目的目标是"收敛真相源"，不是"换框架"——换框架会把 9–11 周的改造变成 6 个月的重写。
2. **形态不匹配**。所有成熟实现都假设有一个常驻 worker 集群 + 一个网络可达的数据库。Fulilian 是单机 CLI（一次调用一个进程）+ 可选 gateway。评审 H1 已经指出"worker 由谁拉起"是空白——引入外部框架并不能回答这个问题，反而多一层部署依赖。
3. **Python 生态缺位**。想要"SQLite + 租约 + fencing + 多进程"，Python 里没有现成实现：`procrastinate`/`pgqueuer` 要 Postgres，`huey` 没有租约与崩溃恢复。既然都要自己写 store 层，就不如按自己的状态机写。
4. **许可与维护**。river 是 MPL-2.0（文件级 copyleft），若真要移植代码需评估；其余虽为 MIT，但把 5k 行的 Go 逻辑翻译成 Python 的维护成本高于自研。

**具体借了什么（写进 PR 的注释里，注明出处）：**

| 借用点 | 来源 | 落到哪 |
|---|---|---|
| `queueing_lock` + `lock` 双键 | procrastinate | `schema.tasks` 两列（修订 M10） |
| worker 心跳判死（而非逐任务租约） | procrastinate | `workers.last_heartbeat` + `patrol()` |
| `cursor_json` 断点续跑 | river `resumable jobs` | `tasks.cursor_json`（新增，H4 之外的补充） |
| 保留策略作为一等公民 | procrastinate `delete_old_jobs` | `events`/`dispatch_log` TTL（M8） |
| 状态由事件推导 | procrastinate `events` | 阶段 4 的 `started_at` 真相源改造 |
| `handoff_policy` 两档语义 | openai-agents | `TaskCard.handoff_policy`（契约预留） |
| 容器而非子进程才是真隔离 | OpenHands | 阶段 5 文档的边界声明 |

---

## 2. 分阶段实施计划

阶段划分沿用评审 §6.1 的 7 阶段（已把"进程隔离"独立并后置为灰度项）。每阶段给出：产出、验收（可机检）、依赖、风险。

### 阶段 0 · 止血（0.5–1 天）

| 项 | 内容 |
|---|---|
| 产出 | `AGENTS.md` 两处默认值修正；`delegate_tool.py` L3708 注释修正；`tests/agent/test_delegation_config_contract.py` |
| 验收 | 新测试全绿；测试能真正捕获漂移（人为改错文档必须变红）；`delegate_tool.py` 仍 4965 行；运行期默认值零变化 |
| 依赖 | 无 |
| 风险 | 极低。唯一风险是 9p 上编辑大文件丢内容 → 强制单次 Edit + 事后 `wc -l` |

### 阶段 1 · 契约层（1 周）

| 项 | 内容 |
|---|---|
| 产出 | `agent/orchestration/{__init__,contracts,state_machine,config,schema}.py` + 三套测试 |
| 验收 | 契约测试 ≥15、状态机测试 ≥17（含穷举）、config/schema 测试 ≥18；`agent/orchestration/` 对 `tools.*` 零 import；内存库建表后 CHECK 约束与部分唯一索引真实生效 |
| 依赖 | 无（纯新增，无调用方） |
| 风险 | 低。风险在"schema 一次没定全，阶段 2 返工" → 本阶段把 B1/B2/B3 的字段全部前置 |

### 阶段 2 · 存储与领取（2 周）

| 项 | 内容 |
|---|---|
| 产出 | `store.py`（CAS 领取 + 租约 + fencing 校验 + 先读后写 + 退避）、迁移 runner、多进程压测脚本 |
| 验收 | ① N=8 进程抢同一批任务，成功数恰为 1；② 被 fence 的 worker 写回必须失败（rowcount=0）；③ 空队列 15 worker 运行 10 分钟，写事务数 < 100；④ kill -9 后重启可接管 |
| 依赖 | 阶段 1 |
| 风险 | 中。写放大是主要风险 → 验收③是硬指标 |

### 阶段 3 · 派发与控制通道（2 周）

| 项 | 内容 |
|---|---|
| 产出 | `dispatcher.py`（batch sampling + 退避）、worker 三档承载（inline/embedded/daemon）、`control.py`（list/steer/stop 跨进程） |
| 验收 | 现有 120 个 delegation 测试全绿；`action=list` 能列出另一进程启动的子代理；`steer` 在 1 个 heartbeat 周期内生效；daemon 空闲 30 分钟自动退出 |
| 依赖 | 阶段 2 |
| 风险 | **最高**。B3 是方案原有空白，控制通道要与现有 TUI/gateway 对齐 |

### 阶段 4 · 监督与修正（2 周）

| 项 | 内容 |
|---|---|
| 产出 | `supervisor.py`（先只硬约束）、`redispatch.py`（含 `cursor_json` 续跑、`route_fingerprint`、换路线豁免） |
| 验收 | 僵尸可判定；转手上限生效；换路线豁免生效；`events` TTL 生效；误报三指标（精确率/可行动率/重复率）达标 |
| 依赖 | 阶段 3 |
| 风险 | 中。误报会摧毁信任 → 两阶段上线，先只告警不裁决 |

### 阶段 5 · 进程隔离（1 周，feature flag）

| 项 | 内容 |
|---|---|
| 产出 | `ProcessReaper`（Linux: `start_new_session` + `killpg`；Windows: Job Object）、`spawn`/`forkserver` 强制、灰度开关 |
| 验收 | 强制杀进程树无孤儿；fenced worker 产物作废；Windows 上孙进程可回收 |
| 依赖 | 阶段 3 |
| 风险 | 中高。平台差异 + fork/线程陷阱 → 必须先文档化"不提供安全隔离" |

### 阶段 6 · 组织与聚合（1–2 周）

| 项 | 内容 |
|---|---|
| 产出 | `organizer.py`（能力位、命名、编制）、`aggregator.py`（归并、预算、冲突裁决） |
| 验收 | 细粒度策略可声明生效；`sum(pools) <= max_running` 校验生效；编制按可并行资源数而非任务数 |
| 依赖 | 阶段 4 |
| 风险 | 中 |

### 阶段 7 · 清理（1 周）

| 项 | 内容 |
|---|---|
| 产出 | 删除 `_active_subagents` / `_recent_subagents` / `_REGISTRY`；去掉 `agent/` 对 `tools.delegate_tool` 私有符号的 import |
| 验收 | `grep -rn "from tools.delegate_tool import _" agent/` 无输出；全量测试绿 |
| 依赖 | 阶段 6 |
| 风险 | 低，但删除面广 → 分 3 个小 PR |

> ### 已撤销（2026-11-01）：上表"删除三个符号"一项全部作废
>
> 上表"产出"栏假定 `_active_subagents` / `_recent_subagents` / `_REGISTRY` 是死代码。**实测三个都是活代码**，删除会造成功能静默降级。裁定与完整证据见 `docs/design/orchestration-phase7-decisions.md`。
>
> | 计划项 | 实际归属 | 引用 | 裁定 |
> |---|---|---|---|
> | `_active_subagents` | `tools/delegate_tool.py`（`_active_subagents_lock` 保护的活跃记录表） | 4 处以上：写入 / 读取 / 清理 | **不删** |
> | `_recent_subagents` | `tools/delegate_tool.py`（`_RECENT_SUBAGENTS_CAP = 200` 的有界 FIFO） | 5 处：写入 / 读取 / 裁剪 | **不删** |
> | `_REGISTRY` | `agent/subagent_lifecycle.py` | **19 处** | **不删** |
>
> `tools/delegate_tool.py` 里**根本没有** `_REGISTRY`（`grep -c` = 0）——上表把 `subagent_lifecycle` 的核心注册表与 `delegate_tool` 的活跃记录表混为一谈了。
>
> 不能删的三条证据：
>
> 1. **`_active_subagents` + `_recent_subagents` 支撑一个活功能。** 二者共同实现 `get_subagent_attribution()`（`tools/delegate_tool.py`：先查活跃表，再查保留表）。调用方真实存在：`tools/process_registry.py` 中 `from tools.delegate_tool import get_subagent_attribution` 与 `info = get_subagent_attribution(task_id)`。子代理起的后台进程（如带 `notify_on_complete=true` 的 `npm ci`）经常活过子代理本身，其完成通知要回到父会话，并且必须知道"这是哪个委派起的"。删掉保留表，这条归属就丢了——通知仍然会发，只是从"由 subagent `sa-xxx`（目标：……，委派 id：……）启动"退化成"由 subagent `sa-xxx` 启动"。这正是本项目反复出现的失败模式：**功能静默降级，而测试照旧全绿。**
> 2. **`_REGISTRY` 是 `subagent_lifecycle` 的核心存储。** 19 处引用，持有 `_Record`（handle / state / future / result），是终态保留与重连的唯一来源。删掉它，整个模块失效。
> 3. **错误计划比没有计划更危险。** 本段存在的唯一目的，是阻止下一个人照着旧计划再删一次。带着"经过评审"权威的错误计划，破坏力大于一份空计划。
>
> **同时更正上表对覆盖率的判断。** 归属功能此前并非零覆盖：`tests/tools/test_delegate_control_actions.py` 已有 `test_attribution_resolves_live_child`、`test_attribution_survives_child_completion`、`test_attribution_unknown_task_id_is_none`。但这份覆盖埋在控制面测试文件里，从文件名看不出归属契约的存在，因此阶段 7 另建独立文件 `tests/tools/test_subagent_attribution.py` 作为该契约的锚点。
>
> **本阶段实际执行的三项**：
>
> ① **清理私有 import。** 在 `tools/delegate_tool.py` 增两个公开**包装函数**，`agent/subagent_lifecycle.py` 改用它们（**不重命名**原函数，避免波及 `delegate_tool` 内部全部调用点）：
>
> | 私有原函数 | 公开包装 | 调用方 |
> |---|---|---|
> | `_run_child_lifecycle` | `run_child_lifecycle` | `_SubagentRuntime._run` |
> | `_build_child_preserving_parent_tools` | `build_child_preserving_parent_tools` | `SubagentLifecycleService.spawn` |
>
> ② **把验收从 grep 换成 AST。** 原验收 `grep -rn "from tools.delegate_tool import _" agent/` 可被多行 import 绕过——`agent/subagent_lifecycle.py` 里正藏着 `from tools.delegate_tool import (\n _build_child_preserving_parent_tools, ... )`，下划线在下一行，grep 抓不到；而这段 import 上方两行的注释还写着"plugin code never imports private delegation helpers"。注释与代码相反，比没有注释更糟。新验收：`tests/tools/test_private_import_guard.py`，用 `ast.ImportFrom` 遍历 `agent/` 下全部 `.py`。
>
> ③ **补归属测试。** `tests/tools/test_subagent_attribution.py`。
>
> ⚠️ **实现陷阱（已踩并修复，后续不要再犯）**：公开名最初写成模块级别名 `run_child_lifecycle = _run_child_lifecycle`，结果 `tests/run_agent/test_sequential_tool_timeout.py` 的 `monkeypatch.setattr("tools.delegate_tool._run_child_lifecycle", ...)` 静默失效——别名在 import 时就绑定了函数对象，之后替换 `_run_child_lifecycle` 不再影响它，真实子代理生命周期被跑起来，测试变红。改为**调用时解析的包装函数**后恢复：包装函数体内引用模块全局 `_run_child_lifecycle`，每次调用重新查字典，monkeypatch 点继续生效。跨模块契约若用模块级别名实现，必须确认没有调用方依赖对原名的 patch。

**总计 10–12 周。** 关键路径：阶段 1 → 2 → 3 → 4 → 6 → 7；阶段 5 可与 4 并行。

---

## 3. 本次执行范围与派发记录

### 3.1 为什么只做 PR-1

阶段 2 之后的所有工作都依赖"引擎自己跑起来才能验证"（多进程抢任务、控制通道、进程树回收），无法在单轮会话里闭环。而**阶段 0 + 阶段 1 恰好是方案自己定义的"第一个 PR"**：纯新增 + 零调用方 + 可独立回滚。所以本轮把 PR-1 做完整、做到可验收，阶段 2–7 以计划形式交付。

### 3.2 派发表

| 任务 | 负责成员 | 产出 | 状态 |
|---|---|---|---|
| #1 Phase 0 止血 | `worker-contracts` | `AGENTS.md`、`delegate_tool.py` 注释、`tests/agent/test_delegation_config_contract.py` | 派发中 |
| #2 Phase 1a 契约 | `worker-contracts` | `contracts.py` + 15 测试 | 派发中 |
| #3 Phase 1b 状态机 | `worker-statemachine` | `state_machine.py` + 17 测试 | 派发中 |
| #4 Phase 1c 配置与 schema | `worker-store` | `config.py`、`schema.py` + 18 测试 | 派发中 |
| #5 独立监督 | `supervisor` | `notes/orchestration-supervision-01.md` | 派发中 |

**边界设计（防止并行踩踏）**：三人文件集互不相交——`worker-contracts` 只碰 `AGENTS.md`/`delegate_tool.py`/`agent/orchestration/contracts.py`；`worker-statemachine` 只碰 `state_machine.py`；`worker-store` 只碰 `config.py`/`schema.py`。测试目录共享 `tests/orchestration/`，但文件名不同，且各自只创建自己那一个。

**跨成员依赖的处理**：`state_machine.py` 与 `schema.py` 都要引用 `contracts.py` 的枚举，而 contracts 由另一个成员创建。已约定：等待文件出现（最多重试 6 次 × 30s），**禁止各自复制一份枚举**——那会立刻造出第五套真相源，正是本次改造要消灭的东西。

### 3.3 监督机制

按方案 §4.6 的定位，`supervisor` 是"引擎生成的任务卡"的人工等价物：

- **只读**：除自己的 `notes/orchestration-supervision-01.md` 外不得改任何文件；
- **只建议不执行**：不直接给 worker 发指令，只向主控报告，由主控决定是否纠偏；
- **两阶段**：先做静态审计（计划→任务卡→产出的映射、覆盖度矩阵、偏离风险），worker 交付后再做产物审计；
- **可审计监督员本身**：它的判定要落到固定结构的文档里（判定档位 / 覆盖度矩阵 / 偏离风险 / 评审自身错误），主控可以逐条复核，而不是只收一句"看起来没问题"。

### 3.4 主控验收方式

不看成员的自我报告，只看三样东西：

1. **文件是否真的存在且内容符合契约**（读文件，不读汇报）；
2. **测试是否真的跑了**（主控自己重跑一遍，比对用例数）；
3. **分层是否真的没破**（`grep` 检查 `agent/orchestration/` 对 `tools.*` 的 import）。

三者任一不成立，即判返工——这与方案 §7 的验收标准口径一致：**证据在目标侧，不在汇报里。**
