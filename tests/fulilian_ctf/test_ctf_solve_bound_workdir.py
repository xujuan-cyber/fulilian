"""P0-4 回归锁：ctf_solve 统一 work_dir 边界校验（H-2）+ stub 工具移除（M-5）。

契约：
1. submit_flag / record_fact / git_auto_commit / declare_intent /
   mark_dead_end 共用 _bound_work_dir 校验，
   FULILIAN_CTF_WORK_DIR 绑定时严格相等才放行（子目录也拒绝）。
2. 绑定未设时只做基本合法性检查（保持单题直调兼容）。
3. 越界返回错误文本（工具协议字符串），不读/不写越界路径。
4. checkpoint / generate_writeup 两个 stub 工具从 registry 注销。
5. declare_intent / mark_dead_end：黑板写入、同 goal 去重、set 幂等。
"""

from __future__ import annotations

import subprocess

import pytest

import tools.ctf_solve as ctf_solve
from tools.registry import registry


@pytest.fixture
def bound_dir(tmp_path, monkeypatch):
    bound = tmp_path / "workspace"
    bound.mkdir()
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(bound))
    return bound


@pytest.fixture
def evil_dir(tmp_path):
    evil = tmp_path / "evil"
    evil.mkdir()
    return evil


# ── 1. 越界拒绝 ──────────────────────────────────────────────────────

def test_record_fact_rejects_out_of_bound(bound_dir, evil_dir):
    out = ctf_solve._record_fact_impl(work_dir=str(evil_dir), content="pwned")
    assert "outside the bound" in out
    assert list(evil_dir.iterdir()) == []  # 不落盘任何 blackboard


def test_submit_flag_rejects_out_of_bound(bound_dir, evil_dir):
    (evil_dir / "FLAG").write_text("flag{should_not_be_read}\n", encoding="utf-8")
    out = ctf_solve._submit_flag_impl(work_dir=str(evil_dir))
    assert "outside the bound" in out
    assert "should_not_be_read" not in out  # 未读越界 FLAG


def test_git_auto_commit_rejects_out_of_bound(bound_dir, evil_dir):
    out = ctf_solve._git_auto_commit_impl(work_dir=str(evil_dir), message="x")
    assert out == "git_auto_commit: work_dir is outside the bound CTF workspace"


# ── 2. 绑定相等放行（行为与现状一致）────────────────────────────────

def test_bound_equal_submit_flag_missing_flag(bound_dir):
    out = ctf_solve._submit_flag_impl(work_dir=str(bound_dir))
    assert "No FLAG file found" in out


def test_bound_equal_record_fact_publishes(bound_dir):
    from fulilian_ctf.blackboard import BLACKBOARD_FILENAME

    out = ctf_solve._record_fact_impl(work_dir=str(bound_dir), content="port 80 open")
    assert "record_fact: published" in out
    assert (bound_dir / BLACKBOARD_FILENAME).exists()


# ── 3. 未绑定兼容（单题直调不破坏）──────────────────────────────────

def test_unbound_env_still_works(tmp_path, monkeypatch):
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)
    free = tmp_path / "free"
    free.mkdir()
    out = ctf_solve._record_fact_impl(work_dir=str(free), content="anywhere")
    assert "record_fact: published" in out
    out2 = ctf_solve._submit_flag_impl(work_dir=str(free))
    assert "No FLAG file found" in out2


def test_unbound_env_invalid_work_dir_rejected(monkeypatch):
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)
    assert ctf_solve._submit_flag_impl(work_dir="") == (
        "submit_flag: work_dir is outside the bound CTF workspace"
    )


# ── 4. 子目录仍拒绝（锁定严格相等语义）──────────────────────────────

def test_subdirectory_of_bound_still_rejected(bound_dir):
    sub = bound_dir / "sub"
    sub.mkdir()
    out = ctf_solve._record_fact_impl(work_dir=str(sub), content="nested")
    assert "outside the bound" in out
    assert list(sub.iterdir()) == []


# ── 5. stub 工具消失 ────────────────────────────────────────────────

def test_stub_tools_removed_from_registry():
    assert registry.get_entry("checkpoint") is None
    assert registry.get_entry("generate_writeup") is None


# ── 6. git_auto_commit 行为零变化（锁定本机实测既有输出）────────────
#
# 注意：本机 git（zh_CN locale）把「无文件要提交」打到 stdout，stderr 为空，
# 实现里 "nothing to commit" in stderr 分支不命中，实测既有输出是
# "Auto-commit skipped: "（修复前用真实 impl 实测确认）。本测试锁定该
# 实际行为，防止重构造成漂移；文案本身的 locale 问题不属本卡范围。


def test_git_auto_commit_no_changes_message(bound_dir):
    subprocess.run(["git", "init"], cwd=str(bound_dir), capture_output=True, check=True)
    out = ctf_solve._git_auto_commit_impl(work_dir=str(bound_dir), message="step")
    assert out == "Auto-commit skipped: "


# ── 7. declare_intent / mark_dead_end（boomerang 多轮闭环的数据源）────
#
# 没有这两个工具，黑板的 intents / dead_ends 结构上永远为空：boomerang
# 每轮末尾读不到 open Intent，多轮机制退化成单轮（--max-rounds 失效）；
# 一个 solver 踩过的死路别的 solver 还会原样再踩。

def test_declare_intent_publishes_open_intent(bound_dir):
    from fulilian_ctf.blackboard import BLACKBOARD_FILENAME, State, load_blackboard

    out = ctf_solve._declare_intent_impl(
        work_dir=str(bound_dir), goal="inspect hidden endpoint", approach="HTTP headers"
    )
    assert out == "declare_intent: declared — inspect hidden endpoint"
    board = load_blackboard(bound_dir / BLACKBOARD_FILENAME)
    assert len(board.intents) == 1
    assert board.intents[0].goal == "inspect hidden endpoint"
    assert board.intents[0].approach == "HTTP headers"
    assert board.intents[0].state == State.OPEN


def test_declare_intent_dedupes_same_goal_any_state(bound_dir):
    from fulilian_ctf.blackboard import BLACKBOARD_FILENAME, load_blackboard

    first = ctf_solve._declare_intent_impl(work_dir=str(bound_dir), goal="probe admin")
    # strip 后同 goal 去重；意图声明与消费翻状态都不改变「已声明」事实
    second = ctf_solve._declare_intent_impl(work_dir=str(bound_dir), goal="  probe admin  ")
    assert "declared" in first
    assert "duplicate" in second
    board = load_blackboard(bound_dir / BLACKBOARD_FILENAME)
    assert len(board.intents) == 1


def test_declare_intent_rejects_out_of_bound(bound_dir, evil_dir):
    out = ctf_solve._declare_intent_impl(work_dir=str(evil_dir), goal="pwned")
    assert out == "declare_intent: work_dir is outside the bound CTF workspace"
    assert list(evil_dir.iterdir()) == []  # 不落盘任何 blackboard


def test_declare_intent_requires_goal(bound_dir):
    out = ctf_solve._declare_intent_impl(work_dir=str(bound_dir), goal="   ")
    assert out == "declare_intent: work_dir and goal are required"
    assert not (bound_dir / "blackboard.json").exists()


def test_mark_dead_end_publishes(bound_dir):
    from fulilian_ctf.blackboard import BLACKBOARD_FILENAME, load_blackboard

    out = ctf_solve._mark_dead_end_impl(
        work_dir=str(bound_dir),
        path="CVE-X not exploitable — 404 on all payloads",
    )
    assert out == "mark_dead_end: marked — CVE-X not exploitable — 404 on all payloads"
    board = load_blackboard(bound_dir / BLACKBOARD_FILENAME)
    assert board.dead_ends == {"CVE-X not exploitable — 404 on all payloads"}


def test_mark_dead_end_is_idempotent(bound_dir):
    from fulilian_ctf.blackboard import BLACKBOARD_FILENAME, load_blackboard

    ctf_solve._mark_dead_end_impl(work_dir=str(bound_dir), path="bruteforce /login")
    out = ctf_solve._mark_dead_end_impl(work_dir=str(bound_dir), path="bruteforce /login")
    assert "marked" in out  # set 语义：重复标记不报错
    board = load_blackboard(bound_dir / BLACKBOARD_FILENAME)
    assert board.dead_ends == {"bruteforce /login"}


def test_mark_dead_end_rejects_out_of_bound(bound_dir, evil_dir):
    out = ctf_solve._mark_dead_end_impl(work_dir=str(evil_dir), path="x")
    assert out == "mark_dead_end: work_dir is outside the bound CTF workspace"
    assert list(evil_dir.iterdir()) == []


def test_blackboard_tools_registered_in_ctf_solve():
    for name in ("record_fact", "declare_intent", "mark_dead_end"):
        entry = registry.get_entry(name)
        assert entry is not None, name
        assert entry.toolset == "ctf_solve"
