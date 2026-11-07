# 代码审查 · PR-1 编排子系统 · 分片 A（契约与调度语义）

对象：`agent/orchestration/{contracts,state_machine,config}.py` + 三个配套测试。审查员 reviewer-core，未参与编写。

## 0. 基线

```
$ ./venv/bin/python -m pytest tests/orchestration -q
138 passed, 2 skipped, 1 xfailed in 1.42s
```
**全绿不构成任何结论的依据**——下列 6 条缺陷在 138 绿时全部存在。

变异测试（改坏实现看是否变红）：

| 变异 | 目标测试 | 结果 |
|---|---|---|
| M1 `_ALLOWED[QUEUED]` 偷加 `→RUNNING` | `test_allowed_table_matches_spec_literal` | **RED** `QUEUED 的出边与规格不符` |
| M2 `transition` 删掉重试守卫 | `test_max_retries_semantics` / `test_tc12_*` | **RED** `DID NOT RAISE` |
| M2c 守卫边界 `<=`→`<` | `test_max_retries_semantics` | **RED** `IllegalTransitionError` |
| M3 `validate_card` 变 no-op | `..._rejects_relative_output_path` / `..._empty_dod` | **RED** `DID NOT RAISE` |
| M4 `_COERCE` bool 守卫换裸 `int` | `test_from_mapping_rejects_bool_for_int` | **RED** `DID NOT RAISE` |
| M5 `TaskCard.__hash__` 改常量 `0` | `test_task_card_is_hashable_with_full_field_set` | **GREEN（无判别力）** |

状态机与 config 的核心测试判别力合格；`validate_card` 的测试忠实覆盖了**已实现的**规则，但规则本身有 3 处缺口（P1-3/4/5）。

## P0

#### [P0-1] 崩溃恢复主路径 `RUNNING→BLOCKED→QUEUED` 不受任何上限约束，文档声称的兜底不存在

- 位置：`state_machine.py:49-50`（声明）、`state_machine.py:90-92`（`BLOCKED` 出边）、`state_machine.py:144-156`（仅两条守卫）
- 证据：文档第 49-50 行写"崩溃循环由 ``attempts`` / ``handoff_count`` 上限兜住"，但 `BLOCKED: {QUEUED, CANCELLED, FAILED}` 与 `CLAIMED: {RUNNING, QUEUED, FAILED}` 均无守卫，`attempts` 只在 `FAILED→QUEUED` 被读。实测：

  ```
  $ ./venv/bin/python   # 循环 RUNNING→BLOCKED→QUEUED→CLAIMED→RUNNING
  == crash-recovery loop: attempts=99, max_retries=0 ==
    200 transitions passed, cycles=50, final=RUNNING, attempts still 99, max_retries=0
    RUNNING->QUEUED lease_expired=True attempts=99 max_retries=0 -> QUEUED
  ```
  50 个完整崩溃周期、`attempts=99`、`max_retries=0`，一次都没被拒。
- 影响：阶段 4 照本文档实现 `patrol()` 时会认为"已有兜底"而不另设上限。一个启动即 OOM 的子任务会以 60s 租约的节奏无限重派，token 与产物无限增长且无任何报错。这就是"守卫可被绕过"的直接实例：想绕过重试上限，让失败走 `BLOCKED` 而不是 `FAILED` 即可。
- 建议：二选一，但必须本 PR 定死。
  1. 让回收边也读计数：`if current in (BLOCKED, RUNNING) and target is QUEUED and redispatch_count > max_redispatches: raise IllegalTransitionError(...)`；
  2. 若硬顶放在 `store.claim()`，则**改掉 49-50 行**为"attempts 上限由 store.claim 执行，本模块不检查"，并删掉 `transition()` 的 `attempts` 入参，避免双方互以为对方在守。
- 验证：新增 `test_redispatch_loop_is_bounded`（跑 `max_retries + 2` 圈，末圈断言抛错）。当前必红。

## P1

#### [P1-1] `transition()` 的 `max_retries` 默认值朝"放行"方向偏，且与 `TaskCard.max_retries=0`、`retry_cap=1` 三处不一致

- 位置：`state_machine.py:106` / `contracts.py:171` / `config.py:150`
- 证据：`max_retries: int = 1`（transition）vs `max_retries: int = 0`（card）vs `retry_cap: int = 1`（config）。漏传实测：

  ```
  default-args FAILED->QUEUED: QUEUED
  ```
  一张 `max_retries=0` 的卡，调用点漏传参数即被静默允许再跑一次。
- 影响：`lease_expired` 默认 `False` 是安全方向，`max_retries` 却相反。阶段 2/3 的调用点很多（store 写回、dispatcher、TUI 手动重试），漏传是大概率事件，症状是"多跑一次、多花一份预算"，日志里看不出来。三个默认值并存也说明"默认重试几次"尚无唯一答案。
- 建议：守卫参数改必填关键字，让漏传变成 `TypeError`：

  ```python
  attempts: int | None = None, max_retries: int | None = None
  if current is TaskState.FAILED and target is TaskState.QUEUED:
      if attempts is None or max_retries is None:
          raise TypeError("FAILED->QUEUED 必须显式传入 attempts 与 max_retries")
  ```
  并把 `TaskCard.max_retries` 的默认值改为由 `config.retry_cap` 填充，而不是硬编码 0。
- 验证：`test_transition_requires_guard_args`（`pytest.raises(TypeError)`）。当前必红。

#### [P1-2] `isolation` 默认值契约层与 DDL 层不一致（`inline` vs `process`）

- 位置：`contracts.py:161` vs `schema.py:124`
- 证据：

  ```
  DDL 默认值 (isolation,tier,priority,is_key,attempts,state) = ('process', 2, 0, 0, 0, 'QUEUED')
  TaskCard 默认值 isolation = inline | Isolation.INLINE = inline | Isolation.PROCESS = process
  ```
  `tier/priority/is_key/attempts/state` 五项一致，**只有 `isolation` 反了**。能锁死这条的 `test_invariants.py:136 test_derived_columns_match_card_json` 是 `@pytest.mark.skip`。
- 影响：默认值分叉本身不致命（store 显式写列），但它是"同一概念两个真相源"的残留。触发路径真实：手写 INSERT、迁移脚本、或阶段 2 的 `insert()` 若依赖 `DEFAULT`，声明 `INLINE` 的卡会以 `PROCESS` 落库被拉子进程；反过来把 DDL 改成 `inline` 又会让本该隔离的任务跑在父进程。两个方向都不报错。
- 建议：DDL 不要抄字面量，从契约取值 `DEFAULT '{Isolation.INLINE.value}'`；更稳的是**删掉该列 DEFAULT**，让"忘了写"变成 `NOT NULL constraint failed`。
- 验证：新增 `test_ddl_defaults_match_contract_defaults`，逐项比对 `(tier,is_key,priority,isolation,attempts,state)`。当前在 `isolation` 上必红。

#### [P1-3] 路径穿越：`output_path` 只查 `isabs`，`task_id` 完全无字符校验

- 位置：`contracts.py:253-256`、`contracts.py:250-251`
- 证据：`if not os.path.isabs(card.output_path): raise ...`。实测全部 `ACCEPTED`：

  ```
  output_path with .. traversal -> ACCEPTED  (/tmp/../../../etc/passwd)
  output_path with NUL          -> ACCEPTED  ("/tmp/a\x00b.json")
  output_path with newline      -> ACCEPTED
  task_id with slash+dotdot     -> ACCEPTED  ("../../etc/cron.d/x")
  task_id with spaces/semicolon -> ACCEPTED  ("t 1; DROP TABLE tasks--")
  ```
- 影响：`/tmp/../../../etc/passwd` 是绝对路径，`isabs` 恒真，检查给的是假安全感。`task_id` 更危险——它是产物目录名（测试里就用 `/tmp/orchestration/t-001/...`），`task_id="../../etc/cron.d/x"` 会让 supervisor 的 `mkdir -p` + 写入落到任意目录。NUL 路径要到 worker 里 `open()` 才炸，属"晚失败"。
- 建议：

  ```python
  _TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
  if not _TASK_ID_RE.match(card.task_id): raise CardValidationError(...)
  if "\x00" in card.output_path or "\n" in card.output_path: raise CardValidationError(...)
  normalized = os.path.normpath(card.output_path)
  if normalized != card.output_path or ".." in normalized.split(os.sep):
      raise CardValidationError(f"output_path 必须已归一化且不含 ..：{card.output_path!r}")
  ```
- 验证：上表 5 行写成 `test_validate_card_rejects_path_traversal`。当前 5 条全绿（即全放行）。

#### [P1-4] `validate_card` 完全不校验 `goal` / `role` / `isolation` / `priority` / `tier` / `pool`

- 位置：`contracts.py:235-288`（全函数无一处涉及）
- 证据：实测 `ACCEPTED`：`goal=""`、`goal=None`、`role="LEAF"`（合法值小写 `"leaf"`）、`isolation="bogus"`、`priority="9"`、`tier=9`、`pool=""`。对照 `max_retries=True` 被拒——说明作者对 bool 陷阱有意识，但只覆盖了 6 个数值字段。
- 影响：`goal=None` 会一路带到 prompt 构造，在 worker 里炸 `TypeError`，此时任务已 `CLAIMED`，还得走一次 `CLAIMED→FAILED`。`priority="9"` 落库被 SQLite 亲和性转成 9 不报错，但 `ORDER BY priority DESC` 与 Python 侧排序结果不同——正是 H3 要避免的静默错序。`isolation="bogus"` 让阶段 5 分支落到 `else`。
- 建议：用枚举反查而非字面量白名单（`TaskRole.LEAF == "leaf"` 为真，`==` 挡不住，必须 `isinstance`）：

  ```python
  if not isinstance(card.goal, str) or not card.goal.strip(): raise CardValidationError("goal 不能为空")
  for name, enum_cls in (("role", TaskRole), ("isolation", Isolation)):
      if not isinstance(getattr(card, name), enum_cls): raise CardValidationError(...)
  if not isinstance(card.tier, TaskTier): raise CardValidationError(...)
  if isinstance(card.priority, bool) or not isinstance(card.priority, int): raise CardValidationError(...)
  if not isinstance(card.pool, str) or not card.pool: raise CardValidationError(...)
  ```
- 验证：`test_validate_card_rejects_bad_goal/role/isolation/priority/tier`。当前 7 条全绿（即全放行）。

#### [P1-5] 放行 list 型 `dod`，得到一张不可 hash 的 `TaskCard`，违背模块自己声明的契约

- 位置：`contracts.py:258-264`（只排除 `str`，未要求 `tuple`）、`contracts.py:139-141`（"所有集合类字段用 tuple，保证 frozen dataclass 可 hash"）
- 证据：`dod as list -> ACCEPTED [hash-FAIL(unhashable type: 'list')]`；同批 17 个用例都是 `[hash-ok]`，只有这一条崩。
- 影响：`TaskCard` 被设计为可 hash（`set` 成员 / `dict` key / `card_hash` 去重，H8 要求 `sha256(canonical_json(card))`）。唯一入口闸门放行了一个在 `hash(card)` 处抛 `TypeError` 的对象，错误位置从"入队时"漂到"阶段 2 的 dedupe 里"，traceback 指向 stdlib。类型注解 `tuple[str, ...]` 不是运行时保证。
- 建议：把"必须可 hash"变成显式断言，防止将来新增字段再漏：

  ```python
  for f in ("dod", "allowed_toolsets", "resources", "depends_on"):
      if not isinstance(getattr(card, f), tuple): raise CardValidationError(f"{f} 必须是 tuple")
  try: hash(card)
  except TypeError as exc: raise CardValidationError(f"TaskCard 必须可 hash：{exc}") from exc
  ```
- 验证：`test_validate_card_rejects_list_dod` + `test_validated_card_is_always_hashable`。前者当前必红。

## P2

#### [P2-1] `test_is_terminal_matches_contracts` 与实现同源，零判别力

- 位置：`test_state_machine.py:263-266`；证据：`assert is_terminal(state) is (state in TERMINAL_STATES)` 复刻了 `state_machine.py:168` 的函数体。
- 影响：`is_terminal` 的语义没有任何独立断言。若改成 `return not _ALLOWED.get(state)`（看起来更"合理"），测试仍绿，但 `FAILED` 的判定会反转——而 `FAILED` 恰是唯一"终态但有出边"的状态，正是该守住的点。
- 建议：断言行为：`is_terminal(FAILED) is True`、`is_terminal(BLOCKED) is False`、`is_terminal(QUEUED) is False`。
- 验证：把实现改成 `not _ALLOWED.get(state)`，现有测试绿、新测试红。

#### [P2-2] `test_task_card_is_hashable_with_full_field_set` 的断言恒真（实测 M5）

- 位置：`test_contracts.py:190-191`；证据：`assert hash(card) == hash(card)` + `len({card, card}) == 1`；变异 M5 后 **GREEN**。
- 影响：只证明"hash 不抛异常"，不证明"值敏感"。不同卡 hash 不同这一点完全没覆盖。
- 建议：`assert hash(_card()) != hash(_card(priority=1))` 与 `len({_card(), _card(priority=1)}) == 2`。
- 验证：重跑 M5 应变红。

#### [P2-3] `validate()` 放行 `NaN` / `inf`，租约语义被彻底破坏

- 位置：`config.py:206-218`；证据：

  ```
  nan lease_seconds -> validate OK    inf lease_seconds -> validate OK    nan heartbeat -> validate OK
  nan <= 0 -> False    inf <= 0 -> False    nan >= 60 -> False
  ```
- 影响：`NaN` 让所有比较恒假，`lease_seconds <= 0` 与 `heartbeat >= lease` 两道检查同时失效；`inf` 让 `lease_expires = now + inf`，worker 崩溃后任务永久停在 `RUNNING`、`patrol()` 永远扫不到、`lease_expired` 永远 `False`——死锁形态，且该任务一直占着 `output_path` 的部分唯一索引。
- 建议：在 `_as_float` 就地拒绝非有限值（`if not math.isfinite(value): raise ConfigError(...)`），并在 `validate()` 里补一条 `math.isfinite`（直接构造可绕过 `from_mapping`）。
- 验证：`test_from_mapping_rejects_non_finite`（nan/inf/-inf）+ `test_validate_rejects_non_finite_direct_ctor`。当前全绿（即全放行）。

#### [P2-4] `from_mapping` 可返回非法配置，范围校验被推迟到调用方主动 `validate()`

- 位置：`config.py:164-184`；证据：`{"batch_limit": -1}` / `{"batch_limit": 10**9}` / `pools` 负配额均 `from_mapping OK`，只有调 `validate()` 才报错。
- 影响：docstring 只承诺"wrong type raises"，未说"返回值仍需 `validate()`"。任何 `from_mapping(yaml.safe_load(...))` 的调用点都可能拿到非法对象；配合 P2-3，`nan` 即使调了 `validate()` 也拦不住。多进程启动路径上很容易只做第一段校验。
- 建议：加 `validate: bool = True` 参数，默认校验；docstring 写明"返回值默认已通过 `validate()`"。
- 验证：`test_from_mapping_validates_by_default`（`batch_limit=-1` 应抛）。当前必红。

#### [P2-5] `pools` 重名静默合并，`pool_map()` 丢配额且不报错

- 位置：`config.py:81-101`（不查重）、`config.py:260-262`（`dict()` 后者覆盖前者）。证据：`[("solve",3),("solve",9)] -> validate OK`，`pool_map()` 得 `{"solve": 9}`，3 无声消失；而 `warnings()` 的 `sum(cap)` 仍是 12，与生效的 9 不一致。
- 影响：YAML 里 `pools` 用 list 时重复键很常见（合并两个片段），结果是告警数字与真实配额对不上，排查时会怀疑调度器。
- 建议：`_as_pools` 里 `if len({n for n, _ in out}) != len(out): raise ConfigError(...)`。验证：`test_from_mapping_rejects_duplicate_pool_names`。

#### [P2-6] `db_path` 可指向 `state.db`，与模块自己的"never"承诺无强制

- 位置：`config.py:158-160`（注释）、`config.py:187-235`（`validate` 无相关检查）。证据：`{"db_path": "/home/u/.fulilian/state.db"} -> validate OK`；测试只覆盖"默认路径不含 state.db"（`test_config.py:58-65`）。
- 影响：模块头用一整段解释为什么绝不能共用 `state.db`（journal mode 归 `SessionDB`，claim/heartbeat 写会与 transcript/FTS 争锁），但这条约束只活在注释里。写进用户配置后症状是随机 `database is locked`，极难定位。
- 建议：`validate()` 里硬拒 `os.path.basename(self.db_path) == "state.db"`；若担心合法场景，至少 `warnings()` 显式告警，不能无声通过。验证：`test_validate_rejects_state_db_path`。

#### [P2-7] `HandoffPolicy` 两处真相源（`Literal` + `_HANDOFF_POLICIES`），且未进 `__all__`

- 位置：`contracts.py:130-132`、`contracts.py:30-44`。证据：`HandoffPolicy = Literal["tool","handoff"]` 与 `_HANDOFF_POLICIES = frozenset({"tool","handoff"})` 并存；`__all__` 与 `test_contracts_all_is_complete` 的名单都没有它，漏导出不会被发现。
- 影响：新增第三档时类型检查器接受、运行时 `validate_card` 拒绝（或反之）。`Literal` 运行时不可枚举，两份必然要手工同步——与"消灭多真相源"的主题冲突，是阶段 4 handoff 落地时第一个会踩的点。
- 建议：改成 `StrEnum`（与 `Isolation`/`TaskRole` 一致）；或至少加 `assert set(get_args(HandoffPolicy)) == _HANDOFF_POLICIES` 并补进 `__all__`。验证：删掉 `_HANDOFF_POLICIES` 里的 `"handoff"`，新测试变红、当前无测试变红。

#### [P2-8] `attempts` / `max_retries` 无类型与范围校验，`attempts=-1` 绕过守卫、`0.5` 被接受

- 位置：`state_machine.py:100-107`、`state_machine.py:149-156`。证据：`{'attempts': -1, 'max_retries': 0} -> QUEUED`；`{'attempts': 0.5, 'max_retries': 1} -> QUEUED`。（`max_retries=-5` 被拒，但理由是 `0 > -5`，属巧合而非校验。）
- 影响：`attempts` 由调用方维护，`0.5` 说明有人把次数当成了浮点计时器或从 JSON 读到 float；`-1` 直接让守卫失效。与 P1-1 同类，修法可合并。
- 建议：`if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0: raise ValueError(...)`，`max_retries` 同。验证：`test_transition_rejects_negative_attempts` / `..._float_attempts`。

## P3

#### [P3-1] `TaskHandle.issued_at` 默认 `0.0` 是 1970 哨兵
- 位置：`contracts.py:209`。证据：`issued_at: float = 0.0`，且 `test_task_handle_defaults_and_fencing_fields` 还断言 `== 0.0`，把哨兵固化成了契约。
- 影响：`issued_at=0` 与"未设置"不可区分；阶段 2 若用它算租约剩余时间，会得到"已过期 55 年"。
- 建议：改 `float | None = None`，或去掉默认值强制调用方给（`TaskHandle` 只由 `store.claim()` 构造，没有"默认句柄"的合法场景）。

#### [P3-2] `assert_not_terminal` 的错误形状与"同态转移"混淆
- 位置：`state_machine.py:171-178`。证据：`raise IllegalTransitionError(state, state, ...)`，`current is target`，与 `state_machine.py:135-136` 的同态转移错误在日志里无法区分。
- 影响：`FAILED` 是终态但仍有合法出边，用本函数做"能否推进"闸门的调用点会错误拦住 `FAILED→QUEUED` 的重试，而日志指向"同态转移"，方向也错。
- 建议：改用独立的 `TerminalStateError`，或在 reason 里写明"判断能否重试请查 `_ALLOWED`"。

#### [P3-3] `config.py` 注释把自身默认值说成"方案的遗留"
- 位置：`config.py:238-244`。证据：docstring 写"the plan ships `max_running=15` while its pools sum to `17`"，而 `15+1+1` 正是**本模块**的默认值。
- 影响：低，但会让人误判这是历史包袱、下次调参"顺手修正"掉 M1 的告警。
- 建议：改为"本模块默认值沿用方案数字，因此自身即存在 17 > 15 的矛盾（M1）"。

## 待确认（不计入 P0–P3）

1. **`BLOCKED` 无 `attempts` 守卫是否有意？** 我按"文档声称有兜底"判为 P0-1。另一种合理解释：进程被 OOM kill 不该消耗用户的重试预算，回收应由独立的 `redispatch_count` 硬顶。若是设计意图，P0-1 降为"文档与实现不符"，但仍须在契约层写明谁守这个上限。**未实测**：`store.py` 尚不存在，无法确认 `claim()` 里是否有 `attempts >= retry_cap + 1` 的拒绝。
2. **`test_exhaustive_transition_table` 以 `_ALLOWED` 为判据**（实测 M1b：偷加边后仍 GREEN）。作者在 docstring 里明确承认并靠字面量测试兜住，我认可这个取舍，只记录：若删掉那条测试，穷举会退化为自洽性检查。
3. **`CLAIMED` 不能直达 `CANCELLED`**（需 `CLAIMED→QUEUED→CANCELLED` 两跳）。来自方案 §4.2 原表且可达，不算缺陷；但若 H5 要求取消在宽限期内收敛，上界要按 2×租约算。**未实测**（无调用方）。

## 一句话总评

状态机的表结构与重试边界测试扎实（M1/M2/M2c 都能变红），但**崩溃恢复主路径不受任何上限约束而文档声称有兜底（P0-1）**、`max_retries` 默认值朝放行方向偏（P1-1）、`validate_card` 有路径与字段缺口（P1-3/4/5）——**不建议直接合入**，卡在 P0-1：必须先明确"回收次数由谁守"，否则阶段 4 的 `patrol()` 会照着一句不成立的注释实现出无限重派循环。
