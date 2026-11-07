# 阶段 2a 冻结决议 · `store.py` 存储与领取契约

> 主控裁定，**实现者不得自行改动**。凡与本文件冲突的实现一律返工。
> 上游：`orchestration-implementation-plan.md` §阶段 2；`orchestration-pr1-acceptance.md` §八（五条硬门禁）。
> 下游：阶段 3 的 `dispatcher.py` 直接调用本模块，**签名一旦落地即视为公开 API**。

---

## 一、模块边界

`agent/orchestration/store.py` —— **只做存储与领取**，不做调度决策、不跑任务、不碰 `tools.*`。

```
grep -rn "from tools\|import tools" agent/orchestration/   # 必须无输出
```

`store.py` 是数据库的**唯一持有者**：只有它设置 `journal_mode` / `busy_timeout`。

---

## 二、公开 API（冻结，逐字实现）

```python
class StoreError(Exception): ...
class FencedOutError(StoreError): ...      # lease_epoch 不匹配，写回被拒
class NotClaimableError(StoreError): ...   # 任务当前状态不允许该动作
class SchemaMismatchError(StoreError): ... # 库版本与代码不符


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    task_id: str
    lease_epoch: int          # fencing token，写回时必须回传
    attempts: int             # 本次 claim 之后的执行次数
    worker_id: str
    card: TaskCard


class Store:
    def __init__(
        self,
        db_path: str,
        *,
        worker_id: str,
        now: Callable[[], float] = time.time,
    ) -> None: ...

    def close(self) -> None: ...

    # ---- 入队 ----
    def enqueue(
        self,
        card: TaskCard,
        *,
        batch_id: str | None = None,      # None → 用 card.task_id（单任务）
        deps: tuple[str, ...] = (),
    ) -> None: ...

    # ---- 领取 ----
    def claim(
        self,
        pool: str,
        *,
        lease_seconds: int = 300,
        max_wait_seconds: float = 0.0,    # 0 = 立即返回 None，不阻塞
    ) -> ClaimedTask | None: ...

    # ---- 租约 ----
    def heartbeat(self, task_id: str, epoch: int, *, lease_seconds: int = 300) -> None: ...

    # ---- 执行生命周期 ----
    def start(self, task_id: str, epoch: int) -> None: ...            # CLAIMED -> RUNNING
    def complete(
        self,
        task_id: str,
        epoch: int,
        *,
        output_path: str,
        result_json: str | None = None,
    ) -> None: ...                                                    # RUNNING -> SUCCEEDED
    def fail(self, task_id: str, epoch: int, *, reason: str) -> None: ...  # RUNNING -> FAILED/QUEUED

    # ---- 判死与回收 ----
    def patrol(self, *, limit: int = 100) -> int: ...                 # 租约过期 -> BLOCKED，返回处理条数
    def redispatch(self, task_id: str, *, handoff_cap: int | None = None) -> None: ...  # BLOCKED -> QUEUED
```

**签名不得增删参数、不得改默认值。** 需要更多能力时先提，不要私自加。

---

## 三、十条实现决议

### D1 · 连接设置：WAL + busy_timeout，只有 store 设

```python
conn.execute("PRAGMA journal_mode=WAL")     # 持久化属性，只在建库/首次打开时生效
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA foreign_keys=ON")
```

`schema.py` 的 `configure_connection()` **刻意不设 journal_mode**（那是库持有者的职责）。`store.py` 是持有者，所以由它设。测试里用 `:memory:` 时 WAL 无效（SQLite 限制），**要测并发必须用文件库**。

### D2 · claim 必须先读后写（硬门禁③）

**空队列时绝不允许开写事务。** 顺序固定：

1. 廉价探测：`SELECT 1 FROM tasks WHERE state='QUEUED' AND pool=? LIMIT 1`
   - 无行 → 退避后返回 `None`，**零写事务**
2. 有行才 `BEGIN IMMEDIATE`
3. 在事务内重新 `SELECT task_id ... ORDER BY is_key DESC, priority DESC, bottom_level DESC, created_at ASC LIMIT 1`（**必须重查**，探测到的事务开始之间可能被别人抢走）
4. `UPDATE ... WHERE task_id=? AND state='QUEUED'`
5. `rowcount != 1` → `ROLLBACK` 并返回 `None`（被别人抢先，不是错误）
6. `COMMIT`

退避：指数 + 抖动，`min(0.05 * 2**n, 2.0) * random(0.5, 1.5)`，`max_wait_seconds` 到了就返回 `None`。

### D3 · `attempts` 在 claim 时 +1（硬门禁①）

`attempts` 的语义是"已发起的执行次数"。claim 即一次执行尝试——**claim 后崩溃的 worker 消耗一次重试是正确的**，否则坏 worker 可以无限重试。

```sql
UPDATE tasks SET
    state = 'CLAIMED',
    claimed_by = :worker_id,
    claimed_at = :now,
    lease_expires = :now + :lease_seconds,
    lease_epoch = lease_epoch + 1,
    attempts = attempts + 1,
    updated_at = :now
WHERE task_id = :task_id AND state = 'QUEUED'
```

`attempts` 必须在**同一条 UPDATE 里**递增，不得先读后写——否则两个 worker 并发 claim 会读到同一个旧值。

### D4 · `lease_epoch` 是 fencing token，每次 claim +1

同样在上面的 UPDATE 里原子递增。返回给调用方后，**任何写回都必须带上它**。

### D5 · 所有写回带 epoch 校验（硬门禁②）

```sql
UPDATE tasks SET ... WHERE task_id = :task_id AND lease_epoch = :epoch
```

`rowcount == 0` → 抛 `FencedOutError`。**不允许**用"先 SELECT 再判断"代替——那有 TOCTOU 窗口。

`heartbeat` / `start` / `complete` / `fail` 四个方法全部适用。

### D6 · 状态变更必须走 `transition()`

不得直接 `UPDATE tasks SET state='X'`。每次状态变更前调用：

```python
transition(current, target, lease_expired=..., attempts=..., max_retries=..., handoff_count=..., handoff_cap=...)
```

注意 `max_retries` 现在是**必传参数**（无默认值）。`handoff_cap` 取 `card.max_handoffs`，`handoff_count` 取行内值。

### D7 · 判死落 `BLOCKED`，不是 `INTERRUPTED`（硬门禁④）

`patrol()` 扫 `state IN ('CLAIMED','RUNNING') AND lease_expires < now`，**但两条路径的落点不同**（原决议写错，已修正）：

| 崩溃时状态 | 路径 | 理由 |
|---|---|---|
| `RUNNING` | `RUNNING → BLOCKED`，写 `block_reason='lease_expired'` | 任务跑过，是故障，需要 redispatch 决策；消耗 `handoff_cap` 预算 |
| `CLAIMED` | `CLAIMED → FAILED`，若 `attempts <= max_retries` 再 `FAILED → QUEUED` | **表里没有 `CLAIMED → BLOCKED` 这条边**（`_ALLOWED[CLAIMED]` = {RUNNING, QUEUED, FAILED}）。任务是"领了没跑就死"，本质是一次作废的尝试，不是故障 |

**原决议的错误**：原文写"两条路径都落 `BLOCKED`"，但 `_ALLOWED[CLAIMED]` 里没有 BLOCKED，**该要求不可实现**。执行者发现后按合法边处理并留了 `DEVIATION` 注释，主控复核确认其方案正确，据此修正本节。

`CLAIMED` 路径**必须**是有界的：`attempts` 在 claim 时已 +1（D3），所以 `FAILED → QUEUED` 的重试闸会自然收敛；一旦 `attempts > max_retries` 就停在 `FAILED` 被吸收。若图省事直接 `CLAIMED → QUEUED`（"放弃领取"边），则绕过了 `attempts` 闸，会重新引入无限循环。

**共同理由**：两者都不能落 `INTERRUPTED`。它是空出边终态，任务会永久卡死、只能人工新建——这会让"kill -9 后重启可接管"（验收④）无法成立。

### D8 · `redispatch` 受 `handoff_cap` 守卫，且 `handoff_count +1`

```sql
UPDATE tasks SET
    state = 'QUEUED',
    handoff_count = handoff_count + 1,
    claimed_by = NULL,
    lease_expires = NULL,
    block_reason = NULL,
    updated_at = :now
WHERE task_id = :task_id AND state = 'BLOCKED'
```

调用 `transition(BLOCKED, QUEUED, handoff_count=..., handoff_cap=..., ...)` 先校验，超上限抛 `IllegalTransitionError`。

**`handoff_count` 必须与状态变更在同一条 UPDATE 里递增。**

### D9 · `fail()` 的重试判定

`RUNNING → FAILED` 之后，若 `attempts <= max_retries` 则再 `FAILED → QUEUED`；否则停在 `FAILED`（吸收态）。

两次 `transition()` 调用都要做，**不能跳步直接置 QUEUED**。

### D10 · 迁移 runner 最小实现

`SCHEMA_VERSION = 1`，无存量库。要求：

- `Store.__init__` 调 `apply_schema()`（幂等）
- 读 `schema_version` 最大值：`> SCHEMA_VERSION` → 抛 `SchemaMismatchError`；`< SCHEMA_VERSION` → 抛 `SchemaMismatchError`（无迁移分支，不静默）
- **不允许** `except Exception: pass`

---

## 四、验收（全部必须满足，缺一不算完成）

| # | 指标 | 判定方式 |
|---|---|---|
| ① | 8 进程抢同一批任务，每个任务成功数恰为 1 | 多进程脚本，`claimed_by` 去重后计数 |
| ② | 被 fence 的 worker 写回失败 | 用旧 epoch 调 `complete()` → 必须抛 `FencedOutError` |
| ③ | 空队列 15 worker × 10 分钟，写事务 < 100 | 用 `sqlite3` 的 `PRAGMA data_version` 或包装计数；**10 分钟太长，测试里用 60 秒等价折算，并说明折算依据** |
| ④ | kill -9 后重启可接管 | 子进程 claim 后 `os.kill(SIGKILL)`，父进程 `patrol()` 判死 → `BLOCKED` → `redispatch()` → 可被重新 claim |
| ⑤ | 端到端吸收态 | 连续 claim/fail 到超过 `max_retries`，任务落 `FAILED` 且 `claim()` 再也取不到 |

**③ 的等价折算必须写在测试注释里**：60 秒内写事务数 × 10 < 100，即 60 秒内 < 10 次写事务。

### 必须新增的测试（函数名固定）

```
test_claim_increments_attempts_atomically
test_claim_returns_none_without_write_when_queue_empty
test_concurrent_claim_single_winner
test_stale_epoch_write_is_fenced
test_patrol_lands_in_blocked_not_interrupted
test_patrol_ignores_live_lease
test_redispatch_rejected_at_handoff_cap
test_fail_retries_then_absorbs
test_end_to_end_absorption
test_schema_mismatch_raises
```

---

## 五、禁止事项

1. **不得直接 UPDATE `state`**，一律走 `transition()`。
2. **不得在空队列时开写事务**（硬门禁③，10 分钟压测就是为它设的）。
3. **不得用 `SELECT` 代替 epoch 校验**（TOCTOU）。
4. **不得吞异常**。`except Exception: pass` / 静默降级一律返工——PR-1 已因此被拦过一次。
5. **不得改 `schema.py` / `contracts.py` / `state_machine.py`**。发现契约有问题，报给主控，不要自己改。
6. 不得引入第三方依赖（`sqlite3` + 标准库够用）。

---

## 六、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```

Python `./venv/bin/python`（3.11.15）。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

并发测试**必须用文件库**（`tempfile.mkdtemp()` 下），`:memory:` 无法跨进程共享。
