# 代码审查任务书 · PR-1 编排子系统契约层

> 本文件即**派发用的提示词本体**。审查员按此执行，不需要额外口头说明。
> 被审对象：`agent/orchestration/` 四个模块 + 配套测试（PR-1，未提交工作区改动）。

---

## 一、审查范围

### 必审（按分片，只审你分到的那一片）

**分片 A · 契约与调度语义**

| 文件 | 行数 | 关注点 |
|---|---|---|
| `agent/orchestration/contracts.py` | 281 | 枚举、`TaskCard` / `WorkerCapability` / `TaskHandle`、`validate_card` |
| `agent/orchestration/state_machine.py` | 149 | 转移表、守卫、`IllegalTransitionError` |
| `agent/orchestration/config.py` | 262 | 默认值、`from_mapping`、`validate` / `warnings` |
| `tests/orchestration/test_contracts.py` | 355 | 测试是否"能失败" |
| `tests/orchestration/test_state_machine.py` | 278 | 同上 |
| `tests/orchestration/test_config.py` | 170 | 同上 |

**分片 B · 存储与约束**

| 文件 | 行数 | 关注点 |
|---|---|---|
| `agent/orchestration/schema.py` | 402 | DDL、索引、CHECK、`apply_schema`、`configure_connection`、迁移雏形 |
| `tests/orchestration/test_schema.py` | 291 | 约束是否真的生效（不是"建表成功"就算过） |
| `tests/orchestration/test_invariants.py` | 207 | 护栏是否真的在守，skip/xfail 是否掩盖缺口 |
| `tests/agent/test_delegation_config_contract.py` | 228 | 四源一致性断言是否真读文件 |

### 参考（只读，用于判断设计意图，不作为审查对象）

- `docs/design/orchestration-plan-review-2026-10-31.md`（评审意见，含 B1–B3 / H1–H8 / M1–M18 编号）
- `docs/design/orchestration-implementation-plan.md`（分阶段计划）
- `docs/design/orchestration-pr1-acceptance.md`（验收报告，**注意：其中结论本身也可能是错的，不要当权威**）

### 明确不在范围

- `tools/delegate_tool.py` 的既有逻辑（本次只改了 2 行注释）
- 阶段 2–7 尚未实现的部分（`store.py` / `dispatcher.py` 等不存在，不要报"缺失"）

---

## 二、审查重点

按**发现问题的价值**排序，不要平均用力。

### P0 级关注（错一次就是线上事故）

1. **状态机语义正确性**：`_ALLOWED` 是否存在"能进去出不来"或"能绕过守卫"的路径；`transition()` 的守卫顺序是否可能被参数组合绕过；`attempts` / `max_retries` 的边界是否 off-by-one。
2. **存储约束是否真的生效**：CHECK、部分唯一索引、`NOT NULL`、默认值——**必须用实际插入验证**，不能只看 DDL 文本。
3. **默认值的语义一致性**：同一概念在契约层与 DDL 层是否给出同一个默认值（例如 `tier` 的默认、`attempts` 的零点）。历史上这里已经出过一次 off-by-one。
4. **静默失败**：任何 `except Exception` + 降级/回退/skip 的路径。本 PR 已因此被拦下过一次（`schema.py` 的 `_FALLBACK_*`），请确认没有第二处。

### P1 级关注

5. **并发与多进程安全**：这份 schema 是否真的支撑"多进程 CAS 领取 + 租约 + fencing"。具体看：`lease_epoch` 是否可原子递增、`claimed_by` 与 `lease_expires` 是否可能不一致、部分唯一索引在并发插入下是否会产生意外冲突。
6. **SQL 注入 / 路径安全**：所有 SQL 是否有字符串拼接用户输入；`output_path` 的校验是否足以防止 `../` 穿越（`validate_card` 只查绝对路径，够不够）。
7. **索引可用性**：`ORDER BY is_key DESC, priority DESC, bottom_level DESC, created_at` 是否能命中 `idx_tasks_claim`（用 `EXPLAIN QUERY PLAN` 实测，不要推理）。
8. **测试的判别力**：断言是否与实现同源（`from module import X; assert X == X` 这类自证）；是否有"改了实现也不会红"的测试。

### P2 级关注

9. **可维护性**：命名是否表达意图；注释与代码是否一致（本 PR 已出现过"注释写错但测试抓不到"的情况）；是否有死代码/死参数。
10. **分层**：`agent/orchestration/` 是否零 `tools.*` 依赖；是否存在 `contracts → state_machine` 的反向耦合（当前是靠"不 import"维持的，检查有没有偷偷 import）。
11. **配置健壮性**：`from_mapping` 对畸形输入（`None`、`"5"`、`True`、超大值、负数）的处理是否可预期；`warnings()` 与 `validate()` 的职责边界是否清晰。
12. **导入期开销**：`schema.py` 在模块导入时执行了什么（DDL 字符串构造、枚举读取），是否可能拖慢 CLI 启动。

### P3 级关注

13. 风格一致性、文档字符串完整性、类型注解准确性。

---

## 三、输出要求

### 分级

| 级别 | 定义 | 处理要求 |
|---|---|---|
| **P0 阻塞** | 会导致数据错误、状态机死锁、静默失败、安全事故 | 必须修，修完才能合 |
| **P1 重要** | 会在阶段 2–3 放大成事故，或让测试失去判别力 | 应在本 PR 修，或明确排期 |
| **P2 改进** | 可维护性、一致性、边界健壮性 | 可延后，但要记录 |
| **P3 建议** | 风格、命名、注释 | 可选 |

### 每条问题必须包含六要素

```
#### [P1-3] 短标题（一句话说清问题）

- 位置：`agent/orchestration/schema.py:134`
- 证据：贴出实际代码（不要转述）
- 影响：说清"会导致什么"，不要写"可能有问题"
- 建议：给出可直接采用的改法（含代码片段）
- 验证：怎么确认修好了（命令 / 断言 / 测试名）
```

**没有证据的条目一律不写。** 不要用"建议考虑""或许可以"这类措辞——要么指出具体缺陷，要么不提。

### 必须附带的三项

1. **实测证据**：凡涉及 SQL 约束、索引命中、默认值的结论，必须贴出你实际执行的命令与输出（`sqlite3` / `pytest` / `EXPLAIN QUERY PLAN`）。推理得出的结论标注"未实测"。
2. **误报声明**：如果你怀疑某个设计有问题但无法确认，单独列在"待确认"小节，**不要混进 P0–P3**。
3. **一句话总评**：这个模块能不能进 PR，不能的话卡在哪一条。

### 交付格式

- 文件：`notes/orchestration-pr1-code-review-{a|b}.md`（中文 Markdown，≤ 300 行）
- 汇报：SendMessage 给 `team-lead`，正文 ≤ 200 字，只写：P0/P1 条数、最严重的一条、总评。

### 时间与预算

- **本轮会话内完成**，不超过 40 次工具调用。
- 不要跑全量测试（`tests/` 有数千个用例）；只跑 `tests/orchestration` 与 `tests/agent/test_delegation_config_contract.py`。

---

## 四、禁止事项

1. **只读**。除你自己的 `notes/orchestration-pr1-code-review-*.md` 外，不得创建或修改任何文件。发现问题写进报告，**不要顺手修**——修不修由主控决定。
2. **不得跑破坏性命令**（`git checkout` / `git reset` / 删文件）。
3. **不得引用验收报告作为"正确性依据"**。验收报告是审查对象之一，不是标准答案。规格以评审文档 + 方案原文为准；两者冲突时，以"能否支撑多进程编排"为判据。
4. **不得把"测试通过"当作"代码正确"的证据**。本 PR 已经出现过 126 个测试全绿但转移表是错的情况。
5. 不要重复已修复的问题（`_FALLBACK_*` 静默回退已删、`attempts` 默认值已改 0、`tier` 默认值已改 2、`error` 已改名 `block_reason`）——如果你发现这些**没改干净**，那要报。

---

## 五、环境

仓库在 WSL：`/home/xujuan/.fulilian/fulilian-agent`，Windows 侧 `//wsl.localhost/kali-linux/home/xujuan/.fulilian/fulilian-agent`。

所有命令走：
```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```

Python：`./venv/bin/python`（3.11.15）。

⚠️ `Edit` / `Write` 工具对 UNC 路径会报 `ModifyBackup failed`；如果你需要写文件，用 `Write` 写到 `C:\Users\Administrator\AppData\Local\Temp\` 再在 WSL 内 `cp` 过去。
