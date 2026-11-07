# PR-1 代码审查 · 合并结论

> 审查方式：两名独立审查员分片审查（A 契约/状态机/配置，B 存储/约束），主控做交叉探针复核。
> 分片报告：`notes/orchestration-pr1-code-review-a.md`（224 行）、`-b.md`（262 行）。
> 任务书：`docs/design/orchestration-pr1-code-review-brief.md`。

---

## 一、结论

**不建议按当前状态合入。** 卡 1 条 P0：崩溃恢复主路径在状态机层没有刹车，而文档声称有。

除此之外代码质量高于预期——约束、索引、CHECK、并发领取、`lease_epoch` 原子性都实测通过，测试判别力也经过变异探针验证。问题集中在**"文档承诺"与"表实际约束"之间的缝隙**，不是实现错误。

| 级别 | 条数 | 说明 |
|---|---|---|
| P0 阻塞 | 1 | 崩溃循环无上限，且文档写反了 |
| P1 重要 | 8 | 3 条默认值/口径分裂、2 条安全校验缺失、2 条约束失效、2 条契约-存储脱节 |
| P2 改进 | 16 | 恒真断言、迁移缺口、索引细节、错误吞噬、NULL 绕过唯一索引 |
| P3 建议 | 5 | 注释、命名、哨兵值 |
| 待确认 | 4 | 审查员无法判定、需设计决策的项 |

**值得记录的对比**：本次审查发现的 9 条 P1 里，**有 6 条是"两处写同一件事、值不一样"**（`isolation` 默认、`max_retries` 三处、`lock` 索引口径、`output_path` 可空性、`depth` 有无、`batch_id` 可空性）。这正是本次改造要消灭的病，而它在修复过程本身里又长出来了——**收敛真相源的动作，自己最容易产生新的真相源**。

---

## 二、P0（必修）

### [P0-1] 崩溃恢复主路径无上限，且 `state_machine.py` 的说明与转移表相反

- 位置：`agent/orchestration/state_machine.py:9`（说明）vs `:37-62`（转移表）
- 证据：`RUNNING → BLOCKED` 与 `BLOCKED → QUEUED` 两条边**都没有守卫**；唯一带 `attempts` 闸的是 `FAILED → QUEUED`。而模块 docstring 写着"崩溃循环由 attempts / handoff_count 上限兜住"。
- 实测（审查员 A）：连续 50 个崩溃周期、`attempts=99`、`max_retries=0`，`RUNNING→BLOCKED→QUEUED` 全部通过，一次未被拒。
- 影响：阶段 4 若照 docstring 实现，会得到一个**无限重派循环**——进程每次崩溃都自动重排，永不收敛，且每次重派都消耗完整上下文与 token。这不是理论风险：`kill -9` 一个卡住的 worker 就会触发。
- 建议（三选一，按推荐度排序）：
  1. **给 `BLOCKED → QUEUED` 加守卫** `handoff_count < handoff_cap`，让表自己兜住（推荐：约束下沉到状态机，不依赖 `redispatch` 记得）；
  2. 若坚持由 `redispatch` 守，则**删掉 docstring 那句话**，改成"本模块不限制回收次数，由 redispatch 的 handoff_cap 负责"——不能让文档承诺一个不存在的行为；
  3. 两者都做（表兜底 + 策略控制），并加一条测试：连续 `BLOCKED→QUEUED` 到 `handoff_cap` 后必须拒绝。
- 验证：`transition(BLOCKED, QUEUED, handoff_count=cap)` 必须抛 `IllegalTransitionError`；`handoff_count=cap-1` 必须放行。

---

## 三、P1（应在本 PR 修）

### 3.1 默认值与口径分裂（4 条）

| 编号 | 问题 | 证据 | 建议 |
|---|---|---|---|
| A-P1-1 | `max_retries` 三处默认值不同 | `transition(max_retries=1)` / `TaskCard.max_retries=0` / `config.retry_cap=1` | 统一为 1（"允许 1 次重试"），并让 `transition` 的默认值改为必传（去掉默认，强制调用方显式给出）——默认值朝"放行"方向偏是最危险的默认 |
| A-P1-2 | `isolation` 契约默认 `INLINE`，DDL 默认 `'process'` | `contracts.py:161` vs `schema.py:124` | **改契约默认值为 `None`**（= 自动推断），恢复方案 §4.5 的 fail-safe：未声明 → `PROCESS`。当前写法等于绕过了推断逻辑，不写 `isolation` 的任务会在主进程里跑，一次段错误拖垮整队 |
| 主控-1 | `tasks.depth` 列不存在 | `PRAGMA table_info(tasks)` 38 列无 `depth`；而 `contracts.py:172` 有 `depth: int = 0`、`:272` 还校验 `depth >= 0` | 加 `depth INTEGER NOT NULL DEFAULT 0`。**不能用 parent 链递归推导**：handoff 会改 `parent_task_id`，重挂后的链长 ≠ 逻辑 depth，递归会算错。补列成本不在列本身，在迁移框架（见 P2-3） |
| 主控-2 | `batch_id TEXT NOT NULL` 无默认，且**空串放行** | 不带 `batch_id` 插入直接 `IntegrityError`；但 `batch_id=''` 能通过，无 CHECK 拦 | 定级 P1（大声失败、不写坏数据）。**真正的坑是空串**：所有单任务共享 `batch_id=''`，`list` 一次全捞，且「无批次」与「单任务批次」不可区分。建议 `CHECK (batch_id <> '')` + 单任务以 `task_id` 作 batch_id，语义写死在注释里 |

### 3.2 安全校验缺失（2 条）

| 编号 | 问题 | 证据 | 建议 |
|---|---|---|---|
| A-P1-3 | `output_path` 只查 `os.path.isabs`，不查归一化 | `/tmp/../../etc/passwd` 是绝对路径，通过校验 | 加 `os.path.normpath` 后比对，拒绝 `..` 段；或强制 `realpath` 落在允许根目录内 |
| A-P1-4 | `validate_card` 完全不校验 `goal` / `role` / `isolation` / `priority` / `tier` | 构造 `goal=""` 的卡通过校验 | 至少校验 `goal` 非空、`role`/`isolation` 是合法枚举值、`priority` 为 int、`tier` 在 1–3 |

### 3.3 约束失效（1 条 P1 + 1 条 P2）

| 编号 | 问题 | 证据 | 建议 |
|---|---|---|---|
| B-P1-1 | `idx_tasks_lock` / `idx_tasks_queueing_lock` 只写 `WHERE ... IS NOT NULL`，未收敛活跃态 | 实测：`t1` 终态后仍占着 `lock='w1'`，`t2` 用 `'w1'` 直接 UNIQUE 冲突 | 加 `AND state NOT IN (终态)`。否则"运行期互斥"退化成"每个 lock 值全生命周期只能用一次"，阶段 3 第二个任务起全部 INSERT 失败 |
| 主控-3（**P2**，审查员 B 复核后下调） | `output_path` 可空，部分唯一索引对 NULL 静默失效 | 连插 3 行 `output_path=NULL` 全部成功（SQLite 中 NULL 互不相等）；且 `test_null_output_path_is_not_unique` 把这个缺口**写成了断言** | 加 `NOT NULL`，或让索引 `WHERE output_path IS NOT NULL AND state NOT IN (...)` 并注明 NULL 不受保护。**注意那条测试**：它把缺陷固化成期望，将来收紧会以「保护既有行为」挡路——这正是评审里说过的变更探测器，修约束时要一并删掉 |

### 3.4 契约完整性（1 条）

| 编号 | 问题 | 建议 |
|---|---|---|
| A-P1-5 | `validate_card` 放行 list 型 `dod`，`TaskCard(dod=["a"])` 能构造成功但 `hash()` 崩——违背模块自己声明的"可 hash"契约 | `validate_card` 里强制 `isinstance(card.dod, tuple)`；或 `__post_init__` 里做 `tuple()` 转换（frozen dataclass 需 `object.__setattr__`） |

---

## 四、P2（记录，可排期）

按主题归并，不逐条展开（细节见分片报告）：

**A. 测试判别力（3 条，最值得先修）**
- `test_is_terminal_matches_contracts` 与实现同源（`from contracts import TERMINAL_STATES` 后自比），零判别力；
- `test_task_card_is_hashable_with_full_field_set` 恒真（实测改坏实现仍绿）；
- `test_invariants.py` 里被 skip 的用例是同义反复，unskip 时不会带来任何保护。
→ **建议**：这三条要么改成"能失败"的形式，要么删掉。留着恒真断言比没有更糟——它让人误以为有覆盖。

**B. 迁移与事务（3 条）**
- `apply_schema` 注释声称"one transaction: either the whole schema lands or nothing"，实际 DDL 逐条自动提交，中途失败会留下半套表；
- `applied < SCHEMA_VERSION` 没有迁移分支，旧库静默停在旧版本号；
- `current_version` 把 `OperationalError` 一律翻译成"未初始化"，会吞掉真实的库损坏。

**C. 索引与约束细节（3 条）**
- `idx_tasks_claim` 把 `state` 放在 `pool` 之后：带 `pool` 等值时命中良好，**不带 `pool`** 时退化为全索引扫描 + 临时排序（阶段 3 的全局领取会踩）；
- `PRAGMA foreign_keys = ON` 是装饰性的——全库 0 个外键声明；
- 派生列（`role` / `pool` / `tier` / `is_key` / `priority` / `isolation`）与 `card_json` 之间无取值域约束，`card_hash` 也没在 DDL 层强制。

**D. 配置健壮性（4 条）**
- `validate()` 放行 `NaN` / `inf`（租约时长变 NaN 会让判死逻辑彻底失效）；
- `from_mapping` 返回的可能仍是非法配置，范围校验被推迟到调用方主动 `validate()`；
- `pools` 重名静默合并，`pool_map()` 丢配额且不报错；
- `db_path` 可以指向 `state.db`，与模块自己写下的"never reuse state.db"承诺无任何强制。

**E. 其他（2 条）**
- `attempts` / `max_retries` 无类型与范围校验：`attempts=-1` 可绕过守卫，`attempts=0.5` 被接受；
- `HandoffPolicy` 有两处真相源（`Literal` + `_HANDOFF_POLICIES`），且未进 `__all__`。

---

## 五、待确认（需设计决策，不计入 P0–P3）

1. **`depth` 是否故意不存**：若设计意图是"由 `parent_task_id` 链推导"，则 M2 需要递归 CTE，且 `max_spawn_depth` 校验会变成一次查询——性能与复杂度都高于存一列。审查员倾向"漏了"，但无法从代码判断意图。
2. **`lock` 的语义边界**：是"运行期互斥"（终态释放）还是"幂等键"（永久占用）？当前 DDL 实现的是后者，注释写的是前者。
3. **`queueing_lock` 与 `idempotency_key` 是否重复**：两者都是排队期去重，保留两列的理由未在注释中说明。
4. **单任务是否允许无 `batch_id`**：若允许，`idx_tasks_batch` 的查询语义要重新定义（不能假定"一个 batch 至少两个任务"）。

---

## 六、审查质量评估（对审查本身的审查）

**做对的**：
- 两名审查员都做了**变异探针**（改坏实现确认测试变红），不是只跑测试。审查员 A 报"5 组变异中 4 组能红、hash 相关恒真"，审查员 B 报"改坏 `tips.py` 后 2 条变红并已字节还原"——这是本轮最可信的部分。
- 审查员 B 发现的两条 P1 都是**只有实际插入才能发现**的问题（索引口径、并发写版本表），光读 DDL 看不出来。
- 审查员 A 的 P0 是**把文档承诺和代码行为对照**得出的，不是读代码读出来的——这类问题最难被自动工具发现。

**漏掉的**：
- 主控交叉探针撞出 3 条（`depth` 缺失、`batch_id NOT NULL`、`output_path` 可空），**都落在 B 的分片范围内**。说明分片 B 的检查清单里缺少"契约字段 ↔ DDL 列"的逐项对照。
- 这不是审查员能力问题，是**任务书的检查项不够具体**：我写了"约束是否真的生效"，但没写"逐字段核对 contracts 的每个字段在 DDL 里有没有落点"。

**下次改进**：任务书里应加一条硬性检查项——"把 `TaskCard` 的每个字段与 `PRAGMA table_info(tasks)` 做双向差集，两个方向都要为空"。这类机械核对交给脚本比交给人可靠。

---

## 七、修复顺序建议

| 顺序 | 内容 | 理由 |
|---|---|---|
| 1 | P0-1 崩溃循环上限 | 决定阶段 4 的实现形态，越晚改越贵 |
| 2 | A-P1-2 `isolation` 默认值 | 契约默认值是最难改的东西，现在改是 1 行，阶段 5 改要迁移 |
| 3 | 主控-1 / 主控-2（`depth`、`batch_id`） | DDL 加列，趁没有数据 |
| 4 | B-P1-1 / 主控-3（锁索引、`output_path` 非空） | 约束层，同上 |
| 5 | A-P1-1 三处 `max_retries` 统一 | 与 P0-1 同批做，避免两次动状态机 |
| 6 | A-P1-3/4/5 校验补强 | 纯 `validate_card` 内部，无外部影响 |
| 7 | P2 里的 3 条恒真断言 | 测试可信度，越早越好 |

修完应重跑：`pytest tests/orchestration tests/agent/test_delegation_config_contract.py`（当前 155 passed / 2 skipped / 1 xfailed）。
