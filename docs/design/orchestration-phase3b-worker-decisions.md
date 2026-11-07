# 阶段 3b 冻结决议 · `dispatcher.py` + `worker.py` + 三档承载

> 主控裁定，实现者不得自行改动。
> 上游：`orchestration-implementation-plan.md` §阶段 3；`orchestration-phase3a-control-decisions.md`（控制通道已就位）。
> 下游：阶段 4 的 `patrol/redispatch` 直接复用本阶段的 worker 循环。

---

## 一、先厘清一个概念混淆（这是本阶段最容易做错的地方）

计划里写的"worker 三档承载（inline/embedded/daemon）"和 `contracts.Isolation`（`INLINE` / `PROCESS`）**不是同一个维度**：

| 维度 | 取值 | 回答的问题 |
|---|---|---|
| `Isolation`（契约字段） | `INLINE` / `PROCESS` | 任务**在哪里**执行——父进程内，还是独立子进程 |
| 承载档位（本阶段引入） | `inline` / `embedded` / `daemon` | worker **以什么形态**存在——同步、后台线程、常驻进程 |

对应关系不是一一映射：

- `Tier.INLINE` → `Isolation.INLINE`，同步执行，**不产生 worker**
- `Tier.EMBEDDED` → `Isolation.INLINE`，同进程后台线程，进程内共享 `Store`
- `Tier.DAEMON` → `Isolation.PROCESS`，独立进程，**自己开连接、自己 claim**

`embedded` 与 `daemon` 的区别不是隔离级别，是**生命周期**：线程随调用方退出，进程可以跨调用存活、可以空闲自杀。

---

## 二、模块边界

| 文件 | 职责 | 不做什么 |
|---|---|---|
| `dispatcher.py` | 批量采样（只读）、退避、档位判定 | **不 claim、不执行、不改状态** |
| `worker.py` | claim → 执行 → heartbeat → poll 指令 → complete/fail/cancel | 不决定用哪一档，不自己起进程 |
| `launcher.py` | 按档位起停（同步 / 线程 / 进程），daemon 空闲自杀 | 不碰任务状态 |

**三个文件都不得 import `tools.*`。**

---

## 三、公开 API（冻结）

```python
# ---- dispatcher.py ----
class Tier(enum.Enum):
    INLINE = "inline"
    EMBEDDED = "embedded"
    DAEMON = "daemon"


@dataclass(frozen=True, slots=True)
class Backoff:
    base: float = 0.05
    cap: float = 2.0
    def delay(self, attempt: int, *, rand: Callable[[], float] = random.random) -> float: ...


class Dispatcher:
    def __init__(self, store: Store, *, backoff: Backoff | None = None,
                 now: Callable[[], float] = time.time) -> None: ...
    def choose_tier(self, card: TaskCard, *, requested: Tier | None = None) -> Tier: ...
    def sample(self, pool: str, *, limit: int = 32) -> list[str]:
        """只读采样：返回可领取的 task_id，**不改任何状态**。"""
    def poll_delay(self, attempt: int) -> float: ...


# ---- worker.py ----
@dataclass(frozen=True, slots=True)
class WorkerContext:
    store: Store
    control: Control
    worker_id: str
    task_id: str
    lease_epoch: int
    cancelled: threading.Event      # stop 指令置位
    steers: list[str]               # 已消费的 steer 文本，按到达顺序


@dataclass(frozen=True, slots=True)
class TaskResult:
    ok: bool
    output_path: str | None = None
    result_json: str | None = None
    reason: str | None = None       # ok=False 时必填


class Worker:
    def __init__(self, store: Store, control: Control, *, worker_id: str,
                 lease_seconds: int = 300,
                 heartbeat_interval: float = 5.0) -> None: ...
    def run_once(self, pool: str, execute: Callable[[WorkerContext], TaskResult]) -> bool:
        """领一个任务并跑完。没有可领的任务返回 False。"""
    def run_forever(self, pool: str, execute: Callable[[WorkerContext], TaskResult],
                    *, idle_timeout: float | None = None) -> None: ...


# ---- launcher.py ----
@dataclass(frozen=True, slots=True)
class LaunchHandle:
    tier: Tier
    worker_id: str
    thread: threading.Thread | None = None
    process: multiprocessing.process.BaseProcess | None = None
    def join(self, timeout: float | None = None) -> None: ...
    def is_alive(self) -> bool: ...


def launch(tier: Tier, db_path: str, pool: str,
           execute: Callable[[WorkerContext], TaskResult],
           *, worker_id: str | None = None,
           lease_seconds: int = 300,
           heartbeat_interval: float = 5.0,
           idle_timeout: float | None = None) -> LaunchHandle: ...
```

---

## 四、九条实现决议

### W1 · worker 不绑定现有 agent 实现

执行逻辑由调用方以 `execute(ctx) -> TaskResult` 注入。`worker.py` **不得** import `tools.delegate_tool`、`agent.subagent_lifecycle` 或任何现有执行器。

理由：接线是阶段 7 的事；本阶段只证明"任务能被可靠地领走、跑完、写回、被停止"。把执行器绑死会让这一层无法独立测试，也让后续接线变成重写。

### W2 · heartbeat 必须在独立线程里跑

执行期间（可能几十秒到几分钟）必须持续续租，否则 `patrol()` 会把正在跑的任务误判为死掉。

```
主线程: claim → 起 heartbeat 线程 → execute(ctx) → 停 heartbeat → complete/fail
```

heartbeat 线程每 `heartbeat_interval` 调一次 `store.heartbeat(task_id, epoch)`。**`FencedOutError` 要捕获并置 `ctx.cancelled`**——说明租约已被别人接管，本 worker 必须停手。

### W3 · 指令轮询与 heartbeat 合并

每次 heartbeat 顺带 `control.poll(task_id, epoch)`：

- `stop` → `ctx.cancelled.set()`，并调 `store.cancel(task_id, epoch)`
- `steer` → 追加到 `ctx.steers`（worker 线程安全地用 `list` + 锁）
- 处理完立即 `control.ack(cmd_ids)`

**ack 必须在"处理之后"**，不能先 ack 再处理——否则处理失败时指令永久丢失。

### W4 · `store.cancel()` 是本次唯一允许的 `store.py` 改动

现有 `store.py` 有 `fail()` 没有 `cancel()`，而 `RUNNING → CANCELLED` 是合法边（`_ALLOWED` 里有）。没有 `cancel()` 就无法落实"stop 在下一个迭代边界生效"。

新增：

```python
def cancel(self, task_id: str, epoch: int, *, reason: str = "cancelled") -> None:
    """RUNNING/CLAIMED -> CANCELLED，带 fencing 校验。"""
```

必须走 `transition()`（`max_retries` 必传），必须带 `AND lease_epoch = :epoch`，`rowcount==0` 抛 `FencedOutError`。

**除此之外不得改 `store.py` 的任何一行。**

### W5 · `execute` 返回后由 worker 决定落点

| `TaskResult` | 动作 |
|---|---|
| `ok=True` | `store.complete(task_id, epoch, output_path=..., result_json=...)` |
| `ok=False` 且 `ctx.cancelled` 已置位 | `store.cancel(...)`，不再重试 |
| `ok=False` 否则 | `store.fail(task_id, epoch, reason=...)`（内部决定重试还是吸收） |
| `execute` 抛异常 | 视为 `ok=False, reason=type(exc).__name__`，**不得吞掉堆栈**——写进 `result_json` 或 `block_reason` |

### W6 · 档位判定

```python
def choose_tier(self, card, *, requested=None) -> Tier:
    if requested is not None:
        return requested
    if card.isolation is Isolation.PROCESS:
        return Tier.DAEMON
    return Tier.EMBEDDED          # 注意：默认不是 INLINE
```

**默认 `EMBEDDED` 而不是 `INLINE`**：`INLINE` 是同步阻塞，会把调用方卡住；现有 `delegate_task` 的默认行为也是后台跑。只有显式要求 `Tier.INLINE` 才同步。

`card.isolation is None`（自动推断）→ `EMBEDDED`（推断为 PROCESS 时由 `infer_isolation` 在契约层决定，本层不重复推断）。

### W7 · `sample()` 只读，不改状态

`Dispatcher.sample()` 只做 `SELECT task_id ... WHERE state='QUEUED' AND pool=? ORDER BY is_key DESC, priority DESC, bottom_level DESC, created_at ASC LIMIT ?`。

**不得** claim、不得 UPDATE。claim 是 `Worker.run_once` 的事。理由：采样是调度决策，claim 是执行动作，混在一起会让"采了不跑"变成永久占用。

### W8 · daemon 空闲自杀

`run_forever(idle_timeout=...)`：连续 `idle_timeout` 秒没有领到任何任务 → 退出。

实现用注入的 `now`，**测试里不许真 sleep 30 分钟**（用假时钟推进）。

**`idle_timeout` 的三档语义（原决议此处自相矛盾，已修正）**

原文一边冻结签名 `idle_timeout: float | None = None`，一边说"DAEMON 档默认 1800"——同一个形参不可能既表示"永不"又表示"30 分钟"。执行者发现后报了上来，现裁定如下：

| 传入值 | 语义 |
|---|---|
| `None` | **用档位默认**：`Tier.DAEMON` → `1800.0`（30 分钟，对齐计划验收）；`EMBEDDED` / `INLINE` → 永不自杀 |
| 显式数值 | 该值（秒） |
| `float("inf")` | 永不自杀（DAEMON 想要常驻时的出口） |

这样 `None` 保持"跟随档位"的一致含义，而"永不自杀的 daemon"仍有明确表达方式，不需要新增参数或第二个入口函数。

实现用注入的 `now`，**测试里不许真 sleep 30 分钟**（用假时钟推进）。DAEMON 的默认值由模块常量 `_DAEMON_IDLE_TIMEOUT = 1800.0` 提供，并由 `test_launcher_daemon_defaults_to_30_min_idle_timeout` 钉住。

### W9 · 三档启动的进程安全

- `Tier.INLINE`：直接在当前线程调 `run_once`，返回 `LaunchHandle(tier, worker_id)` 且 `thread/process` 均为 `None`
- `Tier.EMBEDDED`：`threading.Thread(daemon=True)`，每个线程**自己 `Store(db_path)`**（sqlite3 连接不可跨线程共享）
- `Tier.DAEMON`：`multiprocessing`（`spawn` 优先，避免 fork 继承父进程的 sqlite 句柄），子进程内自己 `Store(db_path)` + `Control`

**连接绝不能跨线程/进程传递**——这是本阶段最容易踩的坑。

---

## 五、验收

| # | 指标 | 判定 |
|---|---|---|
| ① | `choose_tier` 判定正确 | PROCESS→DAEMON；INLINE→EMBEDDED；显式 `requested` 优先 |
| ② | `sample()` 不改状态 | 采样后 `state` 仍为 `QUEUED`、`claimed_by` 仍为 NULL |
| ③ | worker 跑完一个任务并 `complete` | 注入假 execute，断言 state=SUCCEEDED、output_path 落库 |
| ④ | 执行期间持续续租 | 用短 `lease_seconds` + 慢 execute，断言未被 `patrol()` 判死 |
| ⑤ | 收到 `stop` 后 `cancel` | 另一线程 post stop，断言 state=CANCELLED 且 `execute` 观察到 `ctx.cancelled` |
| ⑥ | `steer` 文本进入 `ctx.steers` | 逐字相等，且 ack 后不再返回 |
| ⑦ | `execute` 抛异常不丢堆栈 | 断言 `reason` 含异常类型名，任务落 FAILED/QUEUED 而非卡住 |
| ⑧ | daemon 空闲超时退出 | 假时钟推进，断言 `run_forever` 返回 |
| ⑨ | 三档都能起停 | INLINE 同步返回；EMBEDDED 线程 join；DAEMON 进程 join |

### 必须新增的测试（函数名固定）

```
test_choose_tier_maps_isolation_to_tier
test_choose_tier_honours_explicit_request
test_sample_does_not_claim
test_worker_completes_task
test_worker_heartbeats_during_long_execution
test_worker_cancels_on_stop_command
test_worker_receives_steer_text
test_worker_fails_on_execute_exception
test_run_forever_exits_after_idle_timeout
test_launcher_inline_runs_synchronously
test_launcher_embedded_thread_joins
test_launcher_daemon_process_joins
```

---

## 六、禁止事项

1. **不得改 `delegate_tool.py` / `subagent_lifecycle.py` / `async_delegation.py`**。接线是阶段 7，本阶段只交付可独立测试的层。
2. 除 W4 允许的 `store.cancel()` 外，不得改 `store.py` / `schema.py` / `contracts.py` / `state_machine.py`。
3. 不得让连接跨线程/进程传递。
4. 不得用真 sleep 等 30 分钟（用注入时钟）。
5. 不得吞异常（`execute` 抛的异常必须留下类型名）。
6. 不得跑全量 `tests/`。

## 七、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```
Python `./venv/bin/python`。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

跨线程/进程测试**必须用文件库**。
