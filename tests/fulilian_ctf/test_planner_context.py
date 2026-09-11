"""P2 回归锁：ContextManager 裁剪按位置切 + Planner 执行器异常透传。

预修复基线（``git checkout HEAD -- fulilian_ctf/planner.py`` 后跑本文件，
再按 md5 恢复）::

    2 failed, 2 passed
    FAILED test_trim_keeps_early_turns_with_duplicate_content
    FAILED test_executor_error_surfaces_type_and_message

两条锁都对应实测到的、症状完全不同的缺陷：

1. ``_trim_if_needed`` 用 ``t not in recent`` 挑 early。``Turn`` 是普通
   dataclass，``in`` 走字段相等，于是「早先那轮与最近 3 轮内容雷同」会被
   判成同一个对象、从 early 里消失。它既不在摘要里也不在 recent 里 ——
   历史被静默丢弃。项目里这种重复内容很常见（"solver attempt N
   finished ok=False" 逐轮长得一样）。

2. ``_execute_task`` 的 except 只写 "Executor error for <id>"，异常类型与
   消息全部丢掉。summary 是上层唯一的故障线索，丢了就只能靠外部 traceback。
"""

from __future__ import annotations

from fulilian_ctf.blackboard import Blackboard
from fulilian_ctf.planner import ContextManager, Executor, Planner, TurnRole
from fulilian_ctf.reasoner import Task, TaskCategory, TaskResult


def _build_history() -> ContextManager:
    """构造「早先那轮与最后一轮内容雷同」的历史（不触发自动裁剪）。"""
    cm = ContextManager("planner", max_tokens=10_000)
    cm.set_system_prompt("SYS")
    cm.add_turn(TurnRole.USER, "DUP", is_reasoning=True)  # early，与末轮雷同
    cm.add_turn(TurnRole.USER, "b", is_reasoning=True)    # early
    cm.add_turn(TurnRole.USER, "c", is_reasoning=True)    # early
    cm.add_turn(TurnRole.USER, "d", is_reasoning=True)    # recent
    cm.add_turn(TurnRole.USER, "e", is_reasoning=True)    # recent
    cm.add_turn(TurnRole.USER, "DUP", is_reasoning=True)  # recent，与首轮雷同
    return cm


def test_trim_keeps_early_turns_with_duplicate_content():
    cm = _build_history()
    cm.max_tokens = 1  # 强制下次裁剪
    cm._trim_if_needed()

    contents = [t.content for t in cm.history]
    # 最近 3 轮原样保留
    assert "d" in contents and "e" in contents
    assert contents.count("DUP") == 1  # 最近那轮仍是 DUP（未被摘要吃掉）
    # 早先那轮 "DUP" 必须进摘要 —— 这就是旧实现丢掉它的地方
    summary = next(c for c in contents if c.startswith("---历史摘要---"))
    assert "DUP" in summary, f"早期重复轮次被静默丢弃: {summary!r}"
    assert "b" in summary and "c" in summary
    # system prompt + 摘要 + 最近 3 轮
    assert len(cm.history) == 5
    assert cm.history[0].content == "SYS"
    assert [t.content for t in cm.history[-3:]] == ["d", "e", "DUP"]


def test_trim_without_early_keeps_recent_only():
    """不足 4 轮非 system 时没有 early 可摘要，仍只保留 system + recent。"""
    cm = ContextManager("planner", max_tokens=10_000)
    cm.set_system_prompt("SYS")
    for text in ("a", "b", "c"):
        cm.add_turn(TurnRole.USER, text, is_reasoning=True)
    cm.max_tokens = 1
    cm._trim_if_needed()
    assert [t.content for t in cm.history] == ["SYS", "a", "b", "c"]


class _BoomExecutor(Executor):
    def __init__(self, exc: BaseException):
        self.exc = exc

    def execute(self, task: Task) -> TaskResult:  # pragma: no cover - 必抛
        raise self.exc


def _planner() -> Planner:
    # reasoner 只在 run() 里用；_execute_task 不碰它，给个占位即可。
    return Planner(reasoner=object(), blackboard=Blackboard())


def test_executor_error_surfaces_type_and_message():
    planner = _planner()
    planner.register_executor("web", _BoomExecutor(ValueError("socket closed early")))
    task = Task(id="t-1", category=TaskCategory.WEB)

    result = planner._execute_task(task)

    assert result.success is False and result.is_stuck is True
    assert "ValueError" in result.summary
    assert "socket closed early" in result.summary
    assert "t-1" in result.summary


def test_missing_executor_is_not_stuck_and_names_category():
    planner = _planner()
    task = Task(id="t-2", category=TaskCategory.CRYPTO)

    result = planner._execute_task(task)

    assert result.success is False
    # 没注册执行器 ≠ 卡住（is_stuck 会让上层反复重试一个根本没人能跑的任务）
    assert result.is_stuck is False
    assert "crypto" in result.summary
