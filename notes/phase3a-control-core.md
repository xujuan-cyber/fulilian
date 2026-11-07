# 阶段 3a · `control.py` 交付记录（control-core）

文件：`agent/orchestration/control.py`（472 行）、`tests/orchestration/test_control.py`（338 行，10 条）。
规格：`docs/design/orchestration-phase3a-control-decisions.md`（§三 冻结签名 + D1–D8）。

## 1. 实际签名（`inspect.signature` 输出原文，非手抄）

```
Command :: (cmd_id: 'int', task_id: 'str', lease_epoch: 'int', kind: 'str', payload: 'str | None', created_at: 'float') -> None
TaskView :: (task_id: 'str', parent_task_id: 'str | None', batch_id: 'str', goal: 'str', state: 'str', pool: 'str', attempts: 'int', lease_epoch: 'int', claimed_by: 'str | None', cancel_requested: 'bool', started_at: 'float | None', updated_at: 'float') -> None
Control.__init__ :: (self, conn: 'sqlite3.Connection', *, now: 'Callable[[], float]' = <built-in function time>) -> 'None'
Control.request_stop :: (self, task_id: 'str') -> 'str'
Control.request_steer :: (self, task_id: 'str', text: 'str') -> 'int'
Control.poll :: (self, task_id: 'str', epoch: 'int') -> 'list[Command]'
Control.ack :: (self, cmd_ids: 'Sequence[int]') -> 'int'
Control.list_children :: (self, *, parent_task_id: 'str | None' = None, batch_id: 'str | None' = None) -> 'list[TaskView]'
```

与 §三 逐字一致：无增删参数、默认值未改（`now=time.time`、`None`）。

## 2. `poll` 与 `request_stop` 的完整 SQL

`poll(task_id, epoch)` —— 同一个 `BEGIN IMMEDIATE` 里先清**更早**时代、再取本时代（D2 + D7）：

```sql
-- 1) 顺带 ack 掉更早时代的未确认指令（之前 attempt 的残留）；严格小于，见 §5.2
UPDATE task_commands SET acked_at = :now
 WHERE task_id = :task_id AND lease_epoch < :epoch AND acked_at IS NULL;

-- 2) 只返回本时代的未确认指令
SELECT cmd_id, task_id, lease_epoch, kind, payload, created_at
  FROM task_commands
 WHERE task_id = :task_id AND lease_epoch = :epoch AND acked_at IS NULL
 ORDER BY cmd_id ASC;
```

`request_stop(task_id)` —— 先读一行判定分派（D3 两条路）：

```sql
SELECT state, lease_epoch, attempts, handoff_count, card_json
  FROM tasks WHERE task_id = ?;

-- 路 A：QUEUED / BLOCKED（无持有者）→ 直接取消，不写 task_commands
UPDATE tasks SET state = :cancelled, completed_at = :now, updated_at = :now
 WHERE task_id = :task_id AND state = :expected;

-- 路 B：CLAIMED / RUNNING（有持有者）→ 落指令 + 标记，不硬切
INSERT INTO task_commands (task_id, lease_epoch, kind, payload, created_at)
VALUES (:task_id, :epoch, 'stop', NULL, :now);

UPDATE tasks SET cancel_requested_at = :now, updated_at = :now
 WHERE task_id = :task_id AND lease_epoch = :epoch
   AND state IN ('CLAIMED', 'RUNNING');
```

两条 UPDATE 都校验 `rowcount == 1`，否则抛 `ControlError`（事务内不可能是竞态，只可能是数据异常）。
状态变更走 `transition()`，`max_retries` / `handoff_cap` 从 `card_json` 取真值传入。

## 3. D1–D8 落点（当前修订的真实行号）

| 决议 | 行号 | 内容 |
|---|---|---|
| D1 自持连接 | 222–228 | `__init__(conn, *, now)` 只存 `self._conn`/`self._now`；全文无 `Store` import（26–37 行仅 contracts / state_machine） |
| D2 更早 epoch 一并 ack | 136–139（SQL，`<` 在 138）、400–407（poll 内同事务先 ack 再查）、127–133（本时代 SELECT）、387–394（docstring 写明为何不能 `<>`） |
| D3 `request_stop` 两条路 | 155–162（`_UNOWNED_STATES` / `_OWNED_STATES`）、294–295（终态→`TargetGoneError`）、299–324（取消路，零指令）、326–340（指令路）、342（不可达状态→`ControlError`）；257（任务不存在） |
| D4 steer 可达性近似 | 346–382，362（空文本→`ValueError`）、369–371（非 CLAIMED/RUNNING→`TargetGoneError`）、docstring 347–358 写明是近似 |
| D5 所有权范围强制 | 454–458（两个都空→`NotOwnedError`）、460–472（两个都给=**交集**，446–449 的 docstring 已写明"AND，不是并集"） |
| D6 ack 幂等 | 142–146（SQL `AND acked_at IS NULL`）、420–435（空输入直接返回 0，逐条累加 `rowcount`） |
| D7 写操作走 `BEGIN IMMEDIATE` | 234–245（`_write_tx`）、237（`BEGIN IMMEDIATE`）；调用点 289（stop）、365（steer）、400（poll）、430（ack）；`list_children` 只读不开事务 |
| D8 不吞异常 | 240–243（`except BaseException` 只回滚后 `raise`）；D1–D8 代码路径内无 `except: pass`、无静默降级 |

## 4. 测试

```
$ pytest tests/orchestration/test_control.py tests/orchestration/test_control_multiprocess.py -q
..............                                                           [100%]
14 passed in 0.85s
```

`test_control.py` 10 条（§五 固定清单 8 条 + `test_poll_does_not_swallow_newer_epoch_commands`
+ 一条 `test_list_children_tolerates_malformed_card_json`），`test_control_multiprocess.py` 4 条
（control-verify 写，含跨进程验收 ①）。

**来源说明**：`control.py:165` 的 `_goal_from_card()` 与上述最后一条测试不是本次交付写的
（我交付时 `_task_view` 直接 `json.loads(...)["goal"]`），是本文件被并行编辑时加入的；
它把 JSON 解析失败降级为空 goal，与 D8"不得静默降级"的边界需要主控确认，我没有改动它。

## 5. 两条可失败验证

**5.1 关掉 D2 的"顺带 ack 过期指令"**（`poll` 里那 4 行换成注释）：`test_poll_discards_stale_epoch_commands` 变红，还原后绿。

```
E       AssertionError: 过期指令必须被顺带 ack 掉
E       assert None is not None
FAILED tests/orchestration/test_control.py::test_poll_discards_stale_epoch_commands
1 failed, 7 passed in 0.50s
```

**5.2 `<>` → `<` 修正**（control-verify 实测：僵尸 epoch1 worker 会把现任 epoch2 未执行的指令吞掉）。
把 `lease_epoch < :epoch` 改回 `<>`，新测试的**关键断言**立刻变红：

```
>       assert _acked_at(conn, new_id) is None, "僵尸 worker 不得吞掉新持有者的指令"
E       AssertionError: 僵尸 worker 不得吞掉新持有者的指令
E       assert 1793463325.1825986 is None
FAILED tests/orchestration/test_control.py::test_poll_does_not_swallow_newer_epoch_commands
1 failed, 8 deselected in 0.30s
```

只断言"不返回 epoch2 的指令"抓不到这个洞（`<>` 也 ack 掉、也不返回），必须断言它**没被 ack**。

## 6. 已知取舍（有意识的，不是遗漏）

**连续两次 request_stop 会写两条 stop 指令（无去重）。** 主控裁定保持现状：worker 侧执行两次
stop 等价于执行一次（幂等），多两行的代价远小于 INSERT ... WHERE NOT EXISTS 带来的额外分支，
且 stop 是低频操作。阶段 3b 接手者不要把它当 bug「修」掉——改成去重属于写入语义变更，需重新裁定。
