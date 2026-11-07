# 阶段 3a 验收记录 · `control.py` 跨进程控制通道

> 验收人：team-lead｜时点：2026-11-01 00:2x｜依据：`orchestration-phase3a-control-decisions.md` §五
> 方式：主控独立重跑 + 变异验证 + 逐条对照决议。

## 结论：通过（决议被修正 2 次，均为我方错误）

全量 **223 passed / 2 skipped / 1 xfailed**。`test_control.py` 10 条 + `test_control_multiprocess.py` 3 条全绿。

| 验收 | 结果 |
|---|---|
| ① 另一进程 post 的 stop，一个 heartbeat 内 poll 到 | 通过（子进程 post → 父进程单次 poll 取到，耗时 < 5s） |
| ② steer 文本逐字往返、ack 后不再返回 | 通过（含中文/换行/引号/反斜杠） |
| ③ 过期 epoch 指令被 ack 且不返回 | 通过 + 变异验证（见下） |
| ④ `list_children` 按 parent 隔离 | 通过（两个 parent 互不泄漏） |
| ⑤ 无范围抛 `NotOwnedError` | 通过 |
| ⑥ QUEUED 任务 stop 直接取消、零指令行 | 通过 |

---

## 一、决议修正之一：D2 的 `<>` 是个洞（`control-verify` 发现）

**原决议**：`poll()` 把 `lease_epoch != :epoch` 的未确认指令一并 ack（清理死掉 attempt 的残留）。

**问题**：`<>` 同时覆盖 `lease_epoch > :epoch`。场景——worker A 持 epoch 1 但是僵尸（卡住、租约已过期），worker B 已 claim 到 epoch 2 正在跑；A 醒来 poll 一次，就把 **B 尚未执行的 steer/stop 全部吞掉**。B 永远看不到，A 也早已无权执行。

**修正**：改为 `lease_epoch < :epoch`（严格小于）。这是 fencing 思想在指令通道上的应用——**worker 只能确认自己之前的时代，不能确认自己之后的时代**。

**变异验证**（主控独立执行）：把 `<` 退回 `<>` 后跑新测试

```
FAILED test_poll_does_not_swallow_newer_epoch_commands
E  + where 1793463354.08 = _acked_at(conn, 2)
1 failed in 0.80s
=> 测试能抓住 <> 这个洞
已还原: True
```

这条测试的关键是第三条断言"epoch=2 的指令 `acked_at` 仍为 NULL"。只断言"不返回 epoch=2"的话，用 `<>` 的错误实现也能过（它 ack 了自然就不返回），测不出洞。

---

## 二、决议修正之二：`list_children` 被一行脏数据打崩（主控探针发现）

**现象**：`_task_view` 用 `json.loads(str(card_json))["goal"]` 取目标。主控探针插入一行 `card_json='{}'` 后，**整个 `list_children` 抛 `KeyError`**。

**影响**：控制通道的列表路径是 TUI 直接读的。一条损坏记录会让调用方**看不见所有子任务**——比这一行数据本身坏掉严重得多。

**修正**：抽出 `_goal_from_card()`，`json.loads` 失败、非 dict、缺 `goal` 键一律返回 `""`，不抛。新增 `test_list_children_tolerates_malformed_card_json`：三条记录（正常 / JSON 坏 / 缺 goal）必须**都出现在结果里**，坏的 goal 为空串。

---

## 三、实现纪律抽查

| 决议 | 结果 |
|---|---|
| D1 `Control(conn)` 自持连接、不 import `Store` | 通过（`grep "from agent.orchestration.store"` 无命中） |
| D3 stop 两条路 | 通过（QUEUED → `CANCELLED` 且 `task_commands` 零新增行） |
| D5 无范围拒绝 | 通过 |
| D6 ack 幂等 | 通过 |
| D7 写路径 `BEGIN IMMEDIATE` | 通过 |
| D8 无 `except: pass` | 通过 |

## 四、执行者提出、主控认可的取舍

1. `poll` 对不存在的任务返回 `[]` 不抛错 —— 轮询路径抛异常会让 worker 循环变脆，"任务没了"的正确反应就是"没指令"。
2. steer payload 逐字保存，只用 strip 做空校验 —— strip 掉内容会破坏用户原始文本。
3. `list_children` 两个范围都给时取**交集** —— 比只用一个更安全（范围更窄），已要求写进 docstring。

## 五、遗留

| 项 | 说明 |
|---|---|
| `request_stop` 连发两次会写两条 stop 指令 | 执行者主动报告。worker 侧是幂等的（执行两次 stop 等价于一次），不阻塞；若要收敛可在写指令前查 `acked_at IS NULL AND kind='stop'` |
| worker 循环 / 承载方式 | 属阶段 3b，未开始 |
| `dispatcher.py` | 属阶段 3b，未开始 |

## 六、阶段 3 完成度

| 子项 | 状态 |
|---|---|
| 3a 控制通道存储侧（stop/steer/list） | **完成** |
| 3b 派发器 + worker 三档承载 | 未开始 |

**控制通道目前仍无生产调用方**——`tools/delegate_tool.py` 的 `action=list/stop/steer` 走的还是内存态旧实现。接上要等 3b 的 worker 循环就位。
