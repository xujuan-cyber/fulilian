"""kb_nudge hook（解题超时知识库注入）单测。

不读真实 ~/.fulilian/knowledge.db：knowledge_retriever.search 一律
monkeypatch。work_dir 用 tmp_path 隔离，.solve_start 手写控制 elapsed。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Fact,
    State,
    Blackboard,
    save_blackboard,
)
from fulilian_ctf.hooks import _kb_nudge_post_tool_hook
from fulilian_ctf.hooks.kb_nudge import KB_NUDGED_FILENAME

FAKE_RESULTS = [
    {
        "title": "RSA共模攻击笔记",
        "category": "crypto",
        "snippet": "两段密文共享模数时可用扩展欧几里得恢复明文...",
        "source_path": "/kb/CTF大赛WP集合/crypto/rsa-common-modulus.md",
    },
    {
        "title": "SSTI Jinja2 bypass",
        "category": "web",
        "snippet": "{{7*7}} 探测模板引擎后用 __mro__ 链绕过过滤...",
        "source_path": "/kb/WP汇总/ssti-bypass.md",
    },
]


def _make_work_dir(
    tmp_path: Path, elapsed: int | None = 700, facts=None, challenge_id="web-task1"
) -> Path:
    """构造隔离 work_dir：.solve_start 控制耗时，blackboard.json 塞 fact。"""
    wd = tmp_path / "work"
    wd.mkdir()
    if elapsed is not None:
        (wd / ".solve_start").write_text(
            str(int(time.time()) - elapsed), encoding="utf-8"
        )
    if facts is not None:
        board = Blackboard(challenge_id=challenge_id)
        # 兼容两种形态：纯字符串按 CONFIRMED 处理；(content, state) 元组原样
        for fact in facts:
            if isinstance(fact, str):
                board.add_fact(Fact(content=fact, state=State.CONFIRMED))
            else:
                content, state = fact
                board.add_fact(Fact(content=content, state=state))
        save_blackboard(board, wd / BLACKBOARD_FILENAME)
    return wd


@pytest.fixture
def fake_search(monkeypatch):
    """monkeypatch knowledge_retriever.search，记录调用参数。"""
    calls: list[dict] = []

    def _search(query, category=None, limit=5, auto_build=True):
        calls.append({"query": query, "category": category, "limit": limit})
        return list(FAKE_RESULTS)

    monkeypatch.setattr(
        "fulilian_ctf.knowledge_retriever.search", _search
    )
    return calls


# ── 触发条件 ────────────────────────────────────────────────────────────────

def test_no_injection_before_threshold(monkeypatch, tmp_path):
    wd = _make_work_dir(tmp_path, elapsed=100, facts=["phpinfo() 可用"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    # search 若被调用立即暴露（未超阈值根本不该走到检索）
    monkeypatch.setattr(
        "fulilian_ctf.knowledge_retriever.search",
        lambda *a, **kw: pytest.fail("search must not run before threshold"),
    )
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None


def test_no_work_dir_env(monkeypatch):
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None


def test_non_terminal_tool_ignored(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=700, facts=["phpinfo() 可用"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    assert _kb_nudge_post_tool_hook(tool_name="file", result="ok") is None
    assert fake_search == []


def test_no_solve_clock_marker(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=None, facts=["phpinfo() 可用"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert fake_search == []


# ── 注入与格式 ──────────────────────────────────────────────────────────────

def test_injects_after_threshold_with_formatted_context(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(
        tmp_path,
        elapsed=700,
        facts=[("nmap 扫出 80 端口 web 服务", State.CONFIRMED),
               ("弱口令 admin/admin 已排除", State.REFUTED)],
        challenge_id="web-task1",
    )
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    directive = _kb_nudge_post_tool_hook(tool_name="terminal", result="ok")
    assert directive and "context" in directive
    ctx = directive["context"]
    assert "解题已超过 10 分钟" in ctx
    assert "【RSA共模攻击笔记】" in ctx
    assert "/kb/CTF大赛WP集合/crypto/rsa-common-modulus.md" in ctx
    # query 来自黑板 fact 文本；category 来自 challenge_id 前缀启发
    assert fake_search and fake_search[0]["query"].startswith("nmap 扫出 80 端口")
    assert fake_search[0]["category"] == "web"
    assert fake_search[0]["limit"] == 3
    # 一次性标记已写
    assert (wd / KB_NUDGED_FILENAME).exists()


def test_one_shot_second_call_returns_none(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=700, facts=["heap overflow 可达"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    first = _kb_nudge_post_tool_hook(tool_name="terminal", result="ok")
    assert first is not None
    second = _kb_nudge_post_tool_hook(tool_name="terminal", result="ok")
    assert second is None
    # 检索只发生一次
    assert len(fake_search) == 1


def test_marker_file_short_circuits_even_without_clock(monkeypatch, tmp_path, fake_search):
    """标记存在即跳过（宽松去重），连时钟检查都不需要。"""
    wd = _make_work_dir(tmp_path, elapsed=700, facts=["heap overflow 可达"])
    (wd / KB_NUDGED_FILENAME).write_text("1", encoding="utf-8")
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert fake_search == []


# ── 跳过 / 降级 ─────────────────────────────────────────────────────────────

def test_skips_without_blackboard(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=700, facts=None)
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert fake_search == []


def test_skips_with_empty_blackboard_facts(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=700, facts=[])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert fake_search == []


def test_skips_open_state_facts(monkeypatch, tmp_path, fake_search):
    """只有 OPEN 态 fact 时没有可检索的确认信息 → 跳过。"""
    wd = _make_work_dir(
        tmp_path, elapsed=700, facts=[("maybe sql injection?", State.OPEN)]
    )
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert fake_search == []


def test_empty_search_results_no_injection(monkeypatch, tmp_path):
    wd = _make_work_dir(tmp_path, elapsed=700, facts=["very specific keyword"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    monkeypatch.setattr(
        "fulilian_ctf.knowledge_retriever.search", lambda *a, **kw: []
    )
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert not (wd / KB_NUDGED_FILENAME).exists()


def test_search_exception_fail_open(monkeypatch, tmp_path):
    """search 抛异常 → fail-open 返回 None，绝不外泄异常。"""
    wd = _make_work_dir(tmp_path, elapsed=700, facts=["boom keyword"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))

    def _boom(*a, **kw):
        raise RuntimeError("kb index exploded")

    monkeypatch.setattr("fulilian_ctf.knowledge_retriever.search", _boom)
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None


# ── 阈值覆盖 ────────────────────────────────────────────────────────────────

def test_env_threshold_override_triggers_earlier(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=60, facts=["foothold established"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    monkeypatch.setenv("FULILIAN_CTF_KB_NUDGE_SECONDS", "30")
    directive = _kb_nudge_post_tool_hook(tool_name="terminal", result="ok")
    assert directive and "解题已超过 1 分钟" in directive["context"]


def test_env_threshold_override_still_blocks_below(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=10, facts=["foothold established"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    monkeypatch.setenv("FULILIAN_CTF_KB_NUDGE_SECONDS", "30")
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None


def test_invalid_env_threshold_falls_back_to_default(monkeypatch, tmp_path, fake_search):
    wd = _make_work_dir(tmp_path, elapsed=100, facts=["some fact"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    monkeypatch.setenv("FULILIAN_CTF_KB_NUDGE_SECONDS", "not-a-number")
    assert _kb_nudge_post_tool_hook(tool_name="terminal", result="ok") is None
    assert fake_search == []


# ── 注册路由：post_tool_call 能分发到 kb_nudge ───────────────────────────────

class _FakeManager:
    def __init__(self):
        self._hooks = {}


def test_registered_post_hooks_route_to_kb_nudge(monkeypatch, tmp_path):
    """注册后，plugin manager 的 post_tool_call 钩子序列里包含 kb_nudge，
    并能在满足条件时（超阈值 + 黑板 fact）实际路由到注入。"""
    import fulilian_ctf.hooks as hooks_mod

    manager = _FakeManager()
    monkeypatch.setattr("fulilian_cli.plugins.get_plugin_manager", lambda: manager)
    registered = hooks_mod.register_ctf_tool_hooks()
    assert registered == ["pre_tool_call", "post_tool_call"]
    post_hooks = manager._hooks["post_tool_call"]
    assert hooks_mod._kb_nudge_post_tool_hook in post_hooks

    wd = _make_work_dir(tmp_path, elapsed=700, facts=["knudge route fact"])
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(wd))
    monkeypatch.setattr(
        "fulilian_ctf.knowledge_retriever.search",
        lambda *a, **kw: list(FAKE_RESULTS),
    )
    contexts = []
    for hook in post_hooks:
        directive = hook(tool_name="terminal", result="ok")
        if isinstance(directive, dict):
            contexts.append(directive)
    assert any("知识库中与本题相关的历史思路" in c["context"] for c in contexts)
