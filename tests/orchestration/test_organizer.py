"""阶段 6 组织层测试。

每条用例钉一条决议：O2 命名确定性、O3 编制按资源非任务数、O4 资源不足返回空。
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from agent.orchestration.config import OrchestrationConfig
from agent.orchestration.organizer import Organizer, Slot, StaffingError
from agent.orchestration.store import Store


def _config(**overrides: object) -> OrchestrationConfig:
    return dataclasses.replace(OrchestrationConfig(), **overrides)


# ------------------------------------------------------------------ 编制依据


def test_staffing_uses_resources_not_queue_depth(tmp_path) -> None:
    """O3：编制只由"可并行资源"决定，排队任务再多也不多开人。

    两重证据：
    1. 签名里**没有**任何任务数/队列深度参数（有的话实现几乎必然写成
       ``min(tasks, cap)``）；
    2. 往库里塞 1000 个待办任务前后，同样的 ``active_by_pool`` 得到**完全相同**
       的编制结果。
    """
    # 证据 1：签名
    params = set(inspect.signature(Organizer.staffing).parameters)
    forbidden = {
        "queue_depth", "pending", "tasks", "task_count", "queued",
        "backlog", "waiting", "todo",
    }
    assert not (params & forbidden), (
        f"staffing() 出现了任务数类参数 {params & forbidden}；"
        "编制必须只依据可并行资源数，不能依据排队任务数"
    )

    # 证据 2：排队 0 个 vs 1000 个，结果必须一致
    cfg = _config(max_running=5, pools=(("solve", 3), ("audit", 2)))
    organizer = Organizer(cfg)
    active = {"solve": 1}

    before = organizer.staffing(active_by_pool=active)

    store = Store(str(tmp_path / "q.db"), worker_id="seed")
    try:
        for i in range(1000):
            store.enqueue(_card(f"t{i}"))
    finally:
        store.close()

    after = organizer.staffing(active_by_pool=active)

    assert before == after, (
        f"排队 1000 个任务后编制变了：{before} -> {after}；"
        "说明编制受任务数影响，违反 O3"
    )
    assert len(before) == 4, f"solve 配额 3 已有 1 个占位 -> 2 个新位；audit 2 个 -> 共 4，实际 {before}"


def test_staffing_is_deterministic() -> None:
    """O2：同样的输入调两次，名字序列必须逐字相同（禁 uuid/pid/时间戳）。"""
    organizer = Organizer(_config(max_running=5, pools=(("solve", 3), ("audit", 2))))

    first = organizer.staffing(active_by_pool={"solve": 1})
    second = organizer.staffing(active_by_pool={"solve": 1})

    assert first == second
    assert [s.name for s in first] == ["solve-01", "solve-02", "audit-00", "audit-01"]


def test_staffing_respects_pool_quota() -> None:
    """①细粒度策略：各池按自己的配额独立给位，且总和不超全局硬顶。"""
    organizer = Organizer(_config(max_running=5, pools=(("solve", 3), ("audit", 3))))

    slots = organizer.staffing(active_by_pool={})

    by_pool: dict[str, int] = {}
    for slot in slots:
        by_pool[slot.pool] = by_pool.get(slot.pool, 0) + 1
    assert by_pool == {"solve": 3, "audit": 2}, (
        f"audit 配额 3 但全局只剩 2，应给 2 个位；实际 {by_pool}"
    )
    assert len(slots) <= 5


def test_staffing_returns_empty_when_global_full() -> None:
    """O4：资源不足返回空元组，**不抛异常**——"暂时没资源"不是"系统故障"。"""
    organizer = Organizer(_config(max_running=2, pools=(("solve", 2),)))

    assert organizer.staffing(active_by_pool={"solve": 2}) == ()
    assert organizer.staffing(active_by_pool={"solve": 5}) == ()


def test_pools_sum_over_max_running_warns_not_raises() -> None:
    """§一：``sum(pools) > max_running`` 合法，只告警不拒绝启动。

    池配额是"各自最多多少"，不是"各自至少多少"：A 池空闲时 B 池本就该能用满
    全局额度。拒绝启动会让一份只是配额偏松的配置变成不可用，而真正的风险
    （超跑）由调度层的硬顶挡住。
    """
    cfg = _config(max_running=2, pools=(("solve", 5), ("audit", 5)))
    assert sum(cap for _, cap in cfg.pools) > cfg.max_running

    notes = cfg.warnings()
    assert notes, "sum(pools) > max_running 时必须给出告警"

    # 不抛异常，且编制仍被硬顶约束
    organizer = Organizer(cfg)
    slots = organizer.staffing(active_by_pool={})
    assert len(slots) == 2, f"总位数必须被 max_running=2 截住，实际 {len(slots)}"


def test_staffing_rejects_negative_active() -> None:
    organizer = Organizer(_config())
    with pytest.raises(StaffingError):
        organizer.staffing(active_by_pool={"solve": -1})


# ------------------------------------------------------------------ 技能匹配


def test_eligible_requires_skill_coverage() -> None:
    """⑤：技能不覆盖时不可接；覆盖时可接；池不匹配一律不可接。"""
    organizer = Organizer(
        _config(),
        skills_by_pool={"solve": frozenset({"python", "sql"})},
    )
    slot = Slot(name="solve-00", pool="solve", skills=frozenset({"python", "sql"}))

    assert organizer.eligible(slot, pool="solve", required=frozenset({"python"}))
    assert organizer.eligible(slot, pool="solve", required=frozenset())
    assert not organizer.eligible(slot, pool="solve", required=frozenset({"rust"}))
    assert not organizer.eligible(slot, pool="audit", required=frozenset({"python"}))


def test_undeclared_skills_means_unrestricted_not_empty() -> None:
    """``skills is None``（未声明）≠ ``frozenset()``（声明了零个技能）。

    两者混淆的后果是双向的：都当空集，未配置技能的环境变成"所有任务都不可调度"；
    都当 None，误配成空集的池会静默接走全部任务。
    """
    organizer = Organizer(_config())
    undeclared = organizer.staffing(active_by_pool={})[0]
    assert undeclared.skills is None
    assert organizer.eligible(undeclared, pool=undeclared.pool, required=frozenset({"x"}))

    declared_empty = Slot(name="solve-00", pool="solve", skills=frozenset())
    assert not organizer.eligible(
        declared_empty, pool="solve", required=frozenset({"x"})
    )
    assert organizer.eligible(declared_empty, pool="solve", required=frozenset())


def _card(task_id: str):
    from agent.orchestration.contracts import TaskCard

    return TaskCard(
        task_id=task_id,
        goal="g",
        dod=("d",),
        output_path=f"/tmp/out/{task_id}.md",
        pool="solve",
    )
