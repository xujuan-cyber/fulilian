"""阶段 6 聚合层测试。

每条用例钉一条决议：O5 截断可见、O6 冲突默认 REPORT 且 PRIORITY 平手降级。
"""

from __future__ import annotations

import pytest

from agent.orchestration.aggregator import (
    AggregationError,
    ConflictPolicy,
    MergeBudget,
    merge,
)


def test_merge_truncates_visibly() -> None:
    """O5：超预算必须置 ``truncated`` 并给出**准确**的 ``dropped``。

    静默丢弃比归并失败更难发现——结果看起来完整，实际少了条目。所以这里
    不只断言 truncated，还断言"进结果的数量 + 被丢弃的数量 == 输入条目总数"。
    """
    parts = [{"a": 1, "b": 2}, {"c": 3, "d": 4}]

    result = merge(parts, budget=MergeBudget(max_items=2))

    assert result.truncated is True
    assert result.dropped == 2, f"应丢弃 2 条，实际 {result.dropped}"
    assert result.merged == {"a": 1, "b": 2}, "截断必须按输入顺序保留前 N 条"
    assert len(result.merged) + result.dropped == 4, "条目数必须守恒，不许悄悄蒸发"


def test_merge_byte_budget_also_truncates() -> None:
    """预算的另一维：字节数超限同样要可见。"""
    parts = [{"k": "x" * 100}]
    result = merge(parts, budget=MergeBudget(max_bytes=10))

    assert result.truncated is True
    assert result.dropped == 1
    assert result.merged == {}


def test_merge_conflict_defaults_to_report() -> None:
    """O6：默认保留先到的值并记录 key，不静默挑一个。"""
    parts = [{"answer": "A"}, {"answer": "B"}]

    result = merge(parts)

    assert result.merged["answer"] == "A", "REPORT 保留先到的值"
    assert result.conflicts == ("answer",), "分歧 key 必须被记录"
    assert not result.truncated


def test_merge_identical_values_are_not_conflicts() -> None:
    """值相同不算分歧——否则"多源印证"会被误报成冲突。"""
    result = merge([{"k": 1}, {"k": 1}, {"k": 1}])
    assert result.conflicts == ()
    assert result.merged == {"k": 1}


def test_merge_priority_wins_when_strictly_higher() -> None:
    """PRIORITY：高优先级覆盖低优先级，且不算未决分歧。"""
    parts = [{"v": "low"}, {"v": "high"}]

    result = merge(parts, policy=ConflictPolicy.PRIORITY, priorities=[1, 5])

    assert result.merged["v"] == "high"
    assert result.conflicts == (), "非平手已裁决，不记入未决分歧"


def test_merge_priority_tie_degrades_to_report() -> None:
    """O6：平手**必须**降级为 REPORT（保留先到的值并记录）。

    不许用"后到覆盖"之类的隐式规则兜底——那会让同优先级的两个来源里，
    谁在列表后面谁说了算，而调用方完全看不出这个规则。
    """
    parts = [{"v": "first"}, {"v": "second"}]

    result = merge(parts, policy=ConflictPolicy.PRIORITY, priorities=[3, 3])

    assert result.merged["v"] == "first", "平手时必须保留先到的值，不许后到覆盖"
    assert result.conflicts == ("v",), "平手必须记入 conflicts"


def test_merge_fail_policy_raises_on_conflict() -> None:
    """FAIL：有分歧即抛，不留半份结果。"""
    with pytest.raises(AggregationError):
        merge([{"v": 1}, {"v": 2}], policy=ConflictPolicy.FAIL)

    # 无分歧时不抛
    result = merge([{"v": 1}, {"v": 1}], policy=ConflictPolicy.FAIL)
    assert result.merged == {"v": 1}


def test_merge_rejects_priorities_length_mismatch() -> None:
    with pytest.raises(AggregationError):
        merge([{"a": 1}, {"b": 2}], priorities=[1])


def test_merge_empty_input() -> None:
    result = merge([])
    assert result.merged == {}
    assert result.conflicts == ()
    assert result.truncated is False
    assert result.dropped == 0


def test_merge_records_every_conflicting_key() -> None:
    """``conflicts`` 必须记全，不是只记第一个。"""
    parts = [{"a": 1, "b": 2, "c": 3}, {"a": 9, "b": 8, "c": 7}]

    result = merge(parts)

    assert result.conflicts == ("a", "b", "c"), f"实际 {result.conflicts}"


# ------------------------------------------------ 差分测试抓出的两个缺陷（回归）


def test_fail_policy_raises_even_when_budget_drops_everything() -> None:
    """预算紧到什么都进不去时，``FAIL`` 策略**仍然必须**报告冲突。

    这是差分测试抓出来的真缺陷：早期实现把预算检查塞在同一个循环里，被预算
    丢弃的 key 永远进不了结果，也就永远没机会与后续来源比较——冲突检测被
    预算短路。极端情况下调用方要求"有分歧就告诉我"，得到的却是一个空结果，
    既没有分歧也没有错误。**静默成功是最坏的一种失败。**
    """
    parts = [{"a": "x"}, {"a": "y"}]

    with pytest.raises(AggregationError):
        merge(parts, policy=ConflictPolicy.FAIL, budget=MergeBudget(max_bytes=0))


def test_conflicts_are_independent_of_budget() -> None:
    """``conflicts`` 描述输入，不受输出预算影响。

    否则"把预算调小"会让分歧凭空消失——而分歧恰恰是调用方最需要知道的信息。
    """
    parts = [{"a": 1, "b": 2}, {"a": 9, "b": 8}]

    generous = merge(parts, budget=MergeBudget(max_items=100))
    starved = merge(parts, budget=MergeBudget(max_items=0))

    assert generous.conflicts == ("a", "b")
    assert starved.conflicts == ("a", "b"), (
        f"预算为 0 时 conflicts 变成 {starved.conflicts}；"
        "冲突检测被预算短路了"
    )
    assert starved.merged == {}
    assert starved.truncated is True
    assert starved.dropped == 2, "dropped 按 key 计，同一 key 多次出现不应重复计数"


def test_dropped_counts_keys_not_occurrences() -> None:
    """``dropped`` 是"丢了多少个字段"，不是"跳过多少次尝试"。

    按出现次数计会让同一个 key 的多次出现被重复累加，数字虚高且随输入分布变化。
    """
    parts = [{"a": 1}, {"a": 1}, {"a": 1}]  # 同一 key 出现三次，值相同
    result = merge(parts, budget=MergeBudget(max_items=0))

    assert result.dropped == 1, f"只有一个 key 被丢，实际 {result.dropped}"


def test_priority_low_tie_resolved_by_higher_source_is_not_a_conflict() -> None:
    """低优先级处出现过平手、但被严格更高优先级统一 -> 无未决分歧。

    结果无歧义，不需要人看。早期实现用"逐次比较 + 替换即裁决"会把这个假冲突
    残留下来。
    """
    parts = [{"d": "x"}, {"d": 1}, {"d": "x"}]
    result = merge(parts, policy=ConflictPolicy.PRIORITY, priorities=[2, 2, 3])

    assert result.merged["d"] == "x"
    assert result.conflicts == (), (
        f"最高优先级组只有 'x'，不该报冲突；实际 {result.conflicts}"
    )


def test_priority_disagreement_inside_top_group_is_a_conflict() -> None:
    """最高优先级组内部就有两个不同值 -> 真正未决，必须报。

    早期实现会漏掉这种：先遇到低优先级的值、再被高优先级替换，替换那一刻
    只比较了优先级数值，没注意同组内还有另一个值。
    """
    parts = [{"b": "y"}, {"b": "y"}, {"b": 3}]
    result = merge(parts, policy=ConflictPolicy.PRIORITY, priorities=[0, 3, 3])

    assert result.conflicts == ("b",), (
        f"最高优先级组内有 'y' 与 3 两个值，必须报冲突；实际 {result.conflicts}"
    )
