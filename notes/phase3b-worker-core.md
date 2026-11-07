# 阶段 3b · `worker.py` / `launcher.py` / `store.cancel()`（worker-core）

交付：`agent/orchestration/worker.py`（351 行，新建）、`launcher.py`（254 行，新建）、
`store.py`（+1900 字节，只多一个 `cancel()`）、`tests/orchestration/test_worker.py`（291 行）、
`test_launcher.py`（140 行）。

## 1. 实际签名（`inspect.signature` 原文，与决议 §三逐字一致）

```
Worker.__init__(self, store: 'Store', control: 'Control', *, worker_id: 'str', lease_seconds: 'int' = 300, heartbeat_interval: 'float' = 5.0) -> 'None'
Worker.run_once(self, pool: 'str', execute: 'Callable[[WorkerContext], TaskResult]') -> 'bool'
Worker.run_forever(self, pool: 'str', execute: 'Callable[[WorkerContext], TaskResult]', *, idle_timeout: 'float | None' = None) -> 'None'
launch(tier: 'Tier', db_path: 'str', pool: 'str', execute: 'Callable[[WorkerContext], TaskResult]', *, worker_id: 'str | None' = None, lease_seconds: 'int' = 300, heartbeat_interval: 'float' = 5.0, idle_timeout: 'float | None' = None) -> 'LaunchHandle'
Store.cancel(self, task_id: 'str', epoch: 'int', *, reason: 'str' = 'cancelled') -> 'None'
LaunchHandle.join(self, timeout: 'float | None' = None) -> 'None'
LaunchHandle.is_alive(self) -> 'bool'
```

字段（`dataclasses.fields`）：

```
WorkerContext  store: Store, control: Control, worker_id: str, task_id: str, lease_epoch: int, cancelled: threading.Event, steers: list[str]
TaskResult     ok: bool, output_path: str|None, result_json: str|None, reason: str|None
LaunchHandle   tier: Tier, worker_id: str, thread: threading.Thread|None, process: multiprocessing.process.BaseProcess|None
```

## 2. heartbeat 线程完整实现（worker.py:266-342，逐字）

```python
    def _start_heartbeat(self, ctx: WorkerContext) -> tuple[threading.Thread, threading.Event]:
        stop = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(ctx, stop),
            name=f"worker-hb-{ctx.task_id}",
            daemon=True,
        )
        thread.start()
        return thread, stop

    def _stop_heartbeat(self, thread: threading.Thread, stop: threading.Event) -> None:
        stop.set()
        thread.join(timeout=max(1.0, self._heartbeat_interval * 2))

    def _heartbeat_loop(self, ctx: WorkerContext, stop: threading.Event) -> None:
        store: Store | None = None
        conn: sqlite3.Connection | None = None
        try:
            store = Store(self._db_path, worker_id=f"{self._worker_id}:heartbeat")
            conn = sqlite3.connect(self._db_path, isolation_level=None)
            control = Control(conn)
            while not stop.wait(self._heartbeat_interval):
                try:
                    store.heartbeat(ctx.task_id, ctx.lease_epoch,
                                    lease_seconds=self._lease_seconds)
                except FencedOutError:
                    logger.warning("续租被 fence，worker 停手：task_id=%s epoch=%s",
                                   ctx.task_id, ctx.lease_epoch)
                    ctx.cancelled.set()
                    return
                self._drain_commands(ctx, store, control)
        except BaseException:
            logger.exception("heartbeat 线程异常退出：task_id=%s", ctx.task_id)
            ctx.cancelled.set()
        finally:
            if conn is not None:
                conn.close()
            if store is not None:
                store.close()
```

`_drain_commands`（320-342）：`poll` → 逐条处理 → 全部处理完才 `control.ack(handled)`
（W3：先 ack 会让处理失败时指令永久丢失）；`stop` 先置 `ctx.cancelled` 再用**本线程的**
`store.cancel` 抢先落库，`steer` 逐字 `append` 进 `ctx.steers`。

## 3. W1–W9 对应真实行号

| 决议 | 落点 |
|---|---|
| W1 不绑执行器 | worker.py:1-26（模块注释）；全文件 0 处 `import tools.*`；执行体注入点 134-136 |
| W2 heartbeat 独立线程 | worker.py:12-15、266-275（起）、157-161（起停夹住 execute）、281-318（循环）、301-309（`FencedOutError` → `ctx.cancelled.set()`） |
| W3 轮询+ack 顺序 | worker.py:320-342（ack 在 342，处理在 329-341）；`steer` 334；`_SteerList` 47-66（frozen+slots 塞不进锁字段，锁放 list 里） |
| W4 `store.cancel()` | store.py:554-592（`transition()` 带 `max_retries` 571-578、`AND lease_epoch` 583-586、rowcount≠1 抛 `FencedOutError` 587-590） |
| W5 落点判定 | worker.py:200-219（异常 → `reason=类型名`，206-215）、221-253（`_land`）、255-262（`_cancel` 容错） |
| W6 默认 EMBEDDED | 不在我的文件里（dispatch-core 的 `dispatcher.py`）；launcher 只消费 `Tier`：launcher.py:141-160 |
| W7 sample 只读 | 同上，不在我的文件里 |
| W8 空闲自杀 | worker.py:166-196（假时钟判定 187-195，`_IDLE_POLL_SECONDS` 40）；launcher.py:46（1800s 常量）、110-115（`None` → 1800，判据带 `tier is Tier.DAEMON`） |
| W9 连接不跨执行体 | worker.py:128-130（只取 `db_path`/`now`，不传连接）、291-293（线程自建）、314-318（线程内关）；launcher.py:129-137（EMBEDDED 线程 daemon=True）、141（`spawn` 而非 fork）、165-189（INLINE 当前线程同步）、191-218（线程/子进程共用的自建连接段） |

## 4. `pytest tests/orchestration/test_worker.py tests/orchestration/test_launcher.py -q` 原文

```
..........                                                               [100%]
10 passed in 3.95s
```

回归：`pytest tests/orchestration -q` → `240 passed, 2 skipped, 1 xfailed in 71.09s`。

## 5. 反证：去掉 heartbeat 线程后 ④ 变红

把 `run_once` 里的 `self._start_heartbeat(ctx)` 换成"执行前续租一次"（`_NoopThread` 占位，
其余不变），跑单条测试：

```
>       assert "error" not in box, box.get("error")
E       AssertionError: NotClaimableError('complete 需要 RUNNING，task_id=t1 实际 BLOCKED')
E       assert 'error' not in {'error': NotClaimableError('complete 需要 RUNNING，task_id=t1 实际 BLOCKED')}

tests/orchestration/test_worker.py:180: AssertionError
=========================== short test summary info ============================
FAILED tests/orchestration/test_worker.py::test_worker_heartbeats_during_long_execution
1 failed in 2.22s
```

即：没有续租线程时 1.3s 处的 `patrol()` 把活着的任务判成 `BLOCKED`，落点随之炸。
还原后 6 passed。

## 6. 两处需要主控知晓的实现取舍（不是签名偏离）

1. **`_land` 先判 `cancelled` 再判 `ok`**。W5 表格第 1 行是"`ok=True` → complete"，但 W3 要求
   heartbeat 线程收到 `stop` 就**立刻** `store.cancel`，所以 `execute` 返回时行已经是
   `CANCELLED`，此时 `complete` 只会抛 `NotClaimableError`。故按"已取消优先"实现，
   W5 第 1 行只在任务仍为 `RUNNING` 时可达（worker.py:224-231 有注释）。
2. **`execute` 的堆栈去向**。W5 要求"写进 `result_json` 或 `block_reason`"，但 `store.fail()`
   既不写 `result_json` 也不写 `block_reason`（只有 `reason` 进 `events.payload`），而
   store.py 除 `cancel()` 外不许动。落地为：`reason = f"{type(exc).__name__}: {exc}"`
   （类型名进库，验收 ⑦ 可断言）+ `logger.exception(...)` 保留完整堆栈。
3. **`cancel()` 只接受 `RUNNING`**。`_ALLOWED[CLAIMED]` 里没有 `CANCELLED`（与已上报的
   `CLAIMED -> BLOCKED` 缺口同源），所以 `CLAIMED` 行无法取消；`run_once` 在起 heartbeat
   之前就 `start()`，这个窗口为空。二次 `cancel` 抛 `NotClaimableError`（幂等由调用方负责）。
4. **空闲时钟取自 `store._now`**。冻结的 `__init__` 没有 `now` 参数，再加一个会偏离 §三；
   用 Store 注入的同一个时钟，测试用假时钟推进即可（`test_run_forever_exits_after_idle_timeout`
   全程零 sleep）。

5. **`launch(Tier.DAEMON)` 的 1800s 是"函数体里映射"，不是形参默认值**。决议 §三 冻结的形参默认是
   `idle_timeout: float | None = None`，W8 又要求 DAEMON 档默认 1800s，两者只有这一种同时满足的写法：
   签名保持 `= None`（`inspect.signature` 可逐字核对），映射在 launcher.py:110-115，判据里带
   `tier is Tier.DAEMON`，**与代码位置无关**——即使将来有人把这段上提到分支之前，EMBEDDED
   也不会静默继承 1800s（已用桩验证：EMBEDDED 收到 `None`、DAEMON 收到 1800.0、显式 7.5 不被覆盖）。
   代价是 DAEMON 档无法用"显式传 `None`"表达"永不自杀"——这是冻结签名的固有歧义（"没传" 与
   "传了 None" 不可区分），不是实现偏好。需要永不自杀时传一个大数：`float("inf")` 可用，
   `time.sleep(min(_IDLE_POLL_SECONDS, inf))` 仍是 0.5s 轮询，不会退化。
