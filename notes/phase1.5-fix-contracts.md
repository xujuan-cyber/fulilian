# 阶段 1.5 修复报告 · 契约与状态机（fixer）

范围：`state_machine.py` / `contracts.py` / `test_state_machine.py` / `test_contracts.py`；`schema.py` / `test_schema.py` / `test_invariants.py` 未触碰（store-claim 负责）。

## 1. P0：`BLOCKED -> QUEUED` 的 handoff_cap 守卫

改前（`state_machine.py:100-107`）：三个关键字参数，守卫只有两条。

```python
def transition(current, target, *, lease_expired: bool = False,
               attempts: int = 0, max_retries: int = 1) -> TaskState:
    if current is TaskState.FAILED and target is TaskState.QUEUED:
        if attempts > max_retries:
            raise IllegalTransitionError(...)
    return target
```

改后：

```python
def transition(
    current: TaskState, target: TaskState, *,
    max_retries: int,          # §2.2 必传
    lease_expired: bool = False, attempts: int = 0,
    handoff_count: int = 0, handoff_cap: int = 2,
) -> TaskState:
    # FAILED -> QUEUED 的 attempts 守卫不变（此处省略）
    if current is TaskState.BLOCKED and target is TaskState.QUEUED:
        # P0：崩溃循环兜底。没有这条守卫时 RUNNING -> BLOCKED -> QUEUED 可以
        # 无限转下去，而报错点离现场很远（只有 redispatch 一处自觉检查）。
        if handoff_count >= handoff_cap:
            raise IllegalTransitionError(
                current, target,
                f"转手次数已用尽（handoff_count={handoff_count} >= "
                f"handoff_cap={handoff_cap}）",
            )
    return target
```

docstring 三处同步：守卫表"两条边"→"三条边"并加 `BLOCKED -> QUEUED` 行；"`handoff_count` 不是
本模块的入参，既不读也不写"→"把它当入参读，用于 `BLOCKED -> QUEUED` 的 `handoff_cap` 守卫，同样
不负责递增"；"崩溃循环由 `attempts` / `handoff_count` 上限兜住"→"由 `BLOCKED -> QUEUED` 的
`handoff_cap` 守卫兜住"。`_ALLOWED` 一行未动。

## 2.1 isolation / 2.2 max_retries
```python
    isolation: Isolation = Isolation.INLINE          # 改前
    isolation: Isolation | None = None               # 改后（None = 自动推断 → PROCESS 保守路径）
    max_retries: int = 0                             # 改前
    max_retries: int = 1                             # 改后
```

`transition(..., max_retries: int)` 去掉默认值；`test_state_machine.py` 全部 27 处 `transition(...)`
已补 `max_retries=1`（`_satisfied_kwargs` 也改为必带）。

## 2.3 validate_card 新增 7 条

```python
_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")              # 安全项
if not isinstance(card.task_id, str) or not _TASK_ID_PATTERN.fullmatch(card.task_id): raise CardValidationError("task_id 只允许 [A-Za-z0-9._-] 且长度 1–128")
if not isinstance(card.goal, str) or not card.goal.strip(): raise CardValidationError("goal 不能为空或纯空白")
if not isinstance(card.role, TaskRole): raise CardValidationError("role 必须是 TaskRole")
if card.isolation is not None and not isinstance(card.isolation, Isolation): raise CardValidationError("isolation 必须是 Isolation 或 None")
if not isinstance(card.tier, TaskTier): raise CardValidationError("tier 必须是 TaskTier")
if isinstance(card.priority, bool) or not isinstance(card.priority, int): raise CardValidationError("priority 必须是 int（不接受 bool）")
if os.path.normpath(card.output_path) != card.output_path: raise CardValidationError("output_path 必须是规范路径（不含 '..' 段或重复分隔符）")
if isinstance(card.dod, str) or not isinstance(card.dod, tuple): raise CardValidationError("dod 必须是 tuple[str, ...]，不接受 list/str，不做静默转换")
```

## 3. 新增测试（本半 13 条）

状态机 3 条：`test_blocked_to_queued_rejected_when_handoff_cap_reached`（1/2 放行，2/2 抛错且消息含
`handoff_count=2`、`handoff_cap=2`）、`test_blocked_to_queued_guard_is_default_off_the_crash_loop`
（默认 0/2 放行）、`test_transition_requires_max_retries`（缺参抛 `TypeError`）。

契约 10 条：`test_task_card_isolation_defaults_to_none`（默认 None、显式值不被覆盖、validate 放行）、
`test_task_card_max_retries_defaults_to_one`、`test_validate_card_rejects_non_identifier_task_id`、
`test_validate_card_accepts_identifier_charset`（`t-001`/`A.b_c-9`/128×`a`/`0` 放行）、
`test_validate_card_rejects_path_traversal`（含 `..`/`//`/`./` 的绝对路径）、
`test_validate_card_rejects_blank_goal`、`test_validate_card_rejects_empty_goal`、
`test_validate_card_rejects_list_dod`、`test_validate_card_rejects_non_enum_scheduling_fields`
（`role="leaf"`/`role="root"`/`isolation="inline"`/`tier=2`/`tier="T2"`）、
`test_validate_card_rejects_bool_priority` + `test_validate_card_rejects_non_int_priority`。

`test_task_card_defaults` 中 `isolation is INLINE` 改为 `is None`、`max_retries == 0` 改为 `== 1`（未删用例）。

## 4. 测试输出原文

```
$ ./venv/bin/python -m pytest tests/orchestration/test_state_machine.py tests/orchestration/test_contracts.py -q
........................................................................ [ 66%]
.....................................                                    [100%]
109 passed in 1.92s
$ ./venv/bin/python -m pytest tests/orchestration tests/agent/test_delegation_config_contract.py -q
........................................................................ [ 37%]
.........................sx....s........................................ [ 75%]
................................................                         [100%]
189 passed, 2 skipped, 1 xfailed in 3.14s
```

`grep -rn "from tools\|import tools" agent/orchestration/` → 无输出。

## 5. "能失败"验证（P0 守卫）

把 `if handoff_count >= handoff_cap:` 临时改为 `if False:` 后：

```
>       with pytest.raises(IllegalTransitionError) as excinfo:
E       Failed: DID NOT RAISE IllegalTransitionError
FAILED tests/orchestration/test_state_machine.py::test_blocked_to_queued_rejected_when_handoff_cap_reached
1 failed in 0.37s
```

已还原，还原后该用例 `1 passed`。

## 6. 需主控裁决（未自行改动）

`TaskCard.max_handoffs` 默认 `0`，`transition(handoff_cap=2)`：同一语义两个名字、两个默认，卡片说
"不许转手"、状态机说"最多转 2 次"。本次按决议 §一 保持 `handoff_cap=2` 字面量、未动 `max_handoffs`；
阶段 2 的 store 需明确以谁为准（建议显式传 `handoff_cap=card.max_handoffs`，签名默认仅作兜底）。
