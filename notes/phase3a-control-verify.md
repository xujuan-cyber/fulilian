# 阶段 3a · `control.py` 跨进程验证（control-verify）

依据：`docs/design/orchestration-phase3a-control-decisions.md` §三（签名）、§五①（验收）。
交付：`tests/orchestration/test_control_multiprocess.py`（4 用例）、`scripts/demo_control.py`。
未改动 `control.py` / `schema.py` / `store.py` / `state_machine.py`。

## 1. 用例结论

| # | 用例 | 结论 | 关键断言 |
|---|---|---|---|
| ① | `test_cross_process_stop_within_one_heartbeat` | **通过** | 子进程 `request_stop` → `'queued'`；父进程**单次** `poll(epoch)` 取到 1 条 `kind='stop'`，`lease_epoch` 等于投递时 epoch，单次 poll 耗时 < `heartbeat_seconds`(5.0)；库内 `state` 仍为 RUNNING 且 `cancel_requested_at` 已置（D3 只表达意图） |
| ② | `test_cross_process_steer_text_survives_roundtrip` | **通过** | 中文/换行/单双引号/中文引号/反斜杠/制表符往返**逐字相等**；`cmd_id` 与子进程返回值一致；`ack` 后 poll 为空、重复 ack 返回 0（D6） |
| ③ | `test_cross_process_list_does_not_leak_across_parents` | **通过** | 另一进程里 `list_children(parent_task_id=A)` 只见 A 的 2 个子任务，与 B 无交集且不含 A 自身；父进程侧另校验 `TaskView.goal` 由 `card_json` 还原（`tasks` 表无 goal 列） |
| ④ | `test_cross_process_zombie_worker_does_not_swallow_live_commands` | **通过** | 僵尸 poll(epoch=1) 只拿回自己时代的指令，**不许** ack epoch2 的（`acked_at` 仍 NULL）；现役 poll(epoch=2) 照常清掉 epoch1 残留且不返回。epoch 推进走 `fail → QUEUED → claim` 公开路径，不手改 `tasks` |

假绿排查：用 no-op 子进程做变异验证，①②③ 的断言在"指令没送到 / 范围不过滤"时都会红；
④ 另有独立反向验证（把 `_ACK_STALE_SQL` 还原成 `<>`，见 §4.1）。

```
[OK]   stop: 如期失败 -> poll 应取到恰好 1 条 stop，实际 0 条；全部指令：[]
[OK]   steer: 如期失败 -> poll 应取到恰好 1 条 steer，实际 0 条；全部：[]
[OK]   list: 如期失败 -> parent-a 应只看到自己的两个子任务，实际 ['a-child-1', 'a-child-2', 'b-child-1', 'b-child-2', 'parent-a', 'parent-b']
ALL MUTATIONS KILLED
```

连跑多次无抖动（0.32–0.50s）。

## 2. pytest 原文

```
$ ./venv/bin/python -m pytest tests/orchestration/test_control_multiprocess.py -q
....                                                                     [100%]
4 passed in 0.50s

$ ./venv/bin/python -m pytest tests/orchestration/test_control.py tests/orchestration/test_control_multiprocess.py -q
............                                                             [100%]
12 passed in 0.87s
```

## 3. demo 原文

```
$ ./venv/bin/python scripts/demo_control.py
{
  "db_path": null,
  "db_kept": false,
  "worker_exitcode": 0,
  "control_exitcode": 0,
  "elapsed_seconds": 0.224,
  "epochs": { "demo-stop": 1, "demo-steer": 1 },
  "control_sent": { "stop_outcome": "queued", "steer_cmd_id": 2 },
  "worker_saw": {
    "polls_used": 5,
    "commands": [
      { "task_id": "demo-stop",  "kind": "stop",  "payload": null, "cmd_id": 1, "lease_epoch": 1, "acked": 1 },
      { "task_id": "demo-steer", "kind": "steer", "payload": "第 1 行：把结论改成中文。\n第 2 行：保留 \"原文引用\"。", "cmd_id": 2, "lease_epoch": 1, "acked": 1 }
    ]
  },
  "final_tasks": [
    { "task_id": "demo-steer", "state": "RUNNING", "lease_epoch": 1, "claimed_by": "demo-worker", "cancel_requested_at": null },
    { "task_id": "demo-stop",  "state": "RUNNING", "lease_epoch": 1, "claimed_by": "demo-worker", "cancel_requested_at": 1793462889.0522554 }
  ],
  "note": "stop 只表达意图：库里 state 仍是 RUNNING、cancel_requested_at 已置；RUNNING -> CANCELLED 的收敛由后续阶段的承载层在迭代边界完成。"
}
EXIT=0
```

（`worker_saw.polls_used=5`：控制进程 sleep 0.2s 后投递，worker 每 0.05s poll 一轮。）

## 4. 观察：决议没写、但实现与后续阶段必须注意

1. **stale-ack 的方向性（已按主控裁定修复，用例 ④ 锁定）**。原实现 `lease_epoch <> :epoch`
   字面符合 D2，但"残留"是有方向的：僵尸 worker（旧 epoch）醒来 poll 一次，会把**现役
   worker 尚未 ack 的指令**当残留 ack 掉（实测 cmd 2 被吞）。裁定后 `control.py` 改为严格
   小于 `<`；把 SQL 还原成 `<>` 跑 ④ 即红：
   `僵尸 worker 的 poll 把现役指令 cmd_id=2 ack 掉了（D2 必须是严格小于）`。
   未采用"先校验 `tasks.lease_epoch = :epoch`"的修法——那会让僵尸连自己时代的指令都取不到。
2. `request_stop` 对同一 RUNNING 任务调用两次会写 **2 条** stop，无去重。决议未要求去重，但 worker 侧必须幂等。
3. `poll` 对不存在的 task 返回 `[]` 而非抛错。跨进程下 worker 收尾 poll 已删任务不炸，合理；但调用方不能把 `[]` 当"任务还在"。
4. `TaskView.goal` 只能从 `card_json` 反序列化（`tasks` 表无 goal 列）。绕过 `Store.enqueue` 造数的路径必须写合法 card_json，否则 goal 静默变空串而不是报错。
5. 测试造层级必须补 `parent_task_id`：`Store.enqueue` 把它写死为 NULL。测试里只 `UPDATE` 这一列，不碰 `state`。
6. 跨进程必须用文件库：`:memory:` 下每条连接各是一个空库，"子进程写、父进程读"根本没被验证，会得到假绿。
7. 连接必须是自动提交（`isolation_level=None`）：`Control` 自己发 `BEGIN IMMEDIATE`，连接上残留事务会直接抛 `OperationalError`。
