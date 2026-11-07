# 阶段 5 · R6 · fenced 产物作废（`artifact-core`）

只改 `worker.py` / `test_worker.py`；未碰 launcher、reaper、store、schema、contracts、state_machine、control、dispatcher、supervisor、redispatch、`tools/`。

## 一、真实行号（`worker.py`，442 行）

| 行 | 内容 |
|---|---|
| 30 | `import os` |
| 231 | `output_path = result.output_path or default_output_path` |
| 248-259 | `except FencedOutError:` → `self._void_artifact(output_path, ctx)` |
| 261-344 | `_void_artifact()`：查库判归属 → 改名 → 任何失败只记日志 |

## 二、判据：问数据库"谁持有"，不问文件"是不是我的"

文件身份在真实时序下无效：`identity` 只能在 `_land` 入口取，而那时租约已经丢了（否则 `complete()` 不会
抛 `FencedOutError`）。W2 若在 W1 的 execute 期间就写完，stat 拿到的就是 W2 的文件，比对必然"相同"→ 照样
误作废。**`_stat_identity` 已删除**：原理失效的判据留着只能骗人，也没有测试能为它变红。

现在查一行 `SELECT state, claimed_by FROM tasks WHERE task_id = ?`，跳过作废的条件：`SUCCEEDED`（结果已被
承认，绝不碰）；`claimed_by` 非空且不是自己（文件可能已是新持有者的）；查询本身失败（不动文件——留着可
恢复，删了不可逆）。其余（QUEUED/BLOCKED/FAILED/CANCELLED，或持有者就是自己）→ 作废。

**有意为之的代价**：抢租约后旧 worker 的产物会留在 canonical 路径（新持有者还没成功时）。宁可留一个可能
是旧的产物，也不抹掉一个可能是被承认的结果；`patrol`/`redispatch` 会推走该行，下一轮按新持有者再判。

## 三、代码（`worker.py:261-344`，日志文本为排版权宜略作压缩）

```python
    def _void_artifact(self, output_path: str | None, ctx: WorkerContext) -> None:
        """R6：除非有人持有/已被承认，把 fenced 产物改名到 .fenced-{epoch}。"""
        if not output_path:
            return
        try:
            row = self._store.query(
                "SELECT state, claimed_by FROM tasks WHERE task_id = ?",
                (ctx.task_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("查询任务归属失败，不作废：task_id=%s：%s", ctx.task_id, exc)
            return
        if row is not None:
            if str(row["state"]) == "SUCCEEDED":
                logger.warning("任务已被承认（SUCCEEDED），不作废：task_id=%s", ctx.task_id)
                return
            holder = row["claimed_by"]
            if holder is not None and str(holder) != ctx.worker_id:
                logger.warning("任务已被新持有者 %s 持有，不作废：task_id=%s", str(holder), ctx.task_id)
                return
        fenced_path = f"{output_path}.fenced-{ctx.lease_epoch}"
        try:
            os.replace(output_path, fenced_path)
        except FileNotFoundError:
            logger.info("产物在作废前消失：task_id=%s", ctx.task_id)
        except OSError as exc:
            logger.warning("产物改名失败，放弃作废：task_id=%s：%s", ctx.task_id, exc)
        else:
            logger.warning("产物已作废：task_id=%s path=%s -> %s", ctx.task_id, output_path, fenced_path)
```

## 四、`pytest tests/orchestration/test_worker.py -q` 原文

```
...........
11 passed in 2.56s
```

## 五、变异验证（两次都必须红，均已还原）

去掉 `claimed_by` 判断 → `..._not_voided_when_rewritten_by_new_holder`：

```
E       AssertionError: W2 的有效产物被作废了
1 failed in 0.30s  |  exit code = 1
```

去掉 `SUCCEEDED` 判断 → `..._not_voided_when_task_succeeded`：

```
E       AssertionError: 已被承认的产物被旧 worker 作废了
1 failed in 0.31s  |  exit code = 1
```

`_stat_identity` 已删除，故"去掉它是否变红"不再适用：代码里已无这条判据。

## 六、R6 的五条测试（`..._is_renamed` 用 SQL 推进 epoch，其余走真实 patrol→redispatch 链路）

`test_fenced_artifact_is_renamed`（324）／`..._rename_failure_does_not_raise`（355）／`..._not_voided_when_rewritten_by_new_holder`（384，patrol→redispatch→w2 领走并写入）／
`..._voided_when_task_not_held`（427，BLOCKED 无人持有 → 仍作废）／`..._not_voided_when_task_succeeded`（466）。已 `Read` 读回 `worker.py:231-344` 与上述用例。
