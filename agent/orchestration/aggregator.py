"""阶段 6 聚合层：把多个子结果归并成一份，带预算与冲突裁决。

纯函数模块：不读数据库、不调度、不看时钟。归并的边界（空输入、预算刚好卡在
边界、同一 key 三个来源互不相同）最需要单元测试，掺进 I/O 就只能集成测试。

两条设计约束（详见 ``orchestration-phase6-decisions.md``）：

1. **截断必须可见。** 超预算时返回 ``truncated=True`` 与准确的 ``dropped``。
   静默丢弃是本项目反复出现的失败模式——归并结果看起来完整、实际少了三条，
   比归并直接失败更难发现。
2. **冲突默认 ``REPORT``。** 两个子代理对同一事实给出不同答案，**分歧本身就是
   最有价值的信息**。静默挑一个会让它消失。要裁决就显式选 ``PRIORITY``。
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

__all__ = [
    "AggregationError",
    "ConflictPolicy",
    "MergeBudget",
    "MergeResult",
    "merge",
]


class AggregationError(Exception):
    """归并无法按声明的方式完成（``FAIL`` 策略命中冲突、参数不合法）。"""


class ConflictPolicy(enum.Enum):
    """多个来源对同一 key 给出不同值时的处置方式。"""

    REPORT = "report"
    """保留**先到**的值，把该 key 记进 ``conflicts``，不丢信息。默认。"""

    PRIORITY = "priority"
    """按 ``priorities`` 高者胜；**平手降级为 REPORT**（保留先到的值并记录）。"""

    FAIL = "fail"
    """一旦出现分歧即抛 :class:`AggregationError`。"""


@dataclass(frozen=True, slots=True)
class MergeBudget:
    """归并预算。超限时按输入顺序截断，不做随机或哈希选择。"""

    max_items: int = 1000
    max_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if self.max_items < 0:
            raise AggregationError(f"max_items 不能为负：{self.max_items}")
        if self.max_bytes < 0:
            raise AggregationError(f"max_bytes 不能为负：{self.max_bytes}")


@dataclass(frozen=True, slots=True)
class MergeResult:
    """归并结果。

    ``conflicts`` 里的 key 表示"多个来源给了不同值"。在 ``REPORT`` 下这些 key
    保留的是先到的值；在 ``PRIORITY`` 下只记录**平手**的（非平手的已按优先级
    裁决，不算未决分歧）。
    """

    merged: dict[str, object] = field(default_factory=dict)
    conflicts: tuple[str, ...] = ()
    truncated: bool = False
    dropped: int = 0


def _cost(key: str, value: object) -> int:
    """预算计数：key + 值表示的 UTF-8 字节数。

    用 ``repr`` 而不是序列化：它确定、不依赖第三方、也不会因为对象不可序列化
    而抛异常。预算是"防止结果膨胀撑爆上下文"，量级准确即可，不需要精确到字节。
    """
    return len(key.encode("utf-8")) + len(repr(value).encode("utf-8"))


def merge(
    parts: Sequence[Mapping[str, object]],
    *,
    policy: ConflictPolicy = ConflictPolicy.REPORT,
    budget: MergeBudget | None = None,
    priorities: Sequence[int] | None = None,
) -> MergeResult:
    """按顺序归并多个映射。

    Args:
        parts: 子结果，**顺序即优先级顺序**（先到者优先）。顺序必须由调用方
            固定，不能来自集合迭代——否则同样输入会产生不同结果。
        policy: 冲突处置，默认 ``REPORT``。
        budget: 预算；``None`` 用默认值。
        priorities: 与 ``parts`` 等长。``PRIORITY`` 策略下按此比较；其它策略
            下只用于长度校验，不参与决策。

    Raises:
        AggregationError: ``priorities`` 长度不符、预算参数非法、或 ``FAIL``
            策略命中冲突。

    实现分两遍，**这个顺序是契约的一部分**：

    1. 第一遍只做**判定**：每个 key 最终该取什么值、哪些 key 仍有分歧。
    2. 第二遍才按预算决定**哪些 key 能进结果**。

    两遍分开的理由是缺陷驱动出来的：早期版本把预算检查塞在同一个循环里，
    于是被预算丢弃的 key 永远不会进入结果，也就永远没机会与后续来源比较——
    **冲突检测被预算短路了**。极端情况（预算紧到什么都进不去）下 ``FAIL``
    策略会静默返回空结果，调用方既没得到分歧也没得到错误。

    因此：``conflicts`` 与 ``dropped`` 都**不受预算影响**，它们描述的是输入，
    不是输出。``merged`` 受预算影响。三者各自回答不同的问题。

    ``PRIORITY`` 下的冲突判定也**不看过程，只看最终最高优先级组**：某个 key
    在低优先级处出现过平手、但后来被严格更高的优先级统一，就不算未决分歧
    （结果无歧义，不需要人看）；反之，若最高优先级组内部就有两个不同值，
    那才是真正需要裁决的。用"逐次比较"做这件事会两个方向都出错——低优先级
    的平手会残留成假冲突，高优先级组内的分歧会被"替换即裁决"吞掉。
    """
    budget = budget or MergeBudget()

    if priorities is not None and len(priorities) != len(parts):
        raise AggregationError(
            f"priorities 长度 ({len(priorities)}) 必须等于 parts 长度 ({len(parts)})"
        )

    # ---- 第一遍：收集全部出现（与预算无关）----
    order: list[str] = []
    occurrences: dict[str, list[tuple[object, int]]] = {}
    for index, part in enumerate(parts):
        part_priority = priorities[index] if priorities is not None else 0
        for key, value in part.items():
            if key not in occurrences:
                occurrences[key] = []
                order.append(key)
            occurrences[key].append((value, part_priority))

    # ---- 第二遍：判定（与预算无关）----
    decided: dict[str, object] = {}
    conflicts: list[str] = []

    for key in order:
        seen_values: list[object] = []
        for value, _priority in occurrences[key]:
            if not any(value == existing for existing in seen_values):
                seen_values.append(value)

        if len(seen_values) <= 1:
            decided[key] = occurrences[key][0][0]
            continue

        # 有分歧
        if policy is ConflictPolicy.FAIL:
            raise AggregationError(
                f"归并冲突（FAIL 策略）：key={key!r} 出现 {len(seen_values)} 个不同取值："
                f"{seen_values!r}"
            )
        if policy is ConflictPolicy.REPORT:
            decided[key] = occurrences[key][0][0]  # 先到的
            conflicts.append(key)
            continue

        # PRIORITY：只看最终最高优先级组
        top = max(priority for _value, priority in occurrences[key])
        top_values: list[object] = []
        for value, priority in occurrences[key]:
            if priority == top and not any(value == existing for existing in top_values):
                top_values.append(value)
        decided[key] = top_values[0]  # 最高优先级组内先到的
        if len(top_values) > 1:
            conflicts.append(key)  # 最高组内仍有分歧 -> 真正未决

    # ---- 第三遍：预算（只影响 merged）----
    merged: dict[str, object] = {}
    items = 0
    bytes_used = 0
    dropped = 0
    truncated = False

    for key in order:
        value = decided[key]
        cost = _cost(key, value)
        if items >= budget.max_items or bytes_used + cost > budget.max_bytes:
            truncated = True
            dropped += 1  # 按 key 计，不按出现次数计
            continue
        merged[key] = value
        items += 1
        bytes_used += cost

    return MergeResult(
        merged=merged,
        conflicts=tuple(conflicts),
        truncated=truncated,
        dropped=dropped,
    )
