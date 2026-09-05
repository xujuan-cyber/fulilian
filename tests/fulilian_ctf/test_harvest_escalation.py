"""P0-3 回归锁：收割轮 respawn 升级接线（C-冲突1）。

覆盖：路由表 / [Escalation] 块不累积且与 [Specialist Prompt] 共存 /
换模型与退化 / timebox 1.5× 延长 / 决策时序快照 / escalations 计数。
mock 级测试：_spawn 用假进程上下文，不启动真 solver。
"""

from __future__ import annotations

import pytest

import fulilian_ctf.dispatcher as dispatcher_mod
from fulilian_ctf.dispatcher import (
    DEFAULT_ROUTE,
    ESCALATION_ROUTES,
    ChallengeStatus,
    Dispatcher,
    Project,
)


@pytest.fixture
def dispatcher():
    return Dispatcher(quiet=True)


def _project(tmp_path, status=ChallengeStatus.ABANDONED, stop_reason=""):
    return Project(
        challenge_id="c1",
        challenge_dir=str(tmp_path),
        difficulty="easy",
        title="t",
        category="web",
        description="base task",
        score=100,
        status=status,
        stop_reason=stop_reason,
    )


class _FakeProc:
    pid = 4242

    def start(self):
        pass


class _FakeCtx:
    def Queue(self):
        return None

    def Process(self, target=None, args=(), name=None):
        return _FakeProc()


@pytest.fixture
def fake_mp(monkeypatch):
    monkeypatch.setattr(dispatcher_mod, "_SAFE_MP_CONTEXT", _FakeCtx())


# ── 1. 路由表：参数化 (status, stop_reason) → route ─────────────────

@pytest.mark.parametrize(
    "status,stop_reason,expected",
    [
        (ChallengeStatus.ABANDONED,
         "STOPPED: HYPOTHESIS_REPEATED (假设空间重复) after 60s",
         "switch_attack_class"),
        (ChallengeStatus.ABANDONED,
         "STOPPED: NO_OUTPUT (无产出) after 60s",
         "extend_timebox"),
        (ChallengeStatus.ABANDONED,
         "STOPPED: BUDGET_EXCEEDED (预算超限) after 60s",
         "switch_model"),
        (ChallengeStatus.TIMEOUT,
         "timebox expired at tier 't2' after 100s (budget 100s)",
         "switch_approach"),
        # 未命中路由 → 现状行为
        (ChallengeStatus.ABANDONED,
         "STOPPED: INFRA_BLOCKED (不可达) after 60s",
         DEFAULT_ROUTE),
        (ChallengeStatus.ABANDONED, "", DEFAULT_ROUTE),
        (ChallengeStatus.NEW, "", DEFAULT_ROUTE),
    ],
)
def test_route_table(dispatcher, status, stop_reason, expected):
    p = _project(tmp_path=None, status=status, stop_reason=stop_reason)
    route, detail = dispatcher._escalation_for(p)
    assert route == expected
    assert detail == stop_reason


def test_route_table_shape():
    # 契约 1：映射集中在模块级常量
    assert ESCALATION_ROUTES[("*", "HYPOTHESIS_REPEATED")] == "switch_attack_class"
    assert ESCALATION_ROUTES[("*", "NO_OUTPUT")] == "extend_timebox"
    assert ESCALATION_ROUTES[("*", "BUDGET_EXCEEDED")] == "switch_model"
    assert ESCALATION_ROUTES[(ChallengeStatus.TIMEOUT.value, None)] == "switch_approach"
    assert DEFAULT_ROUTE == "plain_retry"


# ── 2. [Escalation] 块：剥旧注新不累积，与 [Specialist Prompt] 共存 ──

def test_escalation_block_no_accumulation(dispatcher):
    p = _project(tmp_path=None)
    p.description = (
        "base task\n\n[Specialist Prompt]\nweb workflow here"
    )
    for _ in range(2):  # 模拟两次 respawn
        dispatcher._apply_escalation(
            p, "switch_attack_class", "STOPPED: HYPOTHESIS_REPEATED (...)"
        )
    assert p.description.count("[Escalation]") == 1
    assert p.description.count("[Specialist Prompt]") == 1
    # [Escalation] 在 prompt 末尾（最新指令最后）
    assert p.description.rstrip().endswith("不要死磕。") or \
        p.description.find("[Escalation]") > p.description.find("[Specialist Prompt]")
    assert "已证死路" in p.description  # 块内含差异化指令


# ── 3. 换模型：resolve_race_models 取下一个；异常退化 ───────────────

def test_switch_model_picks_next(dispatcher, monkeypatch):
    import fulilian_ctf.racer as racer

    monkeypatch.setattr(racer, "resolve_race_models",
                        lambda *a, **kw: ["model-a", "model-b"])
    p = _project(tmp_path=None)
    p.model = "model-a"
    dispatcher._apply_escalation(p, "switch_model", "STOPPED: BUDGET_EXCEEDED (...)")
    assert p.model == "model-b"
    assert dispatcher.escalations == 1


def test_switch_model_degrades_on_racer_error(dispatcher, monkeypatch):
    import fulilian_ctf.racer as racer

    def boom(*a, **kw):
        raise ValueError("no racer config")

    monkeypatch.setattr(racer, "resolve_race_models", boom)
    p = _project(tmp_path=None)
    p.model = "model-a"
    dispatcher._apply_escalation(p, "switch_model", "STOPPED: BUDGET_EXCEEDED (...)")
    assert p.model == "model-a"  # 未换名
    assert getattr(dispatcher, "escalations", 0) == 0  # 退化为 plain_retry，不计 escalation


# ── 4. 延长 timebox：NO_OUTPUT → 本次 respawn 1.5× ──────────────────

def test_extend_timebox_multiplier_applied_once(dispatcher, tmp_path, fake_mp):
    p = _project(
        tmp_path,
        stop_reason="STOPPED: NO_OUTPUT (无产出) after 60s",
    )
    dispatcher._apply_escalation(p, "extend_timebox", p.stop_reason)
    assert dispatcher._timebox_multiplier == 1.5

    base = 200
    p.timebox_override = base
    dispatcher._spawn(p)  # respawn 模拟（假进程）
    tb = dispatcher._running["c1"]["timebox"]
    assert tb.initial_budget == int(base * 1.5)
    # 一次性生效：消费后复位
    assert dispatcher._timebox_multiplier == 1.0
    assert p.status == ChallengeStatus.IN_PROGRESS


# ── 5. 决策时序：升级决策读取的是状态重置前的快照 ───────────────────

def test_escalation_decision_before_status_reset(dispatcher, tmp_path, fake_mp):
    p = _project(
        tmp_path,
        stop_reason="STOPPED: HYPOTHESIS_REPEATED (假设空间重复) after 60s",
    )
    dispatcher._spawn(p)  # _spawn 内部会重置 status → IN_PROGRESS
    # status 已被重置，但升级动作已按旧快照执行
    assert p.status == ChallengeStatus.IN_PROGRESS
    assert "[Escalation]" in p.description  # switch_attack_class 已注入


# ── 6. escalations 计数进入 summary ─────────────────────────────────

def test_escalation_counter_in_summary(dispatcher, tmp_path, fake_mp):
    p1 = _project(tmp_path,
                  stop_reason="STOPPED: HYPOTHESIS_REPEATED (...) after 1s")
    dispatcher._spawn(p1)
    p2 = _project(tmp_path,
                  stop_reason="STOPPED: INFRA_BLOCKED (...) after 1s")  # 无路由
    dispatcher._spawn(p2)
    assert dispatcher.escalations == 1
    # run() 返回的 summary dict 含 escalations 键
    import inspect

    src = inspect.getsource(Dispatcher.run)
    assert '"escalations"' in src or "'escalations'" in src
