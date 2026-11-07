# 阶段 1.5 验收记录

> 验收人：team-lead｜时点：2026-10-31 21:0x｜依据：`orchestration-phase1.5-fix-decisions.md` §五
> 方式：主控独立探针 + 逐条对照决议，不采信成员自述。

## 结论：通过

| 决议要求 | 实测 | 结果 |
|---|---|---|
| 测试 ≥160 | **190 passed / 2 skipped / 1 xfailed** | 通过（超 30） |
| 8 条指定测试存在 | 8/8 存在（`test_lock_indexes_are_scoped_to_active_states` 为复数命名） | 通过 |
| 分层零 `tools.*` | `grep` 无输出 | 通过 |
| `_ALLOWED` 不变 | 逐状态与规格比对，8/8 相等，键集一致 | 通过 |
| 改动前后代码片段 | 见 `notes/phase1.5-fix-contracts.md` / `-schema.md` | 通过 |

## P0 实测

```
BLOCKED->QUEUED handoff_count=2 cap=2  -> IllegalTransitionError  ✓
BLOCKED->QUEUED handoff_count=1 cap=2  -> 放行                    ✓
FAILED->QUEUED  attempts=1 max_retries=1 -> 放行                  ✓
RUNNING->QUEUED 未过期                 -> IllegalTransitionError  ✓
```

## S1–S6 实测（10 项探针全过）

depth 列存在且 `NOT NULL DEFAULT 0`；`batch_id=''` 被 CHECK 拒；`output_path` 已 `NOT NULL`；
`idx_tasks_lock` / `idx_tasks_queueing_lock` 均含 `state NOT IN (终态)`；`schema_version` 有主键且
二次 `apply_schema` 仍 1 行；`role`/`pool` 默认 `'leaf'`/`'solve'`；终态释放 `lock` 后同值可复用。

## 验收中主控追加修复的一条（成员未发现）

**`TaskCard.max_handoffs` 默认 `0` 与 `handoff_cap=2` 冲突，导致 P0 修复把恢复路径彻底堵死。**

- 现象：默认卡 `max_handoffs=0`，`handoff_count=0` 时守卫 `0 < 0` 为假 → **第一次崩溃恢复即被拒**。
- 根因：P0 新增的守卫与既有默认值组合后，从"无上限"变成"零上限"。这是**修复引入的新回归**，比原问题更严重。
- 修法：`max_handoffs` 改为 `2`，与 `config.handoff_cap=2`、`transition(handoff_cap=2)` 三处对齐。
- 追加护栏：`test_invariants.py` 新增 `test_handoff_cap_is_consistent_across_layers`，断言
  `card.max_handoffs == config.handoff_cap` 且 `>= 1`，并写明"否则默认卡第一次崩溃恢复会被拒"。

修复后实测：默认卡首次崩溃 → `QUEUED`；`handoff_count=2` → `IllegalTransitionError`。

## 遗留（不阻塞，已排期）

- `apply_schema` 的"单事务"注释与逐条提交不符 → 阶段 2b
- `applied < SCHEMA_VERSION` 无迁移分支 → 阶段 2b（无存量库）
- `idx_tasks_claim` 中 `state` 位于 `pool` 之后 → 阶段 3 全局领取时评估
- `validate()` 放行 NaN/inf → 阶段 2 与 config 消费方一起修

## 下一步

schema 契约已冻结，`store-claim` 可回到阶段 2a 写 `store.py`。硬门禁见
`orchestration-pr1-acceptance.md` §八（五条），其中第 1 条 `attempts` 递增与第 5 条端到端吸收态
必须真断言，否则阶段 2 不算完成。
