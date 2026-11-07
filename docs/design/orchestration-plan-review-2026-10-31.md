# 《Fulilian 子智能体编排子系统 · 最终改造方案》评审意见

> 评审基线：`xujuan-cyber/fulilian`，本地分支 `ctf-opt`（HEAD `2199266`），2026-10-31。
> 评审方式：逐条核对方案中的事实性断言（读源码验证），再对照多智能体系统与分布式调度的公开文献给出修改建议。
> 结论口径：**方向正确，可以立项；但当前版本不宜直接进入实施**——有 3 个阻断级缺陷、8 个高优缺陷，需在阶段 1 的契约里一次性改掉，否则阶段 3 切换点会返工。

---

## 0. 总体判断

方案的核心洞察是准确的，而且是对的：

> 问题不在能力缺失，而在「同一件事有三种说法」。

这一句诊断成立，且证据充分（见 §1）。把状态搬进数据库、把调度改成 pull、把监督下沉为规则，这三条方向也与工程界的主流结论一致（Sparrow 的 pull + 批量采样、Temporal/DBOS 的 durable execution、SRE 的"只对可行动的症状告警"）。

但方案在三个地方把"正确的方向"执行成了"不完整的机制"：

| # | 缺陷 | 后果 | 严重度 |
|---|---|---|---|
| B1 | 租约只有过期时间，**没有 fencing token** | 被判定死亡的 worker 复活后仍能写回结果，覆盖新持有人的产出 | 阻断 |
| B2 | 把 `async_delegations` **合并进 `tasks`** | 执行状态与投递状态耦合，at-least-once 投递语义（现状最成熟的部分）被拆散 | 阻断 |
| B3 | 进程化之后 **`action=list/steer/stop` 无实现路径** | 控制面失效，`steer` 无法跨进程注入；方案对此完全未提 | 阻断 |

另外有一处事实性错误必须在阶段 0 修掉：方案写的 `PRAGMA journal_mode = WAL` 与本仓库既有约束**直接冲突**（§1.3）。

---

## 1. 事实核对

### 1.1 核对通过的断言

| 方案断言 | 实测 | 结论 |
|---|---|---|
| `delegate_tool.py` 4964 行 / 221KB | **4965 行** | 属实（差 1 行） |
| `async_delegation.py` 1638 行 | 1638 行 | 属实 |
| `subagent_lifecycle.py` 552 行 | 552 行 | 属实 |
| `_run_single_child` 947 行（L2460–3407） | L2461–3407，947 行 | 属实 |
| `_active_subagents` 进程内 dict + Lock | `delegate_tool.py` L150 附近 | 属实 |
| `subagent_lifecycle._REGISTRY` 九态枚举 | `_REGISTRY` L159，`SubagentState` 九态（含 `CANCEL_REQUESTED`/`UNKNOWN`） | 属实 |
| `async_delegations` 表 L158–179 | 一致 | 属实 |
| `_DEFAULT_MAX_CONCURRENT_CHILDREN = 10`（L122） | 一致 | 属实 |
| `MAX_DEPTH = 1`（L129） | 一致 | 属实 |
| AGENTS.md L1135 "default 3" / L1144 "default 2" | 一致 | 属实，**文档确已漂移** |
| `cancel()` 置 `CANCEL_REQUESTED` 但底层不支持 | L302–332，三条 `unsupported=True` 分支仍返回 `CANCEL_REQUESTED` | 属实 |
| `action=list` 只查 delegate 侧 | `_handle_control_action` L466，只读 `_active_subagents`，且按 `_owns_subagent_record` 过滤 | 属实 |
| 投递租约 / 僵尸判定 / HMAC 值得保留 | `claim_completion_delivery` L494、`owner_pid`+`owner_started_at`、`_capability` L492 | 属实 |
| `_transaction` 记录了 fd 泄漏教训 | L197–213，注释明确写 `with conn:` 只提交不关闭 | 属实 |

### 1.2 需要修正的断言

**(a) "80 个引用 delegation 的测试文件" → 实测 120 个。**
`grep -rl "delegate_task\|delegation" tests --include=*.py` 命中 120 个文件。这直接影响 §7 的验收成本估算：阶段 3 的回归面比方案预估大 50%，"80 个全绿"这条验收标准应改为 120 个。

**(b) 行号漂移。** 方案称异步满载拒绝在 `L910`，实际 L910 是 `_get_max_async_children` 的 docstring（"REJECTED (not queued)"），真正的拒绝与回退分支在 **L4370–4384**。这类漂移说明文档的行号来自阅读记忆而非重新 grep——建议阶段 0 的"文档/代码一致性断言测试"把行号引用也纳入校验，或干脆改成符号引用（函数名 + 常量名），避免下次重构再次失效。

**(c) 方案称"三套状态真相源"，实际是"三套 + 一个被忽略的第四套"。**
`_recent_subagents`（L166 起，FIFO 容量 200）也是一套进程内状态，承担"子代理已结束但后台进程还在跑"的归属查询。它在 `get_subagent_attribution()` 里与 `_active_subagents` 并列被查。方案 §5 的映射表只写了删除 `_active_subagents`，没提 `_recent_subagents`——迁移时这会变成一个悬空引用（`ProcessSession.task_id` 的归属解析会静默返回 None）。**需要在映射表补一行：`_recent_subagents` → `tasks` 的终态记录（含 `completed_at` 保留窗口）**。

### 1.3 事实性错误（必须在阶段 0 修）

方案 §4.3 写：

```sql
PRAGMA journal_mode = WAL;
```

但本仓库对 `state.db` 的既有约定是**恰好相反**的。`tools/async_delegation.py` L145–155 的注释：

> `state.db`'s owning SessionDB connection establishes the configured journal mode. This secondary durability ledger must preserve that mode: applying WAL here on every short-lived connection requires an exclusive lock when the file is not already WAL and can collide with live transcript/FTS writers.

而 `fulilian_state.py:2923` 的 `apply_durability_barriers()` docstring 更是把这条写成了 API 契约：

> Apply state-store durability barriers **without changing journal mode**.

即：`state.db` 的 journal mode 由 SessionDB 单一所有者决定，任何 guest 连接**不得**改。方案若照抄 `PRAGMA journal_mode = WAL`，在 DELETE 模式的部署上会每次连接都尝试获取排他锁，与 transcript/FTS 写入方冲突——这正是现状注释里已经踩过的坑。

**修改建议（二选一，推荐前者）：**

1. **队列独立建库** `~/.fulilian/orchestration.db`，由编排子系统自己持有并显式设 WAL。好处不止是避开这条约束：`state.db` 是多读单写，transcript/FTS 已经在写；把每秒数十次的 claim/heartbeat 写事务塞进同一个文件，会让 transcript 写入排队。**这是独立于 PRAGMA 问题的第二个理由。**
2. 若坚持复用 `state.db`，则必须调 `apply_durability_barriers(conn)` 而非直接 PRAGMA，并接受与 transcript 争用写锁。

我建议方案 §4.3 明确写死方案 1，并把"独立库"作为架构决策记录下来（理由：写路径隔离 + 便于单独备份/清理 + 便于将来换 Postgres 时只迁一个文件）。

---

## 2. 阻断级缺陷

### B1 · 租约有到期时间，没有 fencing token

**问题。** 方案 §4.3 的原子领取写的是：

```sql
UPDATE tasks SET state='CLAIMED', claimed_by=:worker, lease_expires=:now+:lease ...
```

schema 里**没有 epoch / fencing token / version 列**。于是存在这个序列：

```
t0  worker A claim  T1，lease_expires = t0+60
t1  A 因 GC / 长 tool 调用卡住，未续租
t2  patrol() 判 A 死 → BLOCKED → redispatch → worker B claim T1
t3  A 复活，执行完，UPDATE tasks SET state='SUCCEEDED', result_json=... WHERE task_id='T1'
t4  B 的结果被 A 覆盖，或 A 的结果把 B 正在跑的任务提前置为终态
```

`WHERE task_id=?` 在 t3 时刻仍然匹配，所以 A 的写入**必然成功**。方案 §4.4 把"写冲突"列为监督规则，但那是事后检测——检测到时数据已经被覆盖了。

这正是 Kleppmann 在《How to do distributed locking》(2016) 里用 GC pause 举的那个例子：**带过期时间的锁无法阻止"迟到的客户端"写入**，唯一可靠解法是让被保护的资源校验一个单调递增的 fencing token，拒绝过期 token 的写入。Chubby (OSDI'06) 的 sequencer 是同一机制。方案已经在用 CAS 做领取，只差把 token 落进 schema 并在**每一次写回**上校验——改动很小，但缺了它整套"一任务一持有人"的保证是空的。

**修改建议。** schema 增加两列：

```sql
lease_epoch   INTEGER NOT NULL DEFAULT 0,   -- 每次 claim 递增，fencing token
claimed_at    REAL,                          -- 便于区分"领了没跑"与"跑了一半"
```

领取时 `lease_epoch = lease_epoch + 1`，并把新 epoch 返回给 worker。worker 的**所有**写操作（heartbeat / 进度 / 终局）都必须带 epoch：

```sql
-- 终局写回
UPDATE tasks
   SET state=:terminal, result_json=:r, completed_at=:now, updated_at=:now
 WHERE task_id=:tid AND lease_epoch=:epoch AND claimed_by=:worker;
-- rowcount == 0 → 本 worker 已被 fence，必须立刻自杀，不得重试、不得落盘
```

对应地，`WorkerCapability` / worker 进程的约定要加一条硬规则：**fenced worker 的产物一律作废**（包括它写出去的文件），由 `output_path` 的版本化或 worktree 隔离来兜底。这条要写进 §4.5 的 worker 契约，不能只写在 dispatcher 里。

**补充：租约续期也要走同一事务。** 否则 heartbeat 与 claim 之间存在"续租成功但已被 reclaim"的窗口——epoch 校验天然解决，但实现上要保证 heartbeat 的 UPDATE 也带 `lease_epoch=:epoch`。

### B2 · 把 `async_delegations` 合并进 `tasks` 会丢掉投递维度

**问题。** 方案 §5 写"`async_delegations` 表 → 合并 → 迁到 `tasks`；租约逻辑保留"。但 `async_delegations` 里其实有**两个正交的生命周期**：

| 生命周期 | 列 | 语义 |
|---|---|---|
| 执行 | `state`, `dispatched_at`, `completed_at`, `owner_pid` | 子代理跑没跑完 |
| 投递 | `delivery_state`, `delivery_attempts`, `delivered_at`, `delivery_claim`, `delivery_claimed_at` | 结果有没有送回父会话 |

这两者的完成时刻**天然不同**：子代理可能在父会话离线时完成（`delivery_state='pending'`），也可能在进程重启后才被投递（`claim_completion_delivery` 的存在理由）。合并成一张表后，`tasks.state` 只有一个终态，投递就无处安放——要么塞进 `result_json` 里做隐式状态（又造出一套"同一件事两种说法"），要么丢功能。

方案自己在 §1.3 把"投递租约"列为**必须沿用的四项之一**，却在 §5 把它合并掉，这是内部矛盾。

**修改建议。** 拆两张表，`tasks` 只管执行，`deliveries` 管投递：

```sql
CREATE TABLE deliveries (
    delivery_id     TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    origin_session  TEXT NOT NULL,
    origin_session_id TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'pending',  -- pending|claimed|delivered|dead
    attempts        INTEGER NOT NULL DEFAULT 0,
    claim           TEXT,
    claimed_at      REAL,
    delivered_at    REAL,
    payload_json    TEXT,
    created_at      REAL NOT NULL
);
CREATE INDEX idx_deliveries_pending ON deliveries(state, claimed_at);
CREATE UNIQUE INDEX idx_deliveries_task ON deliveries(task_id);  -- 一任务一投递
```

好处：`claim_completion_delivery` 的 CAS 语义原样保留（只是换表名），重启恢复路径不变，且投递失败不会污染任务状态机。**迁移成本比合并更低**——因为不需要改写投递逻辑，只需要改表名。

### B3 · 进程化之后，控制面没有实现路径

**问题。** 方案 §5 承诺"`delegate_task()` 签名保留，返回 JSON 只增字段"，§4.5 又把执行单元改成独立进程。但现有控制面的三个动作都依赖**同进程内的活对象**：

- `action='list'`：`_handle_control_action` L474 直接 `list(_active_subagents.values())`，取 `r["agent"]` 的 `_live_transcript_path`。
- `action='steer'`：向运行中的 child 注入纠偏文本——必须触碰活对象。
- `action='stop'`：`interrupt_subagent(sid)` 走进程内中断标志。

一旦 child 在另一个进程里，这三件事全部失效。方案 §4.5 只讨论了"入参/出参/退出码"，完全没提控制通道。这不是实现细节——**`steer` 是长任务编排里唯一能纠偏的手段**，丢掉它，方案 §4.4 的"修正"能力就只剩"杀掉重派"，而重派的成本是整份上下文。

**修改建议。** 增加一张控制指令表 + worker 轮询（因为 SQLite 没有 LISTEN/NOTIFY，见 H2）：

```sql
CREATE TABLE task_commands (
    cmd_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    kind        TEXT NOT NULL,      -- steer|stop|budget_update
    payload     TEXT,
    created_at  REAL NOT NULL,
    acked_at    REAL
);
CREATE INDEX idx_cmd_pending ON task_commands(task_id, acked_at);
```

- worker 每次 heartbeat 顺带 `SELECT ... WHERE task_id=? AND acked_at IS NULL`（读操作，不加重写锁）。
- `list` 改为查库（`tasks WHERE batch_id=? AND state NOT IN terminal`），这本来就是方案想要的"唯一真相源"。
- `stop` = 插入 `kind='stop'` 指令 + 置 `cancel_requested_at`（见 H5），由 worker 在迭代边界自行退出；超时未退则由 sweeper 强杀。
- 接口层保持 `action='steer'` 不变，但语义从"注入活对象"降级为"入队一条指令，最多一个 heartbeat 周期后生效"。**这个语义变化必须写进 tool description**，否则模型会以为 steer 是同步生效的。

---

## 3. 高优缺陷

### H1 · pull 模型没有 worker 的拉起者与退出条件

方案 §4.4 说"pull 为主"，§4.5 给了 worker 入口 `python -m fulilian.orchestration.worker`，但没有回答：**谁启动它？启动几个？什么时候退出？**

现状是 CLI 一次调用一个进程（`fulilian` / `fll`），没有常驻调度器。纯 pull 需要常驻消费者，而 CLI 用户不会常驻。方案提到"无订阅者时退化为父代理同步执行"，那等于承认：**没有 daemon 时，队列根本不工作**。

**建议补一节"worker 承载模型"，明确三档：**

| 形态 | 触发 | worker 生命周期 | 适用 |
|---|---|---|---|
| inline（默认，CLI 单任务） | 无 daemon | 不落队列，走现有同步快路径 | 单任务、短任务 |
| embedded pool（CLI 后台批） | `background=true` 且批 ≤ `batch_limit` | 父进程内起 N 个线程 worker，父进程退出时 drain | 现有 async 语义 |
| daemon（大规模） | `fulilian orchestrate daemon` 或 gateway 启动时 | 常驻，空闲超时退出（如 30 min 无任务） | 500 容量队列 |

没有这一节，阶段 3 的"接入 `delegate_task`"会卡在一个没人回答的问题上：**进程 A 派发的任务，凭什么由进程 B 执行完还能投递回 A 的会话？** 答案是 `deliveries.origin_session` + `claim_completion_delivery`（现状已有），但需要显式写出来，否则实现者会重新发明。

### H2 · 空队列时的 claim 是写事务，会放大写竞争

方案的 CAS 领取 SQL：

```sql
BEGIN IMMEDIATE;
UPDATE tasks SET ... WHERE task_id = (SELECT ... WHERE state='QUEUED' ... LIMIT 1) AND state='QUEUED';
COMMIT;
```

子查询返回 NULL 时 `task_id = NULL` 恒假，`rowcount=0`——但**事务已经拿到了写锁**。15 个空闲 worker 以 200ms 间隔轮询，就是 75 次/秒的写事务，每次带一次 WAL 提交。这会把 SQLite 的单写者吞吐打满，而队列里一条任务都没有。

同类问题在 `busy_timeout=5000` 下更糟：一旦写锁被占，其余 14 个 worker 全部阻塞在 5s 的等待上，形成"空转 → 超时 → 再空转"。

**建议三条：**

1. **先读后写**：`SELECT 1 FROM tasks WHERE state='QUEUED' AND pool=? LIMIT 1`（纯读，WAL 下不阻塞），非空才开 `BEGIN IMMEDIATE`。空队列时零写事务。
2. **指数退避 + 抖动**：空闲 worker 的轮询间隔 100ms → 200 → 400 → … 上限 2s，避免同步脉冲（thundering herd）。这是分布式重试的通用做法（AWS 架构博客《Timeouts, retries, and backoff with jitter》）。
3. **批量采样（batch sampling）**：借 Sparrow (SOSP'13) 的做法——一次采样 `d·m` 个候选（d≈2），在应用层按负载选 m 个，而不是让每个 worker 独立抢队首。Sparrow 的结论是：单纯"抢队首"在负载升高时性能显著劣化，批量采样 + 延迟绑定（late binding）才能保持低延迟。在 SQLite 场景下，具体做法是 `SELECT task_id FROM ... LIMIT 2*concurrency` 一次取回，worker 按本地负载挑，减少写事务次数。

**另外**：SQLite 是"多读单写"。公开的实测结论是 5 路以上并发写者就该重新评估存储选型。方案的 15 个 worker 每人一个 heartbeat 写事务，即使按 5s 一次也有 3 写/秒，配合 claim 峰值会逼近上限。这不是说不能用 SQLite，而是**必须把写频率做成设计约束**（heartbeat 间隔可配、空闲不写、批量提交），并在阶段 2 的验收里加一条"空队列 15 worker 运行 10 分钟的写事务计数"基准。

### H3 · 三键排序没有 aging，必然饿死

`ORDER BY is_key DESC, priority DESC, tier ASC, created_at ASC` 是严格优先级。严格优先级的经典问题就是**饿死**：只要持续有钥匙任务/T1 任务进入，低优先级任务永远轮不到。方案 §4.4 自己写"T1 清零后再投 T2/T3"——在一个持续派发的系统里，"清零"这个条件可能永不成立。

而且 `tier ASC` 对 DAG 是错的排序键。依赖图调度的经典结论是：应该按**bottom-level（到汇点的最长路径）**降序排，即"关键路径优先"（Hu 1961 的列表调度、Graham 1966 的界），而不是按任务自身的大小排。一道 T1 任务如果依赖一道 T3，先跑 T1 毫无意义——它只能等。

**建议：**

```sql
-- 有效优先级 = 基础优先级 + 等待时间的老化项 - 关键路径长度
ORDER BY is_key DESC,
         (priority + CAST((:now - created_at) / :aging_seconds AS INTEGER)) DESC,
         bottom_level DESC,
         created_at ASC
```

- `aging_seconds`（如 300s）保证任何任务等待 5 分钟后至少提升 1 级。
- `bottom_level` 在 enqueue 时算好落库（DAG 已在入队时校验无环，顺手算）。
- `tier` 退化为 `priority` 的初始值来源，不再单独作为排序键——**三键变两键，可分析性显著提升**。

另外，方案没有**跨批次公平性**。批 A 有 500 个 T1、批 B 有 5 个，B 会被 A 淹没。如果存在多会话/多用户并发，需要 deficit round robin 或至少按 `batch_id` 轮转。若明确单用户单会话，则应在文档里写"不支持跨批次公平"作为已知边界——**写下来比留白好**。

### H4 · 没有 token 预算，只有时间预算

`TaskCard` 有 `budget_seconds`，没有 `budget_tokens` / `budget_usd`。

Anthropic 的实测数据是：多智能体系统消耗的 token 约为普通对话的 **15 倍**，且 token 用量能解释约 80% 的性能方差。这意味着**成本是这类系统的一等约束，不是可选项**。500 容量的队列 + 15 并发 + 每题几十万 token，一次跑飞就是四位数美元。

`budget_seconds` 也拦不住：一个卡在重试循环里的 agent 在 300 秒内可以烧掉大量 token。

**建议：**

1. `TaskCard` 增加 `budget_tokens: Optional[int]`、`budget_usd: Optional[float]`。
2. 预算检查点放在 **worker 的每次 API 调用前**（现有 `api_call_count` 已有埋点），超限则 worker 自行以 `exit code 3（需重派）` 退出并落 `FAILED(reason=budget_exceeded)`。
3. 批次级预算：`batch.budget_tokens`，`enqueue` 时校验 `sum(cards) <= batch_budget`，运行时由 sweeper 汇总。
4. 全局预算：`orchestration.daily_token_budget`，超限则 `enqueue` 直接拒绝（这是唯一能真正止血的闸门）。
5. 预算耗尽的处理策略要显式：**降级（换便宜模型重跑剩余任务）优于中止**——这与方案 §2.1"修正：降级"的定位一致。

### H5 · 删掉 `CANCEL_REQUESTED` 但没有给出终止路径

方案 §4.2 的注释说"这条直接根治现状 `cancel()` 的问题"，但现状的问题不是"有 `CANCEL_REQUESTED` 这个状态"，而是"置了状态却没人执行"。删掉状态并不会让取消变得可执行——它只是让"取消请求已发出但尚未生效"这个**真实存在的中间态**无处记录。

后果：`cancel()` 要么同步阻塞到 worker 退出（可能几分钟，CLI 卡死），要么返回"已取消"而实际还在烧 token（就是现状的谎言，只是换了个说法）。

**建议：保留中间态，但给它一个截止时间。** 不加状态枚举，加一列：

```sql
cancel_requested_at REAL
```

- `cancel()` = 写 `cancel_requested_at` + 插入 `task_commands(kind='stop')`，立即返回 `state='RUNNING', cancel_requested=True`（**如实告知**，不再谎报 CANCELLED）。
- worker 在迭代边界检查，正常退出 → `CANCELLED`。
- sweeper 检查 `cancel_requested_at < now - grace`（如 30s）→ 强杀进程 → `CANCELLED(reason=force_killed)`。
- 状态机不用改：`RUNNING → CANCELLED` 已在允许表里。

这样"取消"有了确定的收敛时间上界，且中间态可观测（TUI 可以显示"取消中"）。**现状的 `CANCEL_REQUESTED` 唯一的问题是缺一个执行者，不是缺一个状态名。**

### H6 · 进程隔离的两个平台陷阱

方案 §4.5 的执行单元对比表里，"强制终止 = SIGKILL 立即"和"资源限制 = rlimit/cgroup"两行都是 Linux-only 假设，但本仓库明确支持 Windows（`docker-compose.windows.yml`，且 `tools/daemon_pool.py` 的注释专门处理了 CPython 3.14 Windows 运行时的 `_worker` 签名变化）。

**陷阱 1：fork + 线程。** worker 是线程，线程里 `fork()` 出的子进程只继承调用线程，但会继承其他线程持有的锁的**已加锁状态**——子进程一碰这些锁就死锁。CPython 3.12 起，检测到多线程时 `os.fork()` 会发 `DeprecationWarning`；3.14 起 POSIX 默认启动方法已改为 `forkserver`。**必须显式 `multiprocessing.get_context("spawn")` 或 `"forkserver"`，绝不能用默认值。** 这条要写进 worker 实现约定，否则在 Linux 上会随机死锁、且极难复现。

**陷阱 2：Windows 没有 SIGKILL / killpg。** 方案 §4.5 的"`terminate()` → 等 5 秒 → `kill()`"在 Windows 上语义不同（`TerminateProcess` 不跑清理），且**杀不掉孙进程**。取证任务经常是 worker → python → 外部二进制三层，只杀中间层会留下孤儿。

**建议：**

- Linux：`start_new_session=True`（新进程组）+ `os.killpg(pgid, SIGKILL)`。
- Windows：`CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F /PID`，或 Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，能保证父死子死）。
- 统一抽象成 `ProcessReaper.terminate_tree(pid, grace)`，平台差异收在一个模块里。

**另外，"进程隔离"不等于"沙箱"。** 方案说"解析库被 exploit 是现实风险，工具层隔离管不到这一层"——这句话对，但结论不对：`subprocess` 只能防段错误拖垮主进程，防不住 fork bomb、磁盘写满、以及针对解析库的 RCE。取证场景解析畸形 pcap/PE/内存镜像，如果需要真正的隔离，应该上 **gVisor / Firecracker / 容器**，而不是普通子进程。建议把 §4.5 的定位从"隔离"改成"**故障隔离**"（fault isolation），并明确写"不提供安全隔离，不可信输入的沙箱化是独立议题"。这个措辞差异会直接影响后续是否有人误以为已经安全了。

### H7 · `output_path` 全局唯一与重派冲突

入队校验第 1 条："`output_path` 绝对路径且**全局唯一**（查库 + 批内去重）"。

但 `redispatch` 会把同一个任务重新入队，`output_path` 不变 → 唯一约束直接拒绝。同样，`FAILED → QUEUED` 的 retry 也会撞。方案没有说清唯一性是"跨任务"还是"跨活跃任务"。

**建议：改成部分唯一索引，只约束活跃态：**

```sql
CREATE UNIQUE INDEX idx_tasks_output_active
    ON tasks(output_path)
 WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELLED','INTERRUPTED');
```

语义变成"**同一时刻只能有一个任务在写这个文件**"，这才是真正想防的（写冲突），且不阻碍重派。同时补 `tasks(output_path)` 的普通索引供查重。

顺带：这个约束管不住"任务 A 写 `out/a.md`、任务 B 写 `out/a.md.bak`"这类前缀冲突。真正的写冲突防护要靠 `resources`（方案已有）或 worktree 隔离（方案丢了，见 M4）。

### H8 · `card_json` 与列是同一个行里的两个真相

方案用列存 `role/pool/tier/is_key/priority/isolation`，同时 `card_json TEXT NOT NULL` 又存了完整卡片。这两份数据会漂移：卡片是不可变的，列是可更新的（`priority` 可能被 aging 改、`isolation` 可能被推断覆盖）。于是**在解决了"三套真相源"之后，又在单行内造出了第四套**。

这个批评不是吹毛求疵——它会导致同一类 bug 以新的形式复现：`ORDER BY` 用列，审计用 JSON，两者不一致时没人知道该信谁。

**建议：**

1. 明确契约：**列是查询与排序的唯一真相；`card_json` 是入队时刻的不可变快照，只用于重放与审计**，任何逻辑不得从 JSON 读排序字段。
2. 加 `card_hash TEXT`（`sha256(canonical_json(card))`），并在 insert 时断言 `derived_columns == derive(card)`。一条测试就能锁死。
3. 如果某个列会被引擎改写（`priority`、`isolation`），它就不该出现在"派生自 card"的集合里——要在文档里区分 **card 字段** 与 **engine 字段**，别混在一张表里不标注。

---

## 4. 中优问题

| # | 问题 | 建议 |
|---|---|---|
| M1 | **pools 数字自相矛盾**：`max_running=15`，但 `solve=15 + supervision=1 + audit=1 = 17` | 明确 `max_running` 是全局硬顶，pools 是其上的配额划分，`sum(pools) >= max_running` 时以 `max_running` 为准并在启动时告警 |
| M2 | **`supervisor` 任务 `depth=0`** 破坏树不变量 | 改为 `depth = parent.depth`（或 `parent.depth + 1`），并用 `role` 而非 depth 区分；否则 `max_spawn_depth` 校验与树形渲染都会错 |
| M3 | **`patrol()` 跳过 `role=supervisor`** 与"硬约束一视同仁"矛盾 | 只跳过"生成新的语义巡检"，**不跳过**硬约束扫描；否则卡死的 supervisor 任务永远无人回收，形成自指死锁 |
| M4 | **worktree 隔离在方案中消失** | 现状有 `tools/subagent_worktree.py`。并行写同一仓库必须靠 worktree，否则 15 个 worker 互相覆盖。建议作为 `resources` 的一种（`resource="worktree:<repo>"`），或 `TaskCard.worktree: Optional[str]` |
| M5 | **`can_write_shared=False` 但 supervisor 要写自己的 `output_path`** | 拆成 `can_write_shared` 与 `can_write_own_output`（后者恒为 True） |
| M6 | **`depends_on` 缺"依赖失败"的传播** | 依赖进入非成功终态时，下游应 `BLOCKED(reason=dependency_failed)`，再由 redispatch 决定 `CANCELLED` 还是改派。当前 `_ALLOWED` 里没有这条路径，任务会永远 `QUEUED` |
| M7 | **`depends_on` 禁止前向引用** | "引用的 task 存在"若按字面实现，就无法一次性声明整张 DAG（后置任务引用尚未创建的 task）。应允许批内前向引用，批次插入后再整体校验 |
| M8 | **`events` / `dispatch_log` 无保留策略** | 两张日志表会无限增长。设 TTL（如 events 7 天、dispatch_log 30 天）+ 定期归档到 `cache/orchestration/`；或合并成一张 `events` 带 `kind`，减少一套真相 |
| M9 | **无 schema 迁移机制** | 现状 `_initialize_schema` 用 `PRAGMA table_info` + 手工 `ALTER TABLE`。6 个阶段的演进需要 `schema_version` 表 + 前向迁移函数，否则阶段间升级会静默失败 |
| M10 | **无幂等键** | 调用方超时重试 `enqueue` 会产生重复任务。加 `idempotency_key TEXT` + 唯一索引，重复请求返回原 `task_id`。这是 at-least-once 客户端的标准配套 |
| M11 | **`route_fingerprint` 未定义算法** | 若实现者直接 hash `goal`，每次重派 goal 微调都会"换路线"，上限形同虚设。要**明确输入**：`hash(sorted(toolsets) + data_source_id + split_dimension)`，且**存分量而非只存 hash**（可调试） |
| M12 | **`attempts` 与 `handoff_count` 双计数无不变式** | 定义：`attempts` = 执行次数（含首次），`handoff_count` = 持有人变更次数。不变式 `attempts >= handoff_count + 1`，违反即引擎 bug |
| M13 | **`is_key` / `priority` / `tier` 三键语义重叠** | 见 H3，合并为 `priority + aging + bottom_level` |
| M14 | **默认 `batch_limit=15` 与文献不符** | Anthropic 的实践是"一次并行 3–5 个子代理"效果最好，超过后协调成本与 token 消耗陡增。建议 `max_concurrent_children` 默认 **5**，15 作为**硬上限**（`hard_cap`）而非默认值。AGENTS.md 的 "default 3" 也更接近这个区间 |
| M15 | **无 trace 关联** | 跨进程后，父 trace 与子 span 断链。加 `trace_id` / `span_id` 列，按 OpenTelemetry GenAI semantic conventions 导出；否则 TUI 的"后台子代理"视图无法串起来 |
| M16 | **`TaskCard` 的 `frozen=True` 与可变默认值** | `Mapping`/`tuple` 字段在 frozen dataclass 里不可 hash（`output_schema` 是 dict），`frozenset`/`set` 之类也会踩。建议 `output_schema: Optional[str]`（JSON 字符串）或加 `eq=False` 并显式实现 `__hash__` |
| M17 | **`str, enum.Enum` 而非 `StrEnum`** | Python 3.11+ 有 `enum.StrEnum`，语义更准（`isinstance(x, str)` 且 `str(x)` 返回值）。当前写法 `str(x)` 返回 `"TaskState.QUEUED"`，落库时会写错。**这是个会直接写坏数据的细节** |
| M18 | **状态机 `_ALLOWED` 用裸名** | 示例里 `QUEUED: frozenset({CLAIMED, CANCELLED})` 而非 `TaskState.QUEUED`。落地时若用裸名会 NameError 或误引用；且 `TaskTier(int, Enum)` 与 `TaskState(str, Enum)` 混用会让 `_ALLOWED` 的 key 类型校验失效 |

---

## 5. 与公开文献的对照

方案 §9 的参考表方向是对的，但有几条被引用了却没落实到设计里。以下按"文献结论 → 方案缺什么 → 具体改法"组织。

### 5.1 Anthropic《How we built our multi-agent research system》(2025-06)

| 文献结论 | 方案现状 | 建议 |
|---|---|---|
| 多智能体比单 agent 高 90.2%，但消耗约 **15× token**；token 用量解释 80% 性能方差 | 只有 `budget_seconds` | 见 H4，加 token/usd 预算 + 三级闸门 |
| 建议**一次并行 3–5 个**子代理 | 默认 `batch_limit=15` | 见 M14，默认 5，15 作硬上限 |
| 同步等待是已知瓶颈 | 方案用 pull 解决，方向正确 | 保留；但补 H1 的 daemon 承载，否则 CLI 下仍是同步 |
| **子代理失败后很难恢复**，需要"让 agent 知道如何从失败中恢复" | 方案有 retry/handoff，但没有"部分成功"的语义 | 加 `partial_result` 字段：任务失败时保留已完成的部分，供 aggregator 归并。这是"宁可先交 10 道"的机制保障 |
| 任务描述四要素：目标 / 输出格式 / 工具 / 边界 | `TaskCard` 的 `goal/dod/scope/output_schema/allowed_toolsets` 已覆盖 | 保持；建议 `dod` 强制"可判定"，即每条必须是可机检的断言，否则 `dod` 会退化成自然语言愿望 |

### 5.2 Cognition《Don't Build Multi-Agents》(2025-06)

这是与 Anthropic 针锋相对的一篇，方案完全没引，但它对**本方案的风险面**判断更准。

| 文献结论 | 对方案的威胁 | 建议 |
|---|---|---|
| 两个原则：① 子代理必须共享完整上下文与轨迹，不能只给压缩后的任务描述；② **动作携带隐含决策**，并行子代理会做出互相冲突的决策 | 方案正是"任务卡 + 并行"，天然踩第②条：两个 worker 同时改同一份代码/同一份报告的不同章节，各自做了不兼容的假设 | ①`TaskCard.context` 要支持"引用父轨迹"而非只塞一段文本；②**写冲突必须是硬约束而非监督建议**：`resources` 互斥要在 `enqueue` 时校验，不能只靠事后检测 |
| 结论：多数任务应单线程；子代理只用于**隔离的、只读的、边界清晰**的工作（如在大上下文中检索） | 方案把子代理用于"写产出"（`output_path` 每任务一个），这恰是文献建议避免的 | 分层：**读类任务**（检索/取证/分析）走并行子代理；**写类任务**（改代码/写报告）走串行或 worktree 隔离 + 单写者。这个分层建议写进 §2.1 的能力边界 |

我不认为这意味着方案要推翻——Fulilian 的场景（CTF 取证、多目标侦察）更接近 Anthropic 的"广度优先检索"，而不是 Cognition 的"编辑同一个代码库"。但**必须在文档里显式说明这个判断**，并给出"什么任务不该并行"的判据。否则实现者和使用者都会默认"所有任务都能拆"。

### 5.3 MAST《Why Do Multi-Agent LLM Systems Fail?》(arXiv:2503.13657, 2025)

7 个框架、200+ 任务、6 位标注者，归纳出 **14 种失败模式 / 3 大类**：系统设计缺陷、智能体间错位、**任务验证**。

关键结论：**多数失败不是模型能力不足，而是协调与验证机制缺失。**

| 对方案的启示 | 具体建议 |
|---|---|
| "任务验证"是三大失败类之一，但方案的状态机里 `RUNNING → SUCCEEDED` 是**直接跳转**，没有验证阶段 | 加一道门：`SUCCEEDED` 必须经过 `dod` 机检 + `output_schema` 校验。现有 `tools/delegation_output_schema.py`（154 行）已经能做 schema 校验，把它接进终局路径，而不是另起炉灶 |
| 验证不能只靠同一个 agent 自评 | 引入 `role=audit`（方案已预留）作为**采样复核**：按比例（如 10%）抽检 `SUCCEEDED` 任务，失败则回退为 `BLOCKED`。这比"监督员读简报"更便宜也更有效 |
| 智能体间错位主要来自"信息不对称" | `TaskCard.context` 应强制包含"上游已确认的事实"（而非只有 goal），否则并行 worker 会各自重新发现同一批事实，既浪费 token 又产生分歧 |

### 5.4 Sparrow (SOSP'13) / Omega (EuroSys'13)

| 文献结论 | 方案现状 | 建议 |
|---|---|---|
| Sparrow：pull + **batch sampling** + **late binding** 才能在负载升高时保持低延迟；单纯随机/队首分配会显著劣化 | 方案是"每 worker 抢队首" | 见 H2，改成一次采样 `2m` 个候选、按本地负载挑 |
| Omega：共享状态调度（shared-state）靠乐观并发，冲突率随调度器数量上升 | 方案正是共享状态（SQLite 作为共享状态存储） | 承认这一点：15 worker 规模下冲突可接受，但要给出**容量上限的量化判据**（如"写事务 > 50/s 或 busy 重试率 > 5% 时须换存储"），而不是笼统说"压力不大" |

Sparrow 的 late binding 值得单独提一句：它的做法是"把探针放进 worker 队列，谁先空出来谁拿任务"，而不是"调度器选一个 worker 推过去"。在 SQLite 场景下，等价物是 **worker 主动 claim + 队列侧不预分配**——方案已经是这个形态，只是没意识到这就是 late binding，因此也没做 batch sampling。

### 5.5 Chubby (OSDI'06) / Kleppmann (2016)

见 B1。核心：**租约必须有 fencing token**，否则过期租约的旧持有者仍能写入。方案有租约无 token，是这套机制的一半。

### 5.6 SQLite WAL 的公开实测结论

- WAL 下**多读单写**：读者不阻塞写者，写者阻塞写者。
- `BEGIN DEFERRED` 下"先 SELECT 后 UPDATE"会触发**事务升级**，此时 SQLite 立即返回 `SQLITE_BUSY` 而**不遵守 `busy_timeout`**——这是最常见的"配了 timeout 还是报 busy"的原因。方案的 `BEGIN IMMEDIATE` 正确规避了这一点，**这一点方案做对了，应当保留并在注释里写明理由**（否则后人会"优化"成 DEFERRED）。
- 5 路以上并发写者应重新评估存储选型。

### 5.7 Python 3.12 / 3.14 的 fork 语义

见 H6。`os.fork()` 在多线程进程中自 3.12 起发 `DeprecationWarning`，3.14 起 POSIX 默认启动方法改为 `forkserver`。**worker 是线程 → 必须显式 `spawn`/`forkserver`。**

### 5.8 Google SRE 的告警原则

方案 §7 把监督的验收标准定为"误报率 < 10%"。这个指标选错了。

SRE 的原则是：**每一条告警都必须是可行动的（actionable）**，不可行动的告警应当删除而不是调阈值。因为一旦团队学会忽略告警，整套机制就永久失效——方案 §4.6 自己引用了 `multi-agent-dispatch` 的这条实证，却在验收标准里用了"误报率"这个滞后指标。

**建议改为三个指标：**

| 指标 | 定义 | 目标 |
|---|---|---|
| 精确率 | 真实异常 / 总告警 | > 0.8 |
| 可行动率 | 收到告警后 5 分钟内产生了非空操作的比例 | > 0.9 |
| 重复率 | 同一 task 在 1 小时内重复告警的次数 | < 2（超了说明该合并/抑制） |

并且：**每条告警必须自带 runbook 链接与建议动作**，否则不予上线。这比"误报率 < 10%"可执行得多。

---

## 6. 对实施计划的修改建议

### 6.1 阶段划分调整

方案的 6 阶段顺序有一个结构性问题：**进程隔离被放在阶段 3（"执行单元"隐含在 dispatcher 里），但它才是风险最高、最容易返工的部分**。而控制通道（B3）在方案里根本没有阶段归属。

建议改成 7 阶段，把"进程隔离"独立出来并后置为灰度项：

| 阶段 | 内容 | 变更说明 |
|---|---|---|
| 0 止血（1–2 天） | 配置对齐 + 一致性断言 + **修掉 `PRAGMA` 事实错误** | 原样 + 1 项 |
| 1 契约（1 周） | contracts + state_machine + config + **修订后的 schema（epoch/幂等键/cancel_requested_at/deliveries/task_commands）** + migration runner | 扩大范围：schema 一次定型，避免阶段 2 返工 |
| 2 存储（2 周） | store + CAS + 租约 + **fencing 写回校验** + 空队列写放大基准 | 加 2 项验收 |
| 3 派发（2 周） | dispatcher（batch sampling + 退避）+ **worker 承载（三档）** + **控制通道 list/steer/stop** | 加 2 项，这是原方案最大的空白 |
| 4 监督与修正（2 周） | supervisor（先只硬约束）+ redispatch | 原样 |
| 5 进程隔离（1 周，**feature flag**） | ProcessReaper + spawn/forkserver + 平台差异 | **新增独立阶段**，先只对 `terminal/execute_code` 类任务开启 |
| 6 组织与聚合（1–2 周） | organizer + aggregator | 原样 |
| 7 清理（1 周） | 删旧注册表 + 分层检查 | 原样 |

总计约 10–12 周，比原估多 1 周，但把两个最高风险项（进程隔离、控制通道）从"隐含"变成"显式"。

### 6.2 迁移策略：从"双写"改为"单写 + 影子读"

方案 §5 提出"双写一个版本 + 每日对账"。**双写是分布式系统的已知反模式**：两次写必然存在部分失败窗口（写 A 成功、写 B 失败），此时系统状态是不确定的，而对账只能事后发现、不能事前避免。而且双写会让"两套都是真相"，恰好是方案要消灭的问题。

**建议改为：**

1. **影子模式（1 周）**：新引擎只做**决策记录**——`delegate_task` 仍然走旧路径执行，但同时生成 `TaskCard` 并写入 `tasks`（`state='SHADOW'`）。对比"新引擎会怎么排"与"旧路径实际怎么跑"。
2. **单写切换**：新引擎成为唯一写入方，旧表改为**只读镜像**（由新引擎在终局时写一行），供旧代码/测试读取。
3. **下线镜像**：一个版本后删除。

这样任何时刻只有一套真相源，回滚只需把开关拨回去。

### 6.3 第一个 PR 的范围

方案 §6.2 的两项改动是对的，但建议补第三项：

**改动 3：加一个"不变量测试"骨架**（纯测试，无生产代码）

在 `tests/orchestration/test_invariants.py` 里先写好这几条断言的空壳（用 `pytest.mark.skip` 占位），后续每个阶段填一条：

- `attempts >= handoff_count + 1`
- `terminal states have completed_at`
- `card_json` 派生列 == 列实际值
- `sum(pools) <= max_running`（或显式声明例外）
- `output_path` 在活跃态唯一

理由：这类不变量是最容易在重构中被静默破坏的，先有骨架比事后补测试便宜得多。而且它给阶段 0 的"一致性断言"提供了落脚点。

---

## 7. 逐节修订清单

按方案章节给出可直接照改的动作项。

| 章节 | 动作 |
|---|---|
| §0 决策摘要 | 加"队列独立库"决策；加"fencing token"决策；加"控制通道"决策；`batch_limit` 默认值改 5、15 降为 hard cap |
| §1.2 P1 | 补第四套状态 `_recent_subagents` |
| §1.2 P3 | 行号改为符号引用；补 `_recent_subagents` |
| §3 架构图 | 加 `control.py`（控制通道）与 `delivery.py`（投递）两个模块 |
| §4.1 契约 | `TaskCard` 加 `budget_tokens`/`budget_usd`/`idempotency_key`/`worktree`；`output_schema` 改 JSON 字符串；`StrEnum` |
| §4.1 校验 | `output_path` 唯一改为"活跃态唯一"；`depends_on` 允许批内前向引用 |
| §4.2 状态机 | `FAILED` 增加 `reason`；补"依赖失败 → BLOCKED"路径；`_ALLOWED` 用限定名 |
| §4.3 schema | 加 `lease_epoch`/`claimed_at`/`cancel_requested_at`/`idempotency_key`/`trace_id`/`span_id`/`bottom_level`/`card_hash`；拆 `deliveries`；加 `task_commands`；加 `schema_version`；`state` 加 CHECK 约束 |
| §4.3 PRAGMA | 改为独立库 + WAL；若复用 `state.db` 则改用 `apply_durability_barriers` |
| §4.3 原子领取 | 加"先读后写"前置检查；加 batch sampling；`lease_epoch + 1` |
| §4.4 编排序 | 三键改两键（priority+aging、bottom_level）；补跨批次公平性的边界声明 |
| §4.4 派发 | 补 H1 的三档承载模型；补 H2 的退避与批量采样 |
| §4.5 执行单元 | 标题改"故障隔离"；补 spawn/forkserver 强制；补 Windows 进程树回收；补"不提供安全隔离"的边界声明 |
| §4.5 进程承载 | 补控制通道；补"fenced worker 产物作废" |
| §4.6 监督 | `depth=0` 改继承；`patrol()` 只跳过语义巡检不跳过硬约束；补 `can_write_own_output` |
| §5 映射 | 补 `_recent_subagents`；补 `action=list/steer/stop` 的跨进程改造；投递改"拆表"而非"合并" |
| §5 迁移 | 双写改单写 + 影子读 |
| §6 阶段 | 按 §6.1 改为 7 阶段 |
| §7 验收 | "80 个测试"改 120 个；"误报率 < 10%"改精确率/可行动率/重复率；补"空队列写事务计数"基准 |
| §9 参考 | 补 Cognition (2025)、MAST (2025)、Sparrow/Omega、Kleppmann (2016)、SQLite WAL 实测、Python 3.12+ fork 语义 |

---

## 8. 一句话结论

**方案诊断准确、方向正确，三处"把状态搬库、把调度改 pull、把监督下沉规则"的判断都与工程界的主流结论一致；但它把"租约"当成了完整的互斥（缺 fencing token）、把"投递"当成了执行状态的一部分（缺拆表）、把"进程化"当成了纯性能优化（缺控制通道与平台差异处理）。这三处不修，阶段 3 的切换点会以"结果被覆盖 / 结果送不回去 / steer 失效"三种形式同时爆出来。**

**最小改动集：schema 加 `lease_epoch` + 拆 `deliveries` + 加 `task_commands` + 队列独立建库。这四项都在阶段 1 的契约里，改起来只是几个字段，但决定了后面 9 周是否需要返工。**
