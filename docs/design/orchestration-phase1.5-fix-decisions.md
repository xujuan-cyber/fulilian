# 阶段 1.5 冻结决议 · PR-1 修复清单

> 主控裁定，**不可由执行者自行改动**。凡与本文件冲突的实现一律返工。
> 来源：`docs/design/orchestration-pr1-code-review-findings.md`（P0×1 / P1×8 / P2×16）
> 本阶段目标：把 PR-1 修到可合入，**并冻结阶段 2 依赖的 schema 契约**。

---

## 一、P0 修法（唯一阻塞项）

**问题**：`RUNNING → BLOCKED → QUEUED` 崩溃恢复路径无任何上限守卫，而 `state_machine.py` 的 docstring 写着"崩溃循环由 attempts / handoff_count 兜住"。

**裁定：约束下沉到状态机，给 `BLOCKED → QUEUED` 加守卫。**

理由：如果只靠 `redispatch` 的 `handoff_cap`，漏写一处就是无限循环，且报错点离现场很远。状态机是唯一能保证"任何调用方都绕不过"的位置。

### 实现要求

`transition()` 签名增加两个参数：

```python
def transition(
    current: TaskState,
    target: TaskState,
    *,
    lease_expired: bool = False,
    attempts: int = 0,
    max_retries: int = 1,
    handoff_count: int = 0,
    handoff_cap: int = 2,
) -> TaskState:
```

守卫共三条：

| 边 | 守卫 | 不满足时 |
|---|---|---|
| `RUNNING → QUEUED` | `lease_expired=True` | 抛 `IllegalTransitionError` |
| `FAILED → QUEUED` | `attempts <= max_retries` | 抛 |
| `BLOCKED → QUEUED` | `handoff_count < handoff_cap` | 抛 |

**必须加一条测试** `test_blocked_to_queued_rejected_when_handoff_cap_reached`：`handoff_count == handoff_cap` 时抛错，`handoff_count == handoff_cap - 1` 时放行。

同时修正 docstring：把"崩溃循环由 attempts / handoff_count 兜住"改成"由 `BLOCKED → QUEUED` 的 `handoff_cap` 守卫兜住"——文档必须描述实际存在的约束。

---

## 二、契约层修正（3 项）

### 2.1 `isolation` 默认值改回 `None`（安全，最高优先）

- 现状：`TaskCard.isolation: Isolation = Isolation.INLINE`
- 改为：`TaskCard.isolation: Isolation | None = None`
- 语义：`None` = **自动推断**，推断规则按方案 §4.5——`allowed_toolsets is None` → `PROCESS`（保守）。
- 理由：当前默认值绕过了 fail-safe。不写 isolation 的任务会在主进程里跑，一次段错误拖垮整队。DDL 的 `DEFAULT 'process'` 保持不变。

### 2.2 `max_retries` 三处口径统一为 1

- `TaskCard.max_retries: int = 1`（现在是 0）
- `transition(..., max_retries: int = 1)`（保持）
- `config.retry_cap: int = 1`（保持）
- **`transition` 的 `max_retries` 改为必传**（去掉默认值）：默认值朝"放行"方向偏是最危险的默认，强制调用方显式给出。

### 2.3 `validate_card` 补校验

| 字段 | 规则 |
|---|---|
| `goal` | 非空、去空白后非空 |
| `role` / `isolation` | 必须是合法枚举值（isolation 允许 `None`） |
| `priority` | 必须是 `int` 且非 bool |
| `tier` | 必须是 `TaskTier` |
| `dod` | 必须是 `tuple`；传 list 直接报错，**不得静默转换** |
| `output_path` | `os.path.isabs` + `os.path.normpath(p) == p`（拒绝 `..` 段） |
| `task_id` | 只允许 `[A-Za-z0-9._-]`，长度 1–128 |

`task_id` 与 `output_path` 的校验是安全项，**不得省略**。

---

## 三、Schema 修正（6 项，冻结为阶段 2 的契约）

| # | 改动 | 说明 |
|---|---|---|
| S1 | 新增列 `depth INTEGER NOT NULL DEFAULT 0` | 不能用 parent 链递归推导：handoff 会改 `parent_task_id`，重挂后链长 ≠ 逻辑 depth |
| S2 | `batch_id` 改为 `TEXT NOT NULL` + `CHECK (batch_id <> '')` | 空串放行会让所有单任务共享 `batch_id=''`，`list` 一次全捞。**单任务以 `task_id` 作 batch_id**，此语义写进列注释 |
| S3 | `output_path` 改为 `NOT NULL` | 契约层已要求绝对路径，DDL 必须一致；否则部分唯一索引对 NULL 静默失效 |
| S4 | `idx_tasks_lock` / `idx_tasks_queueing_lock` 加 `AND state NOT IN (终态)` | 否则"运行期互斥"退化成"每个 lock 值全生命周期只能用一次"，阶段 3 第二个任务起 INSERT 必失败 |
| S5 | `schema_version` 加 `PRIMARY KEY (version)` | 无唯一约束时并发初始化会写多行 |
| S6 | `role` / `pool` 补 `DEFAULT 'leaf'` / `DEFAULT 'solve'` | 与 `isolation` 等列保持一致，减少 store 的必填项 |

**`SCHEMA_VERSION` 保持 1**：尚未发布，无存量库，不引入迁移分支。

### 必须删除的一条测试

`tests/orchestration/test_schema.py::test_null_output_path_is_not_unique` —— 它把"NULL 绕过唯一索引"这个缺陷写成了期望。S3 落地后它必然失败，**删掉，不要改成 skip**。

---

## 四、明确不修（留到后续阶段）

| 项 | 原因 |
|---|---|
| `apply_schema` 的"单事务"注释与逐条提交不符 | 需要真正的事务包装，属阶段 2b |
| `applied < SCHEMA_VERSION` 无迁移分支 | 无存量库，阶段 2b 补 |
| `idx_tasks_claim` 中 `state` 位于 `pool` 之后 | 阶段 3 全局领取时再评估，现在改会牵动排序语义 |
| `PRAGMA foreign_keys` 无外键 | 全库零外键声明，属阶段 2b |
| `validate()` 放行 NaN/inf | 阶段 2 的 config 消费方一起修 |
| 派生列与 `card_json` 的取值域约束 | 阶段 2b（`card_hash` 校验在 insert 路径） |

---

## 五、验收标准（全部必须满足）

1. `pytest tests/orchestration tests/agent/test_delegation_config_contract.py -q` 全绿，用例数 **≥ 160**（当前 155，新增守卫与校验用例后应增加）。
2. 新增测试至少覆盖：
   - `test_blocked_to_queued_rejected_when_handoff_cap_reached`
   - `test_task_card_isolation_defaults_to_none`
   - `test_validate_card_rejects_path_traversal`
   - `test_validate_card_rejects_non_identifier_task_id`
   - `test_depth_column_exists_and_defaults_to_zero`
   - `test_batch_id_rejects_empty_string`
   - `test_lock_index_is_scoped_to_active_states`
   - `test_schema_version_has_primary_key`
3. `grep -rn "from tools\|import tools" agent/orchestration/` 无输出。
4. `python -c "from agent.orchestration.state_machine import _ALLOWED; ..."` 转移表**不变**——本次只加守卫，不改边。若有人动了表，`test_allowed_table_matches_spec_literal` 会红，**红就是错，不要改测试**。
5. 每条改动在报告里贴出**改动前后的实际代码**，不接受"已修复"三个字。
