# 代码审查 · 分片 B（存储与约束）

审查对象：`agent/orchestration/schema.py`、`tests/orchestration/test_schema.py`、`tests/orchestration/test_invariants.py`、
`tests/agent/test_delegation_config_contract.py`。环境：WSL `/home/xujuan/.fulilian/fulilian-agent`，`./venv/bin/python`（sqlite 3.40+）。

**结论：P0 = 0，P1 = 4，P2 = 8，P3 = 3。** 其中 3 条（`depth` 缺列、`batch_id` 无默认、`output_path` 可空）是主控交叉探针指出后我**独立复现**的补充项，编号 P1-3 / P1-4 / P2-8。

先说我**没有**找到问题的部分（均已实测，非推理）：

| 检查项 | 实测结果 |
|---|---|
| `state` CHECK | `'queued'` / `''` / `'QUEUED '` / `' QUEUED'` 全部拒绝；`NULL` 被 NOT NULL 拦下 |
| 默认值组合 | 不写 `state/attempts/tier/isolation` → `('QUEUED', 0, 2, 'process', 0, 0, 0)`，与契约层一致（`attempts=0`、`tier=2` 的修复确实落地） |
| `idx_tasks_output_active` | 活跃态重复插入冲突；终态后同路径可再插；`SUCCEEDED` 与 `FAILED` 共享路径互不影响；`NULL` 不参与唯一 |
| 并发 CAS 领取 | 两线程 `BEGIN IMMEDIATE` + `UPDATE ... WHERE state='QUEUED'` → `[('w-B',1),('w-A',0)]`，`lease_epoch` 0→1，`claimed_by` 单值，无半更新 |
| 索引命中 | `WHERE pool=? AND state='QUEUED' ORDER BY is_key DESC, priority DESC, bottom_level DESC, created_at` → `SEARCH tasks USING INDEX idx_tasks_claim (pool=? AND state=?)`，**无 TEMP B-TREE** |
| 契约测试判别力 | 把 `tips.py` 的 `up to 10` 改成 `up to 3` → 2 failed（`test_tips_text_matches_code_constant`、`test_all_four_sources_agree`），确认真读文件 |
| 静默失败 | `schema.py` 全文只有 1 处 `except`（`current_version` 的 `OperationalError`），`_FALLBACK_*` 无残留，无第二处降级路径 |
| 基线 | 54 passed, 2 skipped, 1 xfailed |

`tips.py` 还原证据：`git diff fulilian_cli/tips.py` 只剩 PR 自身的 `-3 / +10` 一行改动，我的 `up to 3` 变异无残留（`cp /tmp/tips.py.bak` + `cmp` 字节一致）。

---

## P1（应在本 PR 修）

#### [P1-1] `lock` / `queueing_lock` 的唯一索引没有按活跃态收敛，"运行期互斥"退化成"一次性占用"

- 位置：`agent/orchestration/schema.py:184-195`
- 证据：

```python
        # M10 revised: run-time mutex (procrastinate's lock), e.g. one worktree.
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_lock
            ON tasks(lock)
         WHERE lock IS NOT NULL
        """,
```

（`idx_tasks_queueing_lock` 同构，只换列名。）实测：插 `t1` 为 `SUCCEEDED, lock='w1', queueing_lock='q1'`，再插 `t2` 为 `QUEUED` 复用同名键：

```
   lock reuse after terminal => BLOCKED: UNIQUE constraint failed: tasks.lock
   queueing_lock reuse after terminal => BLOCKED: UNIQUE constraint failed: tasks.queueing_lock
```

- 影响：`lock` 的注释写明语义是"run-time mutex，例如一个 worktree"。但索引是**全状态**唯一的，而 `lock` 是任务卡上的不可变属性（DDL 没有触发器、也没有任何写回约定会把它置 NULL），所以第一个占用 `'w1'` 的任务进入终态后，**此后任何任务都不能再占用 `'w1'`**。这不是互斥，是"每个 lock 值全生命周期只能用一次"；阶段 3 一旦把 worktree 路径当 lock，第二个任务起全部在 INSERT 处抛 `IntegrityError`。`queueing_lock` 同理：procrastinate 的 queueing_lock 在任务出队时释放，这里没有释放点，队列级去重变成永久去重，重派/重试永远插不进去。同一份 DDL 里 `output_path` 用的是 `WHERE state NOT IN (terminal)`，两种口径并存本身就是不一致。
- 建议：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_lock
    ON tasks(lock) WHERE lock IS NOT NULL AND state NOT IN ({terminal})
```

`queueing_lock` 同样加 `AND state NOT IN ({terminal})`。
**取舍（明确建议取约束层）**：第二条路是终局时由 store 把 `lock` / `queueing_lock` 置 NULL——语义层清理，允许历史留痕。我不建议：本项目原则是"能下沉到存储层的约束不要靠调用方记得"，而置 NULL 要求每条终态写回路径（成功 / 失败 / 取消 / 中断 / 租约过期回收，至少 5 条）都记得清列，漏一条就是永久锁死**且不会报错**（后续 INSERT 报的是 UNIQUE 冲突，离真正的漏点很远）；加 `AND state NOT IN (终态)` 由 SQLite 兜底，调用方忘了也不会坏。若两者都要，可并存：索引兜底 + 终态清列（清理只为留痕，正确性不依赖它）。
- 验证：新增用例，当前必红——`_insert_task(conn,"t1",state="SUCCEEDED",output_path=None,lock="w1")` 后 `_insert_task(conn,"t2",state="QUEUED",output_path=None,lock="w1")` 应通过。

#### [P1-2] `schema_version` 没有主键/唯一约束，`apply_schema` 读-写分离，多进程首次初始化会写入多行

- 位置：`agent/orchestration/schema.py:279-284`（建表）、`schema.py:352-366`（读-写）
- 证据：

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,      -- 无 PRIMARY KEY / UNIQUE
    applied_at REAL NOT NULL
)
```

```python
    applied = current_version(conn)          # 事务外读
    ...
    with conn:
        if applied is None:                  # 事务内写，中间无锁
            conn.execute("INSERT INTO schema_version ...")
```

实测 4 个线程同时 `apply_schema` 一个全新 DB（`/tmp/orch_init.db`）：

```
  errors: []
  schema_version rows after 4 concurrent inits: [(1,), (1,), (1,), (1,)] -> count = 4
  current_version() = 1
```

- 影响：本模块的设计前提就是"同机多进程"，每个进程启动都会 `apply_schema`。`current_version()` 的 SELECT 在事务之外，四个进程都读到 `None`，于是四行版本记录，表上无 PK/UNIQUE，SQLite 不拦。后果：(a) `test_apply_schema_is_idempotent` 断言的"恰好一行"在生产不成立，测试给了假安全感；(b) 版本表多行后，任何基于"这一行"的迁移审计/回滚都是错的；(c) 将来把迁移进度（pending 标记）挂到行上会直接自相矛盾。用 `MAX(version)` 读掩盖了这个问题，所以不会有人发现。
- 建议：`version INTEGER PRIMARY KEY`，写入改幂等语句 + 事务内重读消除 TOCTOU：

```sql
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)
```

```python
    with conn:
        conn.execute("BEGIN IMMEDIATE")      # 先拿写锁再判定
        applied = current_version(conn)
        ...
        conn.execute("INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                     (SCHEMA_VERSION, time.time()))
```

- 验证：4 线程并发 `apply_schema` 后断言 `SELECT COUNT(*) FROM schema_version == 1`。

#### [P1-3] `tasks` 缺 `depth` 派生列，而 `TaskCard.depth` 是被校验的契约字段

- 位置：`agent/orchestration/schema.py:113-159`（`tasks` DDL，38 列）；对照 `agent/orchestration/contracts.py:172`
- 证据：

```
  tasks 列数 = 38  含 depth? False
  TaskCard 有 depth 字段? True   TaskCard 有 batch_id 字段? False
```

`contracts.py:172` 是 `depth: int = 0`，`contracts.py:272` 有 `_check_non_negative_int(card, "depth")`——契约层把它当正式字段校验，存储层没有对应列。
- 影响：`schema.py` 自己的 H8 原则是"派生列是查询与排序的唯一真相，`card_json` 只是入队快照"，而 `depth` 是 `TaskCard` 里唯一"参与校验 + 影响调度（`max_spawn_depth`）+ 却没有派生列"的字段。现在只能 `json_extract(card_json,'$.depth')` 或沿 `parent_task_id` 递归 CTE，两者都不可索引；更要紧的是 **handoff 会改 parent**（`handoff_count` 列的存在即证明设计承认持有人会变），重挂后 parent 链长度 ≠ 逻辑 depth，递归推导会算错。我的判断：**更像"漏了"，不是"故意由 parent 链推导"**——若真是有意省略，H8 那段说明必须点名 depth 是例外，而它没有。
- 建议：加 `depth INTEGER NOT NULL DEFAULT 0` + `CREATE INDEX idx_tasks_depth ON tasks(depth)`（巡检/限流按深度扫），插入时从 card 派生。
- 验证：`PRAGMA table_info(tasks)` 含 `depth`；不带 depth 插入得 0；阶段 2 断言库里的 depth 等于 card 里的值。
- **为什么定 P1 而不是 P2**：本 PR 冻结 `schema_version=1`，而 `apply_schema` 没有 `applied < SCHEMA_VERSION` 的迁移分支（见 P2-3）。现在漏一列，后面补要先造一套迁移机制——补列的成本不在这一列，在迁移框架。

#### [P1-4] `batch_id TEXT NOT NULL` 无 DEFAULT，而契约层根本没有 batch 概念

- 位置：`agent/orchestration/schema.py:116`
- 证据：

```
  insert without batch_id => NOT NULL constraint failed: tasks.batch_id
  TaskCard 有 batch_id 字段? False
```

- 影响：单任务派发（`delegate_task(goal=...)`）是最常见路径，`TaskCard` 里没有 `batch_id`，存储层却强制非空且无默认 → 插入路径必须凭空造值。两条坏路：(a) 填 `''`——`NOT NULL` 放行、又没 `CHECK` 拦空串，于是所有单任务共享 `batch_id=''`，`list` 走 `WHERE batch_id=''` 会把它们全捞出来，"无批次"与"批次里只有一个任务"从此不可区分；(b) 填 `task_id`/uuid——语义正确（单任务自成一批），但这只是调用方约定，schema 不强制，两个插入点各写一种就开始漂移。你提到的"方案原文是 `batch_id TEXT`（可空）"我在 `docs/design/*.md` 里 grep 不到 DDL 原文，**无法核实**，所以只按"契约层无此概念"判。
- 建议：二选一并把语义写死。我倾向后者：

```sql
            batch_id  TEXT NOT NULL CHECK (batch_id <> ''),
```

并在 store 里规定"单任务以 `task_id` 作 `batch_id`"。理由：`list` 依赖 `idx_tasks_batch`，NULL 会让该索引的可用性打折，而空串会让批次语义彻底失效。
- 验证：不写 `batch_id` 应失败且错误明确；`batch_id=''` 应被 CHECK 拒绝；单任务用例断言 `batch_id == task_id`。
- **为什么不是 P0**：它大声失败（`IntegrityError`），不写坏数据、不静默降级；但它是"契约层与存储层对同一实体给出不同字段集"，阶段 2 的第一个单任务用例就会撞上。

---

## P2（记录，可排期）

#### [P2-1] "one transaction: either the whole schema lands or nothing does" 不成立，DDL 实际逐条自动提交

- 位置：`agent/orchestration/schema.py:359`
- 证据：`isolation_level=''`（legacy 模式）下 `with conn:` 只为 DML 隐式开事务：

```
  isolation_level = ''
  in_transaction after DDL inside with-block = False
```

预置陈旧表 `tasks(task_id, state)` 后调用 `apply_schema`：

```
  raised: OperationalError no such column: pool
  columns now: ['task_id', 'state']        # 前面已建的表/索引留在库里
```

- 影响：注释承诺原子性，实际是"失败前已建的部分保留"。当前因为全部 `IF NOT EXISTS`、版本行最后写，下次调用能自愈，后果有限；但"版本行没写 = 结构可能已半建"这一事实没人知道，任何基于该注释的推理都会错。
- 建议：改成 `conn.execute("BEGIN IMMEDIATE")` 显式包裹（SQLite 支持事务内 DDL），或把注释改成事实描述。
- 验证：`apply_schema` 抛错后 `SELECT COUNT(*) FROM sqlite_master WHERE type='index'` 应为 0。

#### [P2-2] `PRAGMA foreign_keys = ON` 是装饰性的：全库 0 个外键声明

- 位置：`agent/orchestration/schema.py:383`；`deliveries.task_id` / `task_commands.task_id` / `dispatch_log.task_id` 均无 `REFERENCES`
- 证据：`grep -c 'FOREIGN KEY\|REFERENCES' schema.py` → 0；孤儿投递被接受：

```
   orphan delivery (task_id=ghost) => ACCEPTED (no FK)
```

- 影响：`configure_connection` 打开外键开关，读者会以为引用完整性有保证。实际 `deliveries` 可以指向不存在的 task，清扫器/投递器会拿到悬空 `task_id`。这是本 PR 反复强调要消灭的"看起来有约束、实际不生效"同一类。
- 建议：给三张子表加 `REFERENCES tasks(task_id) ON DELETE CASCADE`；若刻意不加（删除策略未定），把 `PRAGMA foreign_keys = ON` 一并去掉并注明原因。
- 验证：插入 `task_id='ghost'` 的 delivery 应抛 `IntegrityError`。

#### [P2-3] `applied < SCHEMA_VERSION` 没有迁移分支，旧库静默停留在旧版本号

- 位置：`agent/orchestration/schema.py:352-366`（只有 `applied is None` 与 `applied > SCHEMA_VERSION` 两个分支）
- 证据：预置 `version=0` 后调用 `apply_schema`：

```
code version 1 -> db version after apply_schema: 0 rows: [(0,)]
```

- 影响：docstring 声称 `schema_version` 让"阶段 2..7 可以向前迁移而不是静默失败"，但代码里没有 `applied < SCHEMA_VERSION` 的处理：DDL 跑一遍（全 `IF NOT EXISTS`，等于没做），版本号原地不动，函数正常返回。真到需要迁移时，调用方拿到的是"成功"。
- 建议：显式加分支 `applied is not None and applied < SCHEMA_VERSION` → `raise SchemaError("需要迁移 v{applied} -> v{SCHEMA_VERSION}，本版本未提供迁移脚本")`。
- 验证：预置 `version=0` 后调用应抛 `SchemaError`。

#### [P2-4] claim 索引把 `state` 放在 `pool` 之后：不带 `pool` 等值的领取查询退化为全索引扫描 + 临时排序

- 位置：`agent/orchestration/schema.py:163-165`
- 证据（同一 DB 三条查询的 `EXPLAIN QUERY PLAN`）：

```
  pool+state   SEARCH tasks USING INDEX idx_tasks_claim (pool=? AND state=?)
  state only   SEARCH tasks USING INDEX idx_tasks_lease (state=?)
               USE TEMP B-TREE FOR ORDER BY
  lease sweep  SEARCH tasks USING INDEX idx_tasks_lease (state=? AND lease_expires<?)
```

- 影响：按 pool 领取是正解；但只要存在"任意 pool 取一个任务"的入口（supervisor 抢活、单 pool 退化、跨 pool 优先级），就变成全索引扫描 + 排序，任务量上来后每次领取 O(n log n)。
- 建议：确认领取路径恒带 `pool = ?`（写进注释并由阶段 2 测试锁住）；若允许跨 pool，补 `idx_tasks_claim_any ON tasks(state, is_key DESC, priority DESC, bottom_level DESC, created_at)`。
- 验证：把"不带 pool"的领取查询写进阶段 2 测试，断言 plan 里没有 `TEMP B-TREE`。

#### [P2-5] `current_version` 把 `OperationalError` 一律翻译成"未初始化"

- 位置：`agent/orchestration/schema.py:337-341`
- 证据：

```python
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return None
```

- 影响：`no such table`、`database is locked`、`no such column` 都被当作"全新库"。前者合理，后两者会让 `apply_schema` 在锁住/损坏的库上继续走建表流程，最终以一个无关的 `OperationalError`（如 P2-1 的 `no such column: pool`）冒出来，调用方无法区分"版本太旧"与"磁盘/并发问题"。
- 建议：只吞 `no such table: schema_version`（`"no such table" in str(exc)`），其余包装成 `SchemaError`。
- 验证：对只读/被锁的库调用 `current_version`，应得 `SchemaError` 而非 `None`。

#### [P2-6] `test_invariants.py` 里被 skip 的用例是同义反复，unskip 时不会带来任何保护

- 位置：`tests/orchestration/test_invariants.py:77-90`
- 证据：

```python
@pytest.mark.skip(reason="阶段 2：store.claim / redispatch 落地后启用（当前无写入方）")
def test_attempts_gte_handoff_count_plus_one(conn):
    _insert_task(conn, "t1", attempts=1, handoff_count=0)
    assert row[0] >= row[1] + 1        # 1 >= 1，恒真
```

- 影响：断言对象是测试自己刚写进去的 `(1, 0)`，与引擎无关。阶段 2 有人照 reason 的提示"启用"它，得到的是一条永远绿的用例——正是任务书 P1-8 说的"改了实现也不会红"。相比之下第 2 条的 `xfail(strict=True)` + 反向用例是正确写法（缺口被钉住，补上约束会 XPASS 变红），应推广到第 1、3 条。
- 建议：改成"断言当前缺口存在"（如断言 `attempts=0, handoff_count=5` 也能插进去），阶段 2 补约束后自然变红；或直接删掉，等阶段 2 用真实领取序列重写。
- 验证：以 `attempts=0, handoff_count=5` 插入，当前应成功（说明无约束）。

#### [P2-7] 派生列与 JSON 列缺少取值域约束

- 位置：`agent/orchestration/schema.py:118-124`、`129-131`、`151`
- 证据：`tier`、`isolation`、`priority`、`pool`、`role` 均无 CHECK；`card_json` / `cursor_json` / `result_json` 无 `json_valid`（`grep -c json_valid` → 0）。
- 影响：`isolation='proces'`、`tier=99`、`card_json='not json'` 都能写进去，查询层拿到非法值才炸，此时数据已落库。`state` 做了 CHECK 而邻居列没有，会让读者误以为整张表的取值域都被约束了。
- 建议：至少补 `CHECK (isolation IN ('process','thread','inproc'))`、`CHECK (tier BETWEEN 1 AND 3)`、`CHECK (json_valid(card_json))`。
- 验证：插入 `isolation='proces'` 应抛 `IntegrityError`。

#### [P2-8] `output_path` 可空，H7 的部分唯一索引对 NULL 行静默失效；测试把这个缺口固化成了期望行为

- 位置：`agent/orchestration/schema.py:131`、`174-177`；`tests/orchestration/test_schema.py:213-215`
- 证据：连插 3 行 `output_path=NULL` 全部成功——`3 rows with output_path=NULL => inserted 3`；而契约层 `contracts.py:253-256` 明确要求非空且绝对路径（`output_path 不能为空` / `必须是绝对路径`）。
- 影响：不是当前活 bug——NULL 语义是"本任务不产出文件"，本来就不该参与"一文件一写者"，唯一索引豁免它是对的。真正的缺陷是**两层要求不一致**：契约层说"必须有绝对路径"，存储层说"可以没有"。任何绕过 `validate_card` 的写入路径（阶段 2 从 `card_json` 恢复重派、迁移脚本、手工修库、别的进程直接写库）都会造出契约层认为不可能存在的行，H7 的写冲突防护对它们完全失效。更值得注意的是 `test_null_output_path_is_not_unique` 把"NULL 可以很多"写成断言，等于给缺口上了锁——将来若收紧为 NOT NULL，这条测试会以"保护既有行为"的名义挡路。
- 建议：加轻量 CHECK（SQLite 无 `isabs`，只能查前导斜杠），或至少在 DDL 注释写明"NULL 是合法值，语义=本任务不产出文件，H7 不适用"，并把测试名/注释改成守"无产出任务不受 H7 约束"而非"NULL 逃过唯一约束"：

```sql
            output_path TEXT CHECK (output_path IS NULL
                                    OR (output_path <> '' AND substr(output_path, 1, 1) = '/')),
```

- 验证：插入 `output_path=''` 与 `'relative/path.md'` 均应被拒绝。
- 定级理由：防御纵深缺口而非活 bug，不到 P1——但它是"看起来有约束、实际不生效"同一类，且被测试固化，所以不能只当 P3。

---

## P3（风格/注释）

- **[P3-1]** `schema.py:160` 注释 "Claim scan: key tasks first, then aged priority, then critical path." —— 索引里没有任何 aging 项，`created_at` 只做 tie-break。aging 只能靠写路径改 `priority`；建议改成"aging 由写路径更新 priority 实现，索引只按当前值排序"。
- **[P3-2]** `schema.py:384` `PRAGMA synchronous = NORMAL` 由 guest connection 设置，与 `configure_connection` 自己的论证（"durability 归 DB 文件 owner 决定"）冲突；`journal_mode` 被拿掉了，`synchronous` 却留着，口径不一致。
- **[P3-3]** `schema.py:125` `state TEXT NOT NULL DEFAULT 'QUEUED'` 的默认值是硬编码字面量，而 CHECK 是契约派生的。枚举改名时 CHECK 跟着变、DEFAULT 不变，报错点离现场很远。

---

## 待确认（不进 P0–P3）

1. **`lock` 是否约定"终态置 NULL"**：若阶段 2 的 store 有硬约定（领取/完成时清列），P1-1 可降为"文档缺失"。但 DDL 与契约层都没有强制或说明，我按缺陷报，需阶段 2 设计者确认。
2. **fencing 在 DB 层完全无强制**：实测 `UPDATE tasks SET result_json='{"zombie":true}' WHERE task_id='t1'`（不带 epoch 条件）成功更新 1 行。这是预期内的应用层职责，但 docstring 大段讲 B1 fencing，读者容易误以为表结构提供了保护。建议加一句"schema 不提供 fencing，写回必须带 `WHERE lease_epoch = ?`"。
3. **部分唯一索引与原地重派**：`FAILED -> QUEUED`（H5 允许的重试边）若发生在"该 `output_path` 已被另一个活跃任务占用"时，UPDATE 会抛 `IntegrityError`，状态机没有这条边的失败语义，属阶段 2 决策，未判为缺陷。

---

## 一句话总评

存储层骨架经得起实测（并发 CAS 领取只有一方成功、`lease_epoch` 原子递增、`state` CHECK 拦得住大小写与空串、claim 索引零临时排序），但 `lock`/`queueing_lock` 的全局唯一索引把"运行期互斥"做成了"一次性占用"，`schema_version` 无唯一约束导致多进程初始化写多行，再加上 `depth` 缺列与 `batch_id` 无默认这两处"契约层有、存储层没有（或有而更严）"的错位——**前两条不修，阶段 2–3 会在 INSERT 处和版本表上出事故；后两条不修，阶段 2 的第一个单任务用例和第一次深度巡检就会撞上，且补列要先造迁移框架**。

---

主控交叉探针补充项：3 条（`depth` 缺列 / `batch_id` 无默认 / `output_path` 可空），已独立复现，编号 P1-3、P1-4、P2-8，全部确认成立，无反驳。
