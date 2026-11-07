# 阶段 3b 验收记录 · `dispatcher.py` + `worker.py` + 三档承载

> 验收人：team-lead｜时点：2026-11-01 01:0x｜依据：`orchestration-phase3b-worker-decisions.md` §五
> 方式：主控独立重跑 + 变异验证 + 逐条对照决议。

## 结论：通过

全量 **257 passed / 2 skipped / 1 xfailed**（阶段 3a 结束时是 223，本阶段 +34）。

| 文件 | 测试数 |
|---|---|
| `test_dispatcher.py` | 23 |
| `test_worker.py` | 6 |
| `test_launcher.py` | 4 |

| 验收 | 结果 |
|---|---|
| ① `choose_tier` 判定 | 通过（PROCESS→DAEMON、INLINE→EMBEDDED、显式优先） |
| ② `sample()` 不改状态 | 通过（断言 state/claimed_by/attempts/整行四层） |
| ③ worker 跑完并 complete | 通过 |
| ④ 执行期间持续续租 | 通过 + 变异验证（见下） |
| ⑤ 收到 stop 后 cancel | 通过 |
| ⑥ steer 文本进入 `ctx.steers` | 通过 |
| ⑦ `execute` 抛异常不丢类型 | 通过 |
| ⑧ daemon 空闲超时退出 | 通过（假时钟，无真 sleep） |
| ⑨ 三档起停 | 通过 |

---

## 一、W2 的变异验证（主控独立执行）

把 `thread, stop = self._start_heartbeat(ctx)` 换成不起线程后：

```
去掉 heartbeat 线程后返回码: 1
tests/orchestration/test_worker.py:180: AssertionError
FAILED test_worker_heartbeats_during_long_execution
=> 测试能抓住 W2
已还原: True
```

**为什么这条重要**：执行期间不续租，任务会被自己的 `patrol()` 判死，从 `RUNNING` 掉到 `BLOCKED`——`complete()` 随即因"需要 RUNNING"失败。这个 bug 在生产里表现为"任务跑着跑着自己变成阻塞了"，极难定位。

---

## 二、三处取舍的裁定

### ① `_land` 先判 `cancelled` 再判 `ok` —— 认可

heartbeat 收到 stop 时会抢先 `cancel()`，此时任务已是 `CANCELLED`；若再走 `complete()` 会因"需要 RUNNING"抛错。先判 cancelled 是对的：**用户的停止意图优先于执行结果**。

### ② 异常堆栈走 `logger.exception`、`reason` 只带类型名 —— 认可但记录

`store.fail()` 只有 `reason` 一个文本通道，没有地方放完整堆栈。当前做法（日志留全栈 + `reason` 带类型名）在可观测性上够用，但意味着**堆栈不在数据库里**，跨进程排查时得去翻日志文件。

记为 P2：阶段 4 的 `redispatch` 要按失败原因决策时，可能需要把 `reason` 结构化（如 `{"error": "TimeoutError", "detail": "..."}`）。现在不动。

### ③ 空闲时钟取 `store._now` —— 与 `dispatcher` 同类的技术债

冻结的 `Worker.__init__` 没有 `now` 参数，所以取了 `store._now`。和 `Dispatcher.sample()` 用 `store._conn` 是同一类封装泄漏。

**记为 P2，与 `sample_ids()` 合并处理**：阶段 3c 给 `Store` 补公开只读接口时，一并暴露 `now`（或让 `Worker`/`Dispatcher` 接受 `now` 参数）。现在改签名会破坏冻结契约。

---

## 三、发现的一个设计缺口（第二次出现）

`store.cancel()` 的 docstring 里写着：

> `CLAIMED -> CANCELLED` 不在 `_ALLOWED` 里，所以"已领取未开始"的任务无法在这里取消。

这与阶段 2a 发现的 `CLAIMED → BLOCKED` 缺失是**同一类问题**：`_ALLOWED[CLAIMED] = {RUNNING, QUEUED, FAILED}` 太窄，导致"领取后立刻出事"的两个方向（崩溃、取消）都没有合法边。

两次的绕过方式：
- 2a：`CLAIMED → FAILED →（重试预算内）QUEUED`
- 3b：`Worker.run_once` 在 `claim()` 之后**立即** `start()`，把 `CLAIMED` 窗口压到两条相邻语句

当前实现是安全的（窗口极小且有注释说明），但这是**靠约定而非靠约束**维持的。记为 P2：阶段 4 若要在 `CLAIMED` 上做更多事，应评估给 `_ALLOWED[CLAIMED]` 补 `CANCELLED`（需同步改钉表测试与规格文档）。

---

## 四、实现纪律抽查

| 决议 | 结果 |
|---|---|
| W1 worker 不绑定现有执行器 | 通过（`execute` 回调注入，未 import `tools.*`） |
| W2 heartbeat 独立线程 | 通过 + 变异验证 |
| W3 ack 在处理之后 | 通过 |
| W4 `store.py` 只加 `cancel()` | 通过（`cancel()` 在 554–592，其余未动） |
| W6 默认 `EMBEDDED` 非 `INLINE` | 通过 |
| W7 `sample()` 只读 | 通过 |
| W9 连接不跨线程/进程 | 通过（每线程/进程自建 `Store`） |

## 五、技术债汇总（P2，不阻塞）

| 项 | 位置 | 计划 |
|---|---|---|
| `Dispatcher.sample()` 用 `store._conn` | `dispatcher.py` | 3c 加 `Store.sample_ids(pool, limit)` |
| `Worker` 空闲时钟用 `store._now` | `worker.py` | 3c 一并暴露 `now` |
| `fail()` 的 `reason` 无结构化通道 | `store.py` | 阶段 4 按失败原因决策时再定 |
| `_ALLOWED[CLAIMED]` 缺 `CANCELLED`/`BLOCKED` | `state_machine.py` | 阶段 4 评估 |

## 六、阶段 3 完成度

| 子项 | 状态 |
|---|---|
| 3a 控制通道（stop/steer/list） | 完成 |
| 3b 派发器 + worker 循环 + 三档承载 | **完成** |

**仍未接线**：`tools/delegate_task` 走的还是内存态旧实现，`agent/orchestration/` 的生产引用数仍为 0。接线是阶段 7，按计划此时不应动它——本阶段交付的是"能被独立测试的执行层"。

阶段 3 计划验收里还有一条"现有 120 个 delegation 测试全绿"，**这一条要等接线后才成立**，现在无法验证。如实记录。

---

## 七、验收中追加的第四处裁定：W8 自相矛盾

** 报**：§三 冻结的签名写 ，而 W8 说" 的默认值是 "——同一个形参不可能既表示"永不自杀"又表示"30 分钟"。

**这是决议内部矛盾，不是实现问题。** 现裁定：

| 传入值 | 语义 |
|---|---|
|  | 用档位默认：DAEMON → ；EMBEDDED / INLINE → 永不自杀 |
| 显式数值 | 该值 |
|  | 永不自杀（DAEMON 要常驻时的出口） |

 保持"跟随档位"的一致含义，"永不自杀的 daemon"仍有明确表达方式，不需要新增参数或第二个入口函数。W8 已按此改写， 钉住默认值。

**这一条值得记**：冻结决议里出现自相矛盾时，执行者的正确做法是**报上来并给出可行解**，而不是二选一悄悄实现——前者能改文档，后者会让下一个人按文档写出不一样的行为。

---

## 八、一条被证伪的缺陷报告（记录方法）

 报：" 的  里没有 timeout 槽位， 传进 EMBEDDED 会被静默忽略。"

**主控行为验证后证伪**：



1.0 秒准时退出，**EMBEDDED 支持空闲退出**，不存在静默忽略。

我基于它的描述给出了"要么 raise ValueError、要么传参"的二选一，**前提是错的，两个选项都不该做**。已及时叫停，避免把一个本来能用的功能改成报错。

**方法上的收获**：怀疑"参数被静默忽略"时，应先做**行为验证**（传一个能被观察到的小值，看行为是否随之改变），而不是读调用链——调用链可能跨多层、可能被默认值兜住，读错一段就会得出错误结论。这次就是读了  的 args 而误推到 。

另一面：**执行者报错时，主控不能只凭描述就下指令**。这次如果我直接批准改代码，就会引入一个真实缺陷。验收方同样要验证被报上来的问题是否成立。

---

## 九、 缺边的处置建议（ 提出，主控采纳为阶段 4 的推荐方案）

 在收尾时给出了一个比"先记着"更强的论证：

> 补边比继续约定便宜： 与  都是"持有者还没开跑就被打断"，语义一致；补两条边后  的  前置和  的 FAILED 回退都能删掉，**是净减法**。

这个论证成立，而且解释了为什么这个缺口值得优先处理——它不是"再加点能力"，而是**删掉两处为了绕路而存在的代码**：

| 补边后可以删掉 | 现在的位置 | 现状 |
|---|---|---|
|  的  前置检查 |  | 因为 CLAIMED 无 CANCELLED 边 |
|  的  回退分支 |  patrol 段 | 因为 CLAIMED 无 BLOCKED 边 |

**代价**：要改 、钉表测试  的字面量、以及方案 §4.3 的转移表——**三处必须同步**，漏一处就会出现"文档与表不一致"，而这正是本 PR 反复出问题的根源。

**裁定**：不在 3b 做。理由不是风险高，而是它会把"阶段 3 的验收基线"和"状态机语义变更"混在一起，出了问题无法归因。列为**阶段 4 的第一项**，独立提交、独立验收。

 说"不擅自改"是对的处置——发现缺口、给出方案、不越权执行。

## 十、 的结构化通道（补充口径）

 补了一个我之前没注意的事实： 的  会写进 ，所以**异常类型名是可查的**，缺的只是 traceback 正文。

因此阶段 4 若要做结构化失败原因，最小改动是给  加可选 （与  的  对称），不必动状态机、不必改表。
