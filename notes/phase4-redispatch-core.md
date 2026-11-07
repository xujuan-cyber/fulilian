# 阶段 4 · redispatch-core 交付笔记（v2，按主控裁定修订）

## 0. 改动范围

- 新增 `agent/orchestration/redispatch.py`（235 行）
- 新增 `tests/orchestration/test_redispatch.py`（232 行）
- **未改** `store.py` / `schema.py` / `contracts.py` / `state_machine.py` /
  `supervisor.py` / `worker.py` / `launcher.py` / `tools/`

## 1. 签名（`inspect.signature` 原文）

```
RedispatchPlan: (task_id: 'str', resume_from_cursor: 'str | None', route_changed: 'bool', consumes_handoff: 'bool', reason: 'str', new_route_fingerprint: 'str | None' = None) -> None
Redispatcher.__init__ (self, store: 'Store', *, now: 'Callable[[], float]' = <built-in function time>) -> 'None'
Redispatcher.plan (self, task_id: 'str', *, new_route_fingerprint: 'str | None' = None) -> 'RedispatchPlan'
Redispatcher.apply (self, plan: 'RedispatchPlan') -> 'None'
fields: ['task_id', 'resume_from_cursor', 'route_changed', 'consumes_handoff', 'reason', 'new_route_fingerprint']
last default: None
```

`new_route_fingerprint` 是 v2 追加的第 6 字段（带默认值）；其余 5 字段与决议 §二逐字一致，`frozen=True, slots=True`。

## 2. 豁免路径 SQL（`_EXEMPT_UPDATE` 原文，redispatch.py:63-76）

```sql
UPDATE tasks SET
    state = :queued,
    -- COALESCE 而不是直接赋值：指纹为 None 时保持原值，绝不写成 NULL。
    -- 写掉旧指纹等于把"上次用的方案"抹了，下次比对就没有基线了。
    route_fingerprint = COALESCE(:route_fingerprint, route_fingerprint),
    claimed_by = NULL,
    lease_expires = NULL,
    block_reason = NULL,
    updated_at = :now
WHERE task_id = :task_id
  AND state = :blocked
  AND lease_epoch = :lease_epoch
```

- 与 `store.redispatch` 的差别只有两点：**没有** `handoff_count + 1`；**多了**
  `route_fingerprint` 写回（v2 裁定）。
- 没有 `cursor_json` 这一列 → S5 的续跑点物理上不可能被写掉。
- `AND state = :blocked AND lease_epoch = :lease_epoch` 是并发闸；`rowcount != 1`
  抛 `NotClaimableError`，不按"看起来成功"提交（redispatch.py:221-225）。
- 事务：`with store._write_tx()`（`BEGIN IMMEDIATE`），`transition()` 抛异常时
  自动 ROLLBACK。
- 审计：同事务内 `_record_event(kind='redispatch_exempt')`（redispatch.py:226-235）。

## 3. 决议落点（真实行号）

| 决议 | 行号 | 内容 |
|---|---|---|
| S4 | 133-137 | `route_changed = (new is not None and new != current)`；`consumes_handoff = not route_changed` |
| S4 | 177-235 | `_apply_exempt()`：`transition()` 202、`_EXEMPT_UPDATE` 211 |
| S4 | 19-21 | docstring 写死"豁免是不记账，不是免死金牌" |
| S5 | 156 | `resume_from_cursor=row["cursor_json"]`（读出，不清空） |
| S5 | 63-76 | 豁免 UPDATE 无 `cursor_json`；普通路径走 `store.redispatch`，同样不动该列 |
| S6 | 163-173 | `apply()` 无 try/except；171 行 `store.redispatch()` 的异常原样外抛 |
| S6 | 202-209 | 豁免路径传**真实** `handoff_count` 过 `handoff_cap` 守卫 |
| v2 | 160 / 68 | `plan()` 填 `new_route_fingerprint`；`apply()` 同一条 UPDATE 写回 |

## 4. 测试

```
$ ./venv/bin/python -m pytest tests/orchestration/test_redispatch.py -q
......                                                                   [100%]
6 passed in 0.31s
```

6 个 = §四 的 4 个固定名 + `test_apply_persists_new_route_fingerprint`（v2 裁定）
+ `test_plan_rejects_task_that_is_not_blocked`。所有 BLOCKED 前置都走真实路径
`enqueue -> claim -> 租约过期 -> patrol()`，不直接 UPDATE `state`。

## 5. 能失败的验证（两次，均已还原 byte-identical）

**(a) S4 豁免必须不记账** —— 往 `_EXEMPT_UPDATE` 注入 `handoff_count = handoff_count + 1,`：

```
.F...                                                                    [100%]
>       assert row["handoff_count"] == 1  # 豁免：预算一个没扣
E       assert 2 == 1
FAILED tests/orchestration/test_redispatch.py::test_route_change_exempts_handoff
1 failed, 5 passed
```

**(b) v2 指纹必须落库** —— 删掉 `route_fingerprint = COALESCE(...)` 那一行：

```
....F.                                                                   [100%]
>       assert row["route_fingerprint"] == "route-b"
E       AssertionError: assert 'route-a' == 'route-b'
FAILED tests/orchestration/test_redispatch.py::test_apply_persists_new_route_fingerprint
1 failed, 5 passed
```

两次均 `RESTORED byte-identical: True`，复跑 6 passed。

## 6. 主控裁定落点

**(a) 豁免仍过 cap 守卫（保持）**：`_apply_exempt` 把真实 `handoff_count` 传给
`transition()`。归零骗守卫会让 `handoff_cap` 彻底失效（换指纹即可无限重派），
所以"预算耗尽"必须仍可见、仍拦截。已在模块 docstring（19-21 行）与方法
docstring（180-186 行）写死："豁免是不记账，不是免死金牌；此时正确处置是人工
介入，不是 bug"。

**(b) 冻结签名缺口（已修）**：`RedispatchPlan` 追加 `new_route_fingerprint=None`，
`plan()` 填充，`apply()` 同一条 UPDATE 写回；`None` 时靠 `COALESCE` 保持原值。
关键断言在 `test_apply_persists_new_route_fingerprint`：写回后再 `plan()` 传同一
指纹，`route_changed is False` → 豁免不会无限重复。

## 7. 私有 API 依赖（技术债，auditor 请记档）

| 私有成员 | 用途 | 若 store 重构 |
|---|---|---|
| `Store._conn` | `plan()` 的只读 SELECT | 需改为公开只读接口 |
| `Store._write_tx()` | 豁免路径的 `BEGIN IMMEDIATE` 事务 | 需公开事务入口 |
| `Store._record_event()` | 审计事件，借它只为与 store 事件格式一致 | **需同步**，否则事件字段漂移 |

依据决议 §三 S4"允许在 redispatch.py 里写 SQL"；未新增任何 store 方法，
也未修改任何已有方法。
