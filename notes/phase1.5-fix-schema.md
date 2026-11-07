# 阶段 1.5 · Schema 修正（S1–S6）交付说明

范围：只改 `agent/orchestration/schema.py`、`tests/orchestration/test_schema.py`、
`tests/orchestration/test_invariants.py`。`SCHEMA_VERSION` 保持 1，无迁移分支。

## 1. S1 — 新增 `depth`

```sql
-- before
parent_task_id      TEXT,
role                TEXT NOT NULL,
-- after
parent_task_id      TEXT,
-- S1: logical DAG depth. Not derivable from the parent chain -- a
-- handoff rewrites parent_task_id, so chain length != logical depth.
depth               INTEGER NOT NULL DEFAULT 0,
```

实测：`PRAGMA table_info(tasks)` → `(3, 'depth', 'INTEGER', 1, '0', 0)`（notnull=1，默认 0）。

## 2. S2 — `batch_id` 非空

```sql
-- before
batch_id            TEXT NOT NULL,
-- after
-- S2: a single-task job uses its own task_id as batch_id. '' is not a
-- batch: it would make every single-task job share one batch and a
-- single `list` call would return all of them.
batch_id            TEXT NOT NULL CHECK (batch_id <> ''),
```

实测：插入 `batch_id=''` → `IntegrityError: CHECK constraint failed: batch_id <> ''`。

## 3. S3 — `output_path NOT NULL`

```sql
-- before
output_path         TEXT,
-- after
-- S3: the contract layer requires an absolute path; the DDL must
-- agree or the partial unique index silently ignores NULLs.
output_path         TEXT NOT NULL,
```

实测：连插两行 `output_path=NULL`，两次都
`IntegrityError: NOT NULL constraint failed: tasks.output_path`。

## 4. S4 — lock 索引收窄到活跃态

```sql
-- before
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_lock ON tasks(lock) WHERE lock IS NOT NULL;
-- after
CREATE UNIQUE INDEX idx_tasks_lock ON tasks(lock)
 WHERE lock IS NOT NULL AND state NOT IN ('SUCCEEDED','FAILED','INTERRUPTED','CANCELLED');
```

`idx_tasks_queueing_lock` 同改（`queueing_lock IS NOT NULL AND state NOT IN (...)`）。

实测：`t-lock-a`(SUCCEEDED) 与 `t-lock-b`(QUEUED) 共用 `worktree-1` → 两行都插入成功；
再加 `t-lock-c`(RUNNING, 同 lock) → `UNIQUE constraint failed: tasks.lock`（活跃态仍互斥）。

## 5. S5 — `schema_version.version` 主键

```sql
-- before
version    INTEGER NOT NULL,
-- after
-- S5: PK, otherwise concurrent initialisation writes several rows.
version    INTEGER NOT NULL PRIMARY KEY,
```

`apply_schema` 的写入改为 `INSERT OR IGNORE INTO schema_version ...`。
实测：连续两次 `apply_schema` 后 `SELECT COUNT(*) FROM schema_version` = 1；
`PRAGMA table_info(schema_version)` → `(0,'version','INTEGER',1,None,1)`（pk=1）。

## 6. S6 — `role` / `pool` 默认值

```sql
-- before
role                TEXT NOT NULL,
pool                TEXT NOT NULL,
-- after
role                TEXT NOT NULL DEFAULT 'leaf',
pool                TEXT NOT NULL DEFAULT 'solve',
```

实测：只给 `task_id/batch_id/card_json/output_path/created_at/updated_at` 插入，
读回 `(depth, role, pool, isolation, state) = (0, 'leaf', 'solve', 'process', 'QUEUED')`。

## 7. 测试改动

删除：`test_null_output_path_is_not_unique`（把 NULL 绕过唯一索引写成期望）。

新增（`test_schema.py`）：
- `test_depth_column_exists_and_defaults_to_zero` — 列存在、INTEGER、notnull=1、默认 `0`、插入取 0。
- `test_batch_id_rejects_empty_string` — `''` 抛 IntegrityError；`batch_id == task_id` 可写。
- `test_output_path_is_not_null` — 两次 NULL 插入都抛，且表内 0 行。
- `test_lock_indexes_are_scoped_to_active_states` — 两个索引的 DDL 含 `state not in (` 与四个终态；
  终态释放 lock、活跃态仍冲突。
- `test_schema_version_has_primary_key` — `pk==1`；重复写同版本抛 IntegrityError。
- `test_role_pool_isolation_defaults` — `('leaf','solve','process','QUEUED')`。

连锁修复：`test_schema._insert_task` 的 `output_path=None` 调用改为显式路径
（`test_null_idempotency_key_allows_many`）；`test_invariants._insert_task` 默认
`output_path=None` 并在 SQL 参数处回落为 `f"out/{task_id}.md"`，避免 NOT NULL 连锁失败。

## 8. 测试输出原文
```
$ ./venv/bin/python -m pytest tests/orchestration/test_schema.py tests/orchestration/test_invariants.py -q
.................................sx....s.....                            [100%]
42 passed, 2 skipped, 1 xfailed in 2.25s
```

改动前同命令：`37 passed, 2 skipped, 1 xfailed`（用例数 37→42）。

## 9. 未解决

无阻塞。按指令只跑上述两个文件；其余 orchestration 测试不建库，不受本次 DDL 影响。
