# 阶段 4.5 · `Store` 公开只读接口（清掉 9 处私有访问）

> 性质：重构，不改行为。全量 **285 passed / 2 skipped / 1 xfailed**（重构前 279）。

## 一、为什么做

`dispatcher` / `worker` / `supervisor` / `redispatch` 四个模块共 **9 处**直接访问 `Store` 的私有成员。这是封装泄漏：store 一改内部结构，四个模块同时坏，且没有任何编译期信号。

它是"同一问题第三次出现"才被升级为 P1 的——前两次各自被记成 P2 债，结果债会自己繁殖。

## 二、清点（迁移前实测）

| 模块 | 私有成员 | 处数 |
|---|---|---|
| `dispatcher.py` | `_conn` | 1 |
| `worker.py` | `_now` | 1 |
| `supervisor.py` | `_conn`（别名后 7 处查询）、`_write_tx` | 8 |
| `redispatch.py` | `_conn`、`_write_tx`、`_record_event` | 3 |

## 三、新增的公开接口（4 个）

| 接口 | 替代 | 说明 |
|---|---|---|
| `Store.now`（property） | `store._now` | 跨模块必须共用同一时钟，否则测试里注入的假时钟只对 store 生效 |
| `Store.query(sql, params)` | `store._conn.execute(...)` | **只接受 SELECT**，其余抛 `ValueError` |
| `Store.write_tx()` | `store._write_tx()` | 同一个 `BEGIN IMMEDIATE` 实现，允许跨模块 |
| `Store.record_event(conn, ...)` | `store._record_event(...)` | 在调用方事务里写审计事件 |

### 关键设计：`query()` 的 SELECT 守卫

S1 要求 `Supervisor.scan()` **零写操作**，此前靠约定维持。现在守卫在唯一入口上：写语句直接抛 `ValueError`，误写会在开发期炸掉，而不是在生产里悄悄改坏状态。

**刻意不支持 `WITH`**：SQLite 允许 `WITH ... DELETE`，放行 CTE 等于放行写操作。需要 CTE 的只读查询请改成子查询。

### 关键设计：`Rows`

`query()` 返回 `Rows`（`list[sqlite3.Row]` 子类，保留 `fetchall()` / `fetchone()`）。

理由：迁移应当只改"访问私有成员"这一件事。调用方原本写 `store._conn.execute(sql, p).fetchall()`，迁到 `store.query(sql, p)` 后不必再重写 7 处多行调用的收尾——**可审阅的 diff 比漂亮的 API 更重要**。

## 四、迁移结果

```
$ grep -n "_conn\|_write_tx\|_record_event" dispatcher.py worker.py supervisor.py redispatch.py
（仅剩 docstring 里的历史说明，代码零命中）
```

三处 docstring 同步更新（它们原本写着"借私有连接是刻意的耦合"，现在描述公开入口）——文档与实现不一致是本项目反复出问题的地方，不能留着。

## 五、防回归

新增 `test_orchestration_modules_do_not_touch_store_internals`：用 **AST** 遍历四个模块，检查真实的 `ast.Attribute` 节点，禁止 `._conn` / `._write_tx` / `._record_event`，以及 `store._now`。

**为什么用 AST 不用 grep**：docstring 里会提到 `store._conn` 这类历史说明，grep 会误报；只有看 AST 节点才准。

变异验证：

```
注入一处 _conn 后返回码: 1
FAILED test_orchestration_modules_do_not_touch_store_internals
=> lint 测试能抓住回归
已还原: True
```

## 六、其余测试（5 条）

| 测试 | 钉住的契约 |
|---|---|
| `test_query_accepts_select_only` | UPDATE / DELETE / INSERT / `WITH ... DELETE` / 空串 全部抛 `ValueError` |
| `test_query_returns_rows_with_cursor_helpers` | `Rows` 既是 list 又能 `fetchall`/`fetchone`；空结果 `fetchone()` 为 `None` |
| `test_now_property_exposes_injected_clock` | 时钟可跨模块共用 |
| `test_write_tx_rolls_back_on_exception` | 公开事务与内部实现同语义：异常整体回滚 |
| `test_record_event_writes_in_caller_transaction` | 事务回滚后事件也消失——同事务是这条 API 的意义 |

## 七、遗留

`Store.query()` 放行任意 SELECT，调用方仍可写低效查询（无 LIMIT、全表扫）。这不在本次范围——本次只解决"访问私有成员"，不解决"查询质量"。

`workers` 表仍无写入方，`supervisor` 的 `_WORKER_HEARTBEAT_TTL` 仍是常量。
