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


class _FakeMpModule:
    """旧版 dispatcher 无 _SAFE_MP_CONTEXT 时替身 multiprocessing。"""

    def Queue(self):
        return None

    def Process(self, target=None, args=(), name=None):
        return _FakeProc()


@pytest.fixture
def fake_mp(monkeypatch):
    if hasattr(dispatcher_mod, "_SAFE_MP_CONTEXT"):
        monkeypatch.setattr(dispatcher_mod, "_SAFE_MP_CONTEXT", _FakeCtx())
    else:
        monkeypatch.setattr(dispatcher_mod, "multiprocessing", _FakeMpModule())


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
    esc = dispatcher._apply_escalation(p, "switch_model", "STOPPED: BUDGET_EXCEEDED (...)")
    # 换模型值经返回值传递，而不是写 project.model —— _spawn 的
    # `self.model or project.model` 会在 self.model 非空时吞掉后者
    assert esc.model == "model-b"
    assert esc.route == "switch_model"
    assert dispatcher.escalations == 1


def test_switch_model_survives_global_model_override(dispatcher, monkeypatch, tmp_path):
    """CLI 传了 --model（self.model 非空）时换模型升级仍须生效。

    旧实现把新模型写进 project.model，被 _spawn 的
    `self.model or project.model` 短路吞掉 → 升级静默失效。
    """
    import fulilian_ctf.racer as racer

    class _RecordingCtx:
        def __init__(self):
            self.spawn_args: list[tuple] = []

        def Queue(self):
            return None

        def Process(self, target=None, args=(), name=None):
            self.spawn_args.append(args)

            class _P:
                pid = 4242

                def start(self):
                    pass

            return _P()

    monkeypatch.setattr(racer, "resolve_race_models", lambda *a, **kw: ["model-b"])
    ctx = _RecordingCtx()
    monkeypatch.setattr(dispatcher_mod, "_SAFE_MP_CONTEXT", ctx)
    dispatcher.model = "global-model"  # 模拟 CLI --model
    p = _project(tmp_path, stop_reason="STOPPED: BUDGET_EXCEEDED (...) after 1s")
    dispatcher._spawn(p)
    # Queue 目标参数顺序：(solver_fn, project, work_dir, model, queue)
    assert ctx.spawn_args[0][3] == "model-b"  # 而非 global-model


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
    esc = dispatcher._apply_escalation(p, "extend_timebox", p.stop_reason)
    assert esc.timebox_multiplier == 1.5
    # 倍率不再落在 Dispatcher 实例上（跨题共享 → 竞态）
    assert not hasattr(dispatcher, "_timebox_multiplier")

    base = 200
    p.timebox_override = base
    dispatcher._spawn(p)  # respawn 模拟（假进程）
    tb = dispatcher._running["c1"]["timebox"]
    assert tb.initial_budget == int(base * 1.5)
    assert p.status == ChallengeStatus.IN_PROGRESS


def test_extend_timebox_multiplier_does_not_leak_to_other_project(
    dispatcher, tmp_path, fake_mp
):
    """倍率只对触发升级的那道题生效，不污染同批 spawn 的其它题。

    旧实现把倍率写进 self._timebox_multiplier：_spawn_candidates 用线程池
    并行探活-分配，先进入 _spawn 的**别的题**会消费掉它并复位，触发升级的
    题自己反而拿不到延长。
    """
    upgraded = _project(tmp_path, stop_reason="STOPPED: NO_OUTPUT (无产出) after 60s")
    other = Project(
        challenge_id="c2", challenge_dir=str(tmp_path / "other"), difficulty="easy",
        title="t2", category="web", description="base", score=100,
    )
    # 升级动作先于两次 spawn 发生（旧代码下 other 会偷走倍率）
    dispatcher._apply_escalation(upgraded, "extend_timebox", upgraded.stop_reason)
    upgraded.timebox_override = other.timebox_override = 200

    dispatcher._spawn(other)
    dispatcher._spawn(upgraded)

    assert dispatcher._running["c2"]["timebox"].initial_budget == 200  # 未被污染
    assert dispatcher._running["c1"]["timebox"].initial_budget == 300  # 200 * 1.5


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
