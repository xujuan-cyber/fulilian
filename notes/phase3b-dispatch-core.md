# 阶段 3b · `dispatcher.py` 交付记录（dispatch-core）

文件：`agent/orchestration/dispatcher.py`（147 行）、`tests/orchestration/test_dispatcher.py`（283 行，23 条含参数化）。
规格：`docs/design/orchestration-phase3b-worker-decisions.md`（§三 冻结签名 + W6/W7/W8），含 team-lead 对三处口径的裁定（见 §6）。

## 1. 实际签名（`inspect.signature` 原文）

```
Tier                    :: [<Tier.INLINE: 'inline'>, <Tier.EMBEDDED: 'embedded'>, <Tier.DAEMON: 'daemon'>]
Backoff                 :: (base: 'float' = 0.05, cap: 'float' = 2.0) -> None
Backoff.delay           :: (self, attempt: 'int', *, rand: 'Callable[[], float]' = <built-in method random of Random object at 0x...>) -> 'float'
Dispatcher.__init__     :: (self, store: 'Store', *, backoff: 'Backoff | None' = None, now: 'Callable[[], float]' = <built-in function time>) -> 'None'
Dispatcher.choose_tier  :: (self, card: 'TaskCard', *, requested: 'Tier | None' = None) -> 'Tier'
Dispatcher.sample       :: (self, pool: 'str', *, limit: 'int' = 32) -> 'list[str]'
Dispatcher.poll_delay   :: (self, attempt: 'int') -> 'float'
```

与 §三 逐字一致：无增删参数、默认值未改（`base=0.05`、`cap=2.0`、`limit=32`、`now=time.time`）。
`Tier` 用 `enum.Enum`（不是 `StrEnum`），照抄决议原文。

## 2. `sample()` 的完整 SQL 与 `Store.claim` 排序子句

```
dispatcher.py:36  _SAMPLE_ORDER = "is_key DESC, priority DESC, bottom_level DESC, created_at ASC"
store.py:66       _CLAIM_ORDER  = "is_key DESC, priority DESC, bottom_level DESC, created_at ASC"
```

```sql
-- dispatcher.py:39（W7：纯 SELECT，无 BEGIN / 无 UPDATE / 无 claimed_by）
SELECT task_id FROM tasks WHERE state = ? AND pool = ? ORDER BY is_key DESC, priority DESC, bottom_level DESC, created_at ASC LIMIT ?

-- store.py:72（claim 事务内的 re-read，同一子句）
SELECT task_id, lease_epoch, attempts, card_json FROM tasks WHERE state = ? AND pool = ? ORDER BY is_key DESC, priority DESC, bottom_level DESC, created_at ASC LIMIT 1
```

两份常量各持一份（dispatcher 不 import store 的私有名），一致性由 `test_sample_order_matches_claim_order` 双向钉住：先断言两常量相等，再实测 `sample()` 序列 `==` 反复 `store.claim()` 得到的序列。

## 3. W6 / W7 / W8 落点（真实行号）

| 决议 | 行号 | 内容 |
|---|---|---|
| W6 档位判定 | 103–116 | 112 `requested is not None` 优先返回；114 `is Isolation.PROCESS → DAEMON`；116 兜底 `return Tier.EMBEDDED`（**不是 INLINE**）；`isolation is None` 同落 116 |
| W7 只读采样 | 120–140 | 36/39 常量与 SQL；136 `limit <= 0` 显式挡掉（SQLite 的 `LIMIT -1` = 不限）；139–140 只 `execute(...).fetchall()`，全函数零 UPDATE / 零 BEGIN |
| W8 退避 | 65–79、145–147 | 78 `min(base * 2**attempt, cap)` 先封顶；79 再乘 `0.5 + 0.5*rand()`（**只向下抖**）；`attempt` 从 0 起；145 `poll_delay` 纯委托注入的 `Backoff` |
| 分层 | 27–32 | 仅 import `enum/random/time/dataclasses/typing` + `contracts` + `store`；无 `tools.*`、无 `worker`（`test_dispatcher_imports_no_tools_and_no_worker` 兜底） |

三处口径（§6 已裁定）：

- **抖动只向下**：`d = min(base*2**n, cap)`，返回 `d * (0.5 + 0.5*rand())`，因子 `[0.5, 1.0)`。`cap` 是**硬上界**（返回值 `<= cap`），区间 `[0.5d, d]` 仍有 2 倍跨度；封顶后各 worker 的 `d` 相同但因子不同，不会收敛到同一点。
- **`now` 预留**：签名要求它，当前无人读，docstring 已写明"阶段 4 的 `sample(created_before=...)` 时间过滤才会用到"；保留 `self._now`。
- **`store._conn` 记 P2 债**：docstring 已写"阶段 3c 应给 `Store` 加公开的 `sample_ids(pool, limit)`，届时切换；现在加会与 `worker-core` 正在改的 `store.py` 冲突"。纯 SELECT 不开事务，不违反 D2。

## 4. 测试

```
$ ./venv/bin/python -m pytest tests/orchestration/test_dispatcher.py -q
.......................                                                  [100%]
23 passed in 1.41s
```

无回归（`tests/orchestration` 上一轮全量 229 passed / 2 skipped / 1 xfailed；本次只动 dispatcher 与其测试）。覆盖：
`test_choose_tier_maps_isolation_to_tier`、`test_choose_tier_default_is_not_inline`、
`test_choose_tier_honours_explicit_request`（9 组）、`test_sample_does_not_claim`、
`test_sample_repeatedly_does_not_claim`、`test_sample_order_matches_claim_order`、
`test_sample_respects_limit`、`test_sample_empty_pool_returns_empty`、
`test_backoff_jitter_within_bounds`、`test_backoff_never_exceeds_cap_under_extreme_jitter`、
`test_backoff_doubles_then_plateaus`、`test_poll_delay_delegates_to_backoff`、
`test_dispatcher_imports_no_tools_and_no_worker`。

`test_sample_does_not_claim` 断言四层：`state == 'QUEUED'`、`claimed_by is None`、
`attempts == 0`、整行 `dict(row) == before`（后者兜住 `lease_epoch/lease_expires/updated_at`）。

## 5. "能失败"验证（W7 反证）

把 `sample()` 改成顺手 `UPDATE tasks SET claimed_by = 'sneaky'`（**故意不改 `state`、不增 `attempts`**），即"悄悄 claim 又装作没采"：

```
.............FF.......                                                   [100%]
>           assert row["claimed_by"] is None
E           AssertionError: assert 'sneaky' is None
tests/orchestration/test_dispatcher.py:144: AssertionError
>       assert dict(_row(store, "t1")) == before
E         Differing items:
E         {'claimed_by': 'sneaky'} != {'claimed_by': None}
tests/orchestration/test_dispatcher.py:159: AssertionError
FAILED tests/orchestration/test_dispatcher.py::test_sample_does_not_claim
FAILED tests/orchestration/test_dispatcher.py::test_sample_repeatedly_does_not_claim
2 failed, 21 passed in 1.43s
exit: 1
restored byte-identical: True
```

`state == 'QUEUED'` 与 `attempts == 0` 两条断言在这个反例下**依然通过**——正是"只断言
state 会被骗过"的证据。改回后重跑 23 passed（§4）。

## 6. 裁定后的改动（相对首版）

1. **抖动改向下**（`0.5 + rand()` → `0.5 + 0.5*rand()`）：首版上界是 `1.5*cap`，`cap` 名不副实。现返回 `<= cap`；新增 `test_backoff_never_exceeds_cap_under_extreme_jitter`（注入 `rand=1.0` 打上边界），`test_backoff_doubles_then_plateaus` 改注入 `rand=1.0` 读未抖动基数。
2. **`now` 标为预留**：docstring 写明阶段 4 的 `sample(created_before=...)` 会读它，代码保留。
3. **`sample` 的 `store._conn` 标 P2 债**：只补注释，未改 `store.py`（`worker-core` 正在其中加 `cancel()`，不并发写）。
