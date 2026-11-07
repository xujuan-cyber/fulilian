# 阶段 6 冻结决议 · 组织与聚合（`organizer.py` + `aggregator.py`）

> 主控裁定，实现者不得自行改动。
> 上游：`orchestration-implementation-plan.md` §阶段 6。产出"`organizer.py`（能力位、命名、编制）、`aggregator.py`（归并、预算、冲突裁决）"；验收"细粒度策略可声明生效；`sum(pools) <= max_running` 校验生效；编制按可并行资源数而非任务数"。

---

## 零、必须先解决的命名冲突

`contracts.py:210` 的 `TaskHandle.capability` **已经是别的东西**：它是 HMAC 字符串，把 `task_id`/`worker_id`/`lease_epoch` 绑在一起做写回校验，是 fencing token。

计划里的"能力位"若也叫 `capability`，两个概念会共用一个词——一个防伪造，一个做匹配。这是最容易埋雷的那类冲突：类型都是 `str`，混用了编译器不会报错。

**裁定：能力位一律叫 `skills`（`frozenset[str]`）。禁止在任何新代码里用 `capability` 表达"能力位"。**

---

## 一、`max_running` 与 `sum(pools)` 的口径

计划验收写"`sum(pools) <= max_running` 校验生效"，而评审 M1 写"`sum(pools) >= max_running` 时以 `max_running` 为准并在启动时告警"。两处不一致，裁定如下：

| 概念 | 语义 |
|---|---|
| `max_running` | **全局硬顶**。任意时刻实际运行数不得超过它 |
| `pools` | 每个池的**配额上限**，不是保证 |

**`sum(pools) > max_running` 是合法配置**，因为池配额是"各自最多多少"，不是"各自至少多少"。A 池空闲时 B 池可以用满全局额度，这正是分池的意义。

所以：

- `sum(pools) > max_running` → **告警，不拒绝启动**（`config.py` 的 `warnings()` 已实现，复用，不要重写）
- 真正的硬校验在**调度时**：实际并发数 <= `max_running`
- 计划验收里的"校验生效"理解为"存在这个检查且会报告"，**不是**"拒绝启动"

理由：拒绝启动会让一份只是配额偏松的配置变成不可用，而真正的风险（超跑）由调度层的硬顶挡住。

---

## 二、模块边界

| 文件 | 职责 | 不做什么 |
|---|---|---|
| `organizer.py` | 算编制（几个 worker）、给 worker 起名、判断某 worker 是否够格接某任务 | **不创建进程、不碰 store** |
| `aggregator.py` | 归并子结果、执行归并预算、裁决冲突 | **不读数据库、不调度** |

两者都是**纯函数模块**：输入配置/数据，输出决策。不 import `store` / `worker` / `launcher`。

理由：这两个模块的决策逻辑最需要单元测试，一旦掺进 I/O 就只能集成测试，而集成测试覆盖不到边界。

---

## 三、公开 API（冻结）

```python
# ---- organizer.py ----
class StaffingError(Exception): ...


@dataclass(frozen=True, slots=True)
class Slot:
    """一个可并行的工作位。``name`` 是稳定标识，不是随机 id。"""
    name: str            # 例如 "solve-00"
    pool: str
    #: ``None`` = 该池**未声明**技能限制（任何任务都能接）；
    #: ``frozenset()`` = 声明了但零技能（什么都接不了）；非空 = 只能接被覆盖的。
    #: 原决议写的是 ``frozenset[str]``，实现时发现"未声明"与"声明为空"必须区分，
    #: 否则未配置技能的环境会变成"所有任务都不可调度"。见验收记录 §四。
    skills: frozenset[str] | None = None


class Organizer:
    def __init__(self, config: OrchestrationConfig) -> None: ...

    def staffing(self, *, active_by_pool: Mapping[str, int]) -> tuple[Slot, ...]:
        """算出**本轮该有多少个工作位**，以及它们的名字与能力。

        编制依据是**可并行资源数**，不是排队任务数——见 O3。
        """

    def eligible(self, slot: Slot, *, pool: str, required: frozenset[str]) -> bool:
        """该工作位能否接这个任务：池匹配 + 技能覆盖。"""


# ---- aggregator.py ----
class ConflictPolicy(enum.Enum):
    REPORT = "report"      # 默认：保留双方 + 标记冲突
    PRIORITY = "priority"  # 按 TaskCard.priority 高者胜
    FAIL = "fail"          # 有冲突即失败


class AggregationError(Exception): ...


@dataclass(frozen=True, slots=True)
class MergeBudget:
    max_items: int = 1000
    max_bytes: int = 1_000_000


@dataclass(frozen=True, slots=True)
class MergeResult:
    merged: dict[str, object]
    conflicts: tuple[str, ...]        # 有分歧的 key
    truncated: bool                   # 是否因预算被截断
    dropped: int                      # 被丢弃的条目数


def merge(
    parts: Sequence[Mapping[str, object]],
    *,
    policy: ConflictPolicy = ConflictPolicy.REPORT,
    budget: MergeBudget = MergeBudget(),
    priorities: Sequence[int] | None = None,
) -> MergeResult: ...
```

---

## 四、七条实现决议

### O1 · 能力位叫 `skills`，不叫 `capability`

见 §零。`Slot.skills` 是 `frozenset[str]`。任务侧需要的能力从 `TaskCard.resources` 派生或另行传入，**不新增 `TaskCard` 字段**（那要改契约与 schema）。

### O2 · 命名必须确定性

`Slot.name = f"{pool}-{index:02d}"`，index 从 0 开始。

**禁止 uuid / 随机后缀 / pid / 时间戳。** 理由：重启后同样的配置必须产生同样的名字，否则日志、事件、指标无法跨重启关联。一个"看起来更安全"的随机名，会让排查从"看 solve-03 干了什么"变成"在上千条记录里找那个 pid"。

### O3 · 编制按可并行资源数，不按任务数

这是计划验收的原话，也是最容易做错的一条。

```python
staffing(pool) = min(pool_quota, max_running - 其它池已占用)
```

**编制函数不得接受"排队任务数"作为输入。** 测试必须能证明这一点：排队 1000 个任务时，`staffing()` 返回值与排队 1 个任务时**完全相同**。

若把任务数传进去，实现者几乎必然会写 `min(tasks, cap)`——那就是按任务数编制，违反验收。

`active_by_pool` 是**当前已占用**（资源侧），不是待办数（任务侧）。这个区分是这条决议的全部。

### O4 · 编制的下界是 0，且不抛异常

某池配额已满或全局已满时，`staffing` 返回**不含该池**的结果，不是抛错。调用方（launcher）拿到 0 个位就不启动，这是正常路径。

抛错会让"暂时没资源"变成"系统故障"。

### O5 · 归并预算：截断必须可见

`MergeBudget` 限制条目数与字节数。超限时：

- 按**输入顺序**保留前 N 条（确定性，不用随机或哈希）
- `truncated=True`、`dropped=<被丢条数>`

**绝不允许静默丢弃。** 归并结果看起来完整、实际少了三条，比归并失败更难发现。

### O6 · 冲突裁决默认 `REPORT`，不是"挑一个"

两个子结果对同一 key 给出不同值时：

| 策略 | 行为 |
|---|---|
| `REPORT`（默认） | 保留先到的值，`conflicts` 里记下该 key，**不丢信息** |
| `PRIORITY` | 按 `priorities` 高者胜；平手降级为 REPORT 并记入 conflicts |
| `FAIL` | 抛 `AggregationError` |

**默认选 `REPORT` 的理由**：静默挑一个（无论"先到"还是"后者"）会让分歧消失，而分歧本身往往是最有价值的信息——两个子代理对同一事实给出不同答案，说明这里有需要人看的东西。

`PRIORITY` 平手时必须降级为 REPORT，**不许用"后到覆盖"之类的隐式规则兜底**。

### O7 · 不 import `store` / `worker` / `launcher` / `dispatcher`

见 §二。这两个模块是纯函数，只依赖 `config.py` 和标准库。

---

## 五、验收

| # | 指标 | 判定 |
|---|---|---|
| ① | 细粒度策略可声明生效 | `staffing` 按 `pools` 配额分别给出工作位，不同池独立 |
| ② | `sum(pools) > max_running` 校验生效 | 复用 `config.warnings()`，返回非空告警；**不抛异常** |
| ③ | 编制按资源数非任务数 | 排队 1 个 vs 1000 个任务，`staffing` 结果完全相同 |
| ④ | 命名确定性 | 同配置两次调用产生完全相同的 name 序列 |
| ⑤ | 技能匹配 | `eligible` 在技能不覆盖时返回 False，覆盖时 True |
| ⑥ | 归并预算截断可见 | 超 `max_items` 时 `truncated=True` 且 `dropped` 准确 |
| ⑦ | 冲突默认 REPORT | 冲突 key 进入 `conflicts`，值保留先到的 |
| ⑧ | PRIORITY 平手降级 | 同优先级冲突时降级为 REPORT，不静默覆盖 |

### 必须新增的测试（函数名固定）

```
test_staffing_uses_resources_not_queue_depth
test_staffing_is_deterministic
test_staffing_respects_pool_quota
test_pools_sum_over_max_running_warns_not_raises
test_eligible_requires_skill_coverage
test_merge_truncates_visibly
test_merge_conflict_defaults_to_report
test_merge_priority_tie_degrades_to_report
```

---

## 六、禁止事项

1. 不得改 `store.py` / `schema.py` / `contracts.py` / `state_machine.py` / `control.py` / `dispatcher.py` / `supervisor.py` / `redispatch.py` / `worker.py` / `launcher.py` / `reaper.py`。
2. 不得新增 `TaskCard` 字段。
3. 不得用 `capability` 表达能力位。
4. 不得让 `staffing` 接受任务数参数。
5. 不得静默丢弃归并条目。
6. 不得跑全量 `tests/`。

## 七、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```
Python `./venv/bin/python`。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

**落盘后必须读回关键行确认文件真的变了**——不要只看脚本打印 OK。

**笔记里的定位用锚点字符串，不要写行号**（行号每改一次文案就漂一次，本项目已因此出过三次"笔记与产物不符"）。
