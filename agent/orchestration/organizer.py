"""阶段 6 组织层：算编制、给工作位命名、判断谁够格接任务。

这个模块是**纯函数**：不碰数据库、不创建进程、不读时钟。输入配置与当前占用，
输出一份工作位清单。理由很简单——编制逻辑的边界条件（配额满、全局满、
技能不覆盖）最需要单元测试，一旦掺进 I/O 就只能集成测试，而集成测试覆盖不到
这些边界。

三条设计约束（详见 ``orchestration-phase6-decisions.md``）：

1. **编制按可并行资源数，不按排队任务数。** ``staffing()`` 刻意不接受任何
   "任务数/队列深度"参数。一旦签名里出现它，实现几乎必然写成
   ``min(tasks, cap)``，那就变成按任务数编制了。
2. **命名必须确定性。** ``{pool}-{index:02d}``，不用 uuid / 随机后缀 / pid /
   时间戳。重启后同样的输入必须产生同样的名字，否则日志与指标无法跨重启关联。
3. **能力位叫 ``skills``，不叫 ``capability``。** ``TaskHandle.capability`` 已经
   是 HMAC 租约令牌，两个概念共用一个词且类型都是 ``str``，混用不会报错。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent.orchestration.config import OrchestrationConfig

__all__ = ["Organizer", "Slot", "StaffingError"]


class StaffingError(Exception):
    """编制参数非法。注意：**资源不足不是错误**，返回空结果即可。"""


@dataclass(frozen=True, slots=True)
class Slot:
    """一个可并行的工作位。

    ``name`` 是**位置名**（像座位号），不是实例 id。某个位空出来之后，
    新 worker 会复用同一个名字——这是有意的：日志里 ``solve-03`` 始终指
    "solve 池的第四个位"，而"哪个实例坐过这个位"由 worker_id 记录。

    ``skills`` 的三态语义（这是最容易写错的地方）：

    | 值 | 含义 |
    |---|---|
    | ``None`` | 该池**未声明**技能限制 —— 任何任务都能接 |
    | ``frozenset()` （空集） | 声明了，但**一个技能都没有** —— 什么都接不了 |
    | 非空集合 | 只能接 ``required`` 被它覆盖的任务 |

    ``None`` 与空集必须区分：前者是"没限制"，后者是"限制到零"。把它们都当成
    空集，未配置技能的环境会变成"所有任务都不可调度"；都当成 ``None``，
    误配成空集的池会静默接走全部任务。
    """

    name: str
    pool: str
    skills: frozenset[str] | None = None


class Organizer:
    """按配额与当前占用算编制。无状态，可复用，可并发调用。"""

    def __init__(
        self,
        config: OrchestrationConfig,
        *,
        skills_by_pool: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        """
        Args:
            config: 编排配置，``pools`` 是各池配额，``max_running`` 是全局硬顶。
            skills_by_pool: 每个池声明的技能集合。**不传的池视为"未声明限制"**
                （``Slot.skills is None``），而不是"零技能"。
        """
        if config.max_running < 1:
            raise StaffingError(f"max_running 必须 >= 1，实际 {config.max_running}")
        for pool, quota in config.pools:
            if quota < 0:
                raise StaffingError(f"池 {pool!r} 的配额不能为负，实际 {quota}")
        self._config = config
        self._skills = dict(skills_by_pool or {})

    def staffing(self, *, active_by_pool: Mapping[str, int] | None = None) -> tuple[Slot, ...]:
        """算出本轮该开多少个工作位，以及它们的名字与技能。

        Args:
            active_by_pool: **当前已占用**的工作位数（资源侧），不是排队任务数
                （任务侧）。这两者不可互换——用排队数算编制就是"任务多就多开人"，
                而实际能开多少只取决于资源上限。

        Returns:
            需要**新开**的工作位。已占用的位不在其中：``active_by_pool["solve"]=2``
            且配额为 3 时，只返回 1 个位，名字是 ``solve-02``。

        资源不足（全局满或某池满）时返回空元组，**不抛异常**。抛异常会让
        "暂时没资源"看起来像"系统故障"。
        """
        active = dict(active_by_pool or {})
        if any(v < 0 for v in active.values()):
            raise StaffingError(f"active_by_pool 不能为负：{active}")

        # 全局硬顶。已占用要按全局算——不管它属于哪个池，都在消耗同一个上限。
        remaining = self._config.max_running - sum(active.values())
        if remaining <= 0:
            return ()

        slots: list[Slot] = []
        for pool, quota in self._config.pools:
            if remaining <= 0:
                break
            taken = active.get(pool, 0)
            free_in_pool = quota - taken
            if free_in_pool <= 0:
                continue
            want = min(free_in_pool, remaining)
            skills = self._skills.get(pool)
            for offset in range(want):
                # 位置名从"该池已有几个"续上：solve 已有 2 个位，新位就是 solve-02。
                slots.append(
                    Slot(
                        name=f"{pool}-{taken + offset:02d}",
                        pool=pool,
                        skills=skills,
                    )
                )
            remaining -= want
        return tuple(slots)

    def eligible(
        self,
        slot: Slot,
        *,
        pool: str,
        required: frozenset[str] = frozenset(),
    ) -> bool:
        """该工作位能否接这个任务：池必须匹配，且技能必须覆盖要求。

        ``slot.skills is None`` 表示该池未声明限制，此时**任何任务都能接**，
        包括 ``required`` 非空的情况——"没声明"不等于"声明了零个技能"。
        """
        if slot.pool != pool:
            return False
        if slot.skills is None:
            return True
        return required <= slot.skills
