# 阶段 3a 冻结决议 · `control.py` 跨进程控制通道

> 主控裁定，实现者不得自行改动。
> 上游：`orchestration-implementation-plan.md` §阶段 3（B3 是方案原有空白，风险最高）。
> 现有语义来源：`tools/delegate_tool.py:478-580` 的 `action=list/stop/steer`（同进程、内存态），**跨进程版必须保住它的行为契约**。

---

## 一、为什么只做存储侧

阶段 3 有三块：`dispatcher.py`（派发）、worker 三档承载、`control.py`（控制通道）。

本阶段**只做 `control.py` 的存储侧**：发指令、取指令、确认、按所有权列任务。**不跑任务、不发信号、不杀进程。**

理由：控制通道是 B3 的空白点，也是最容易在"跨进程语义"上出错的地方；而承载方式（inline/embedded/daemon）要改现有执行链路，风险和验证成本都高一个量级。先把"指令能可靠送达并生效"这件事做对，承载后面接。

---

## 二、必须保住的现有语义（从 `delegate_tool.py` 抄下来的契约）

| 动作 | 语义 | 不许退化成 |
|---|---|---|
| `stop` | 在**下一个迭代边界**停止，进行中的 tool call 被请求取消但不硬切 | 不许变成立即 SIGKILL |
| `steer` | 文本**追加到下一个 tool result**，当前 tool call 永不切断 | 不许打断正在进行的调用 |
| `steer` 未送达 | 子任务先结束时，文本以 `missed_steer` 回报 | 不许静默丢弃 |
| `list` | 只列**本调用方 spawn 树内**的子任务 | **不许全库 dump**（会泄漏其他会话） |

`list` 的所有权过滤是安全项，不是可选项。

---

## 三、公开 API（冻结，逐字实现）

```python
@dataclass(frozen=True, slots=True)
class Command:
    cmd_id: int
    task_id: str
    lease_epoch: int
    kind: str            # 'steer' | 'stop' | 'budget_update'
    payload: str | None
    created_at: float


@dataclass(frozen=True, slots=True)
class TaskView:
    task_id: str
    parent_task_id: str | None
    batch_id: str
    goal: str
    state: str
    pool: str
    attempts: int
    lease_epoch: int
    claimed_by: str | None
    cancel_requested: bool
    started_at: float | None
    updated_at: float


class ControlError(Exception): ...
class NotOwnedError(ControlError): ...      # list 未给所有权范围
class TargetGoneError(ControlError): ...    # 任务不存在或已终态


class Control:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        now: Callable[[], float] = time.time,
    ) -> None: ...

    # ---- 写指令 ----
    def request_stop(self, task_id: str) -> str:
        """返回 'queued'（已投递指令）或 'cancelled'（未领取，直接取消）。"""

    def request_steer(self, task_id: str, text: str) -> int:
        """返回 cmd_id。任务不可 steer 时抛 TargetGoneError。"""

    # ---- 读指令（worker 侧）----
    def poll(self, task_id: str, epoch: int) -> list[Command]:
        """返回该任务当前 epoch 的未确认指令；顺带 ack 掉过期 epoch 的指令。"""

    def ack(self, cmd_ids: Sequence[int]) -> int:
        """确认已执行；幂等，返回本次真正改变的行数。"""

    # ---- 列任务 ----
    def list_children(
        self,
        *,
        parent_task_id: str | None = None,
        batch_id: str | None = None,
    ) -> list[TaskView]:
        """两个参数至少给一个，否则抛 NotOwnedError。"""
```

**签名不得增删参数、不得改默认值。**

---

## 四、八条实现决议

### D1 · `Control` 自己持有连接，不依赖 `Store`

`Control(conn)` 接收**已打开的连接**，自己开 `BEGIN IMMEDIATE`。不要 import `Store`、不要碰 `store._conn`。

理由：跨进程场景下每个进程各开一条连接；`Control` 与 `Store` 解耦后，控制通道可以独立测试、独立演进。

### D2 · 指令绑定 `lease_epoch`，过期的必须 ack 掉

`poll(task_id, epoch)` 只返回 `lease_epoch = :epoch AND acked_at IS NULL` 的指令。

**同一次 poll 里，`lease_epoch < :epoch`（严格小于）的未确认指令要一并 ack 掉**——它们是上一次 attempt 的残留（那个 worker 已经死了），不清理会永久堆积。

**绝不能用 `<>`**（原决议的错误，已修正）：`<>` 会把 `lease_epoch > :epoch` 的指令也 ack 掉。场景：worker A 持 epoch 1 但实际是僵尸（进程卡住、租约过期），worker B 已 claim 到 epoch 2 并正在跑；此时 A 突然醒来 poll 一次，就会把 **B 尚未执行的 steer/stop 全部吞掉**——B 永远看不到那条指令，而 A 也不会执行它（A 的时代已过）。

这是 fencing 思想在指令通道上的应用：**worker 只能确认自己之前的时代，不能确认自己之后的时代。** 新 epoch 的指令属于一个可能活着的后继者，谁都不能替它 ack。

### D3 · `request_stop` 分两条路

| 任务当前状态 | 动作 | 返回 |
|---|---|---|
| `QUEUED` / `BLOCKED`（无持有者） | 直接置 `state='CANCELLED'`、`completed_at=now`，**不写 `task_commands`** | `'cancelled'` |
| `CLAIMED` / `RUNNING` | 写 `task_commands(kind='stop', lease_epoch=当前epoch)` + 置 `cancel_requested_at=now` | `'queued'` |
| 终态 | 抛 `TargetGoneError` | — |

未领取的任务没有持有者，写指令没人会读——只会留一条永远不被 ack 的垃圾。这是 D3 存在的全部理由。

状态变更必须走 `transition()`（`QUEUED→CANCELLED` 是合法边）。`transition` 的 `max_retries` 是**必传**参数。

### D4 · `request_steer` 的可达性判定

库里没有 `accepting_steer` 列（那是旧内存记录里的字段）。用状态近似：**只有 `CLAIMED` / `RUNNING` 可 steer**，其余抛 `TargetGoneError`。

在 docstring 里写明这是近似，不是精确语义——真正的"是否还在接受 steer"由 worker 在迭代边界决定。

`text` 去空白后为空 → 抛 `ValueError`。

### D5 · `list_children` 必须给所有权范围

`parent_task_id` 与 `batch_id` **至少给一个**，都为空抛 `NotOwnedError`。

理由：旧实现的 `list` 用 `_owns_subagent_record()` 过滤，等价于"只看自己的 spawn 树"。跨进程后如果不强制给范围，就会变成全库 dump，**一个会话能看到另一个会话的子任务**——这是安全回归。

### D6 · `ack` 幂等

```sql
UPDATE task_commands SET acked_at = :now WHERE cmd_id = :id AND acked_at IS NULL
```

重复 ack 不报错，返回真实改变的行数。

### D7 · 全部写操作走 `BEGIN IMMEDIATE`

`request_stop` / `request_steer` / `poll`（因为要顺带 ack）/ `ack` 都要。只读的 `list_children` 不需要。

### D8 · 不得吞异常（含边界说明）

`except Exception: pass` / 静默降级一律返工。PR-1 已因此被拦过一次。

**边界：只读投影层允许字段级降级，写入与状态变更路径不允许。**

判别标准是"故障是否被隐藏"：

| 场景 | 判定 |
|---|---|
| 写入路径吞掉异常，数据没写进去却返回成功 | **禁止**——故障被隐藏，调用方以为一切正常 |
| 状态变更失败后静默回退到另一个状态 | **禁止**——状态被悄悄改写 |
| 只读投影解析某个字段失败，返回空值但**保留整行**，且不影响排序/过滤/其他字段 | **允许**——故障以可见方式呈现（字段为空），调用方仍能看到这一行存在 |

典型例子：`_task_view` 解析 `card_json` 取 `goal`。一条记录 JSON 损坏时，若直接 `json.loads(...)["goal"]`，整个 `list_children` 会抛 `KeyError`，调用方**看不见所有子任务**——这是把局部数据问题放大成整体不可用。正确做法是 `_goal_from_card()` 捕获 `TypeError`/`ValueError` 返回 `""`，**整行仍保留在结果里**，坏记录以"goal 为空"的形式暴露出来。

注意这里的 `except` 只捕获**解析类**异常（`TypeError`/`ValueError`），不捕获 `Exception`——数据库错误、编程错误仍必须冒泡。

---

## 五、验收

| # | 指标 | 判定 |
|---|---|---|
| ① | 另一进程 post 的 `stop`，worker 在**一个 heartbeat 周期**内 poll 到 | 跨进程测试：进程 A `request_stop`，进程 B `poll` 取到且 `kind='stop'` |
| ② | `steer` 文本完整送达，`ack` 后不再返回 | 断言文本逐字相等；ack 后 `poll` 返回空 |
| ③ | 过期 epoch 的指令被 ack 掉且不返回 | 用 epoch+1 调 `poll`，断言旧指令不出现且 `acked_at` 非空 |
| ④ | `list_children` 只返回指定范围内任务 | 造两个 parent 的任务，断言不互相泄漏 |
| ⑤ | `list_children` 不给范围时抛 `NotOwnedError` | 直接调用 |
| ⑥ | `request_stop` 对 QUEUED 任务直接取消、不写指令 | 断言 `task_commands` 无新增行且 state='CANCELLED' |

### 必须新增的测试（函数名固定）

```
test_stop_on_queued_task_cancels_without_command
test_stop_on_running_task_queues_command
test_steer_roundtrip_and_ack
test_poll_discards_stale_epoch_commands
test_list_children_scoped_to_parent
test_list_children_requires_ownership_scope
test_ack_is_idempotent
test_stop_on_terminal_task_raises
```

跨进程的那条（①）单独放 `test_control_multiprocess.py`，函数名 `test_cross_process_stop_within_one_heartbeat`。

---

## 六、禁止事项

1. 不得改 `schema.py` / `contracts.py` / `state_machine.py` / `store.py`。
2. 不得直接 `UPDATE tasks SET state`，走 `transition()`。
3. 不得让 `list_children` 无范围执行。
4. 不得引入第三方依赖。
5. 不得跑全量 `tests/`（只跑 `tests/orchestration`）。

## 七、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```
Python `./venv/bin/python`。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

跨进程测试**必须用文件库**（`tempfile.mkdtemp()`），`:memory:` 无法跨进程共享。
