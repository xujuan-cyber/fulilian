"""P0-2 细粒度循环检测测试（loop_guard + hooks 接线）。

覆盖：
- LoopDetector 纯逻辑：warn(≥3)/break(≥5) 阈值、签名稳定性（dict 序序无关）、
  窗口驱逐、不同签名互不干扰、开关（FULILIAN_LOOP_GUARD=0）
- hooks 接线：_ctf_pre_tool_hook 第 5 次同签名 block；warn 经
  _ctf_post_tool_hook 注入 context（与 flag-candidate 提示可共存）
"""

from __future__ import annotations

import pytest

import fulilian_ctf.loop_guard as lg
from fulilian_ctf.loop_guard import LoopDetector, reset_default_detector


@pytest.fixture(autouse=True)
def _clean_detector(monkeypatch):
    monkeypatch.delenv(lg.ENV_LOOP_GUARD, raising=False)
    reset_default_detector()
    yield
    reset_default_detector()


def test_thresholds_warn_then_break():
    det = LoopDetector()
    verdicts = [det.check("terminal", {"command": "ls"}) for _ in range(5)]
    assert verdicts == [None, None, lg.WARN, lg.WARN, lg.BREAK]


def test_dict_args_order_insensitive():
    det = LoopDetector()
    det.check("t", {"a": 1, "b": 2})
    det.check("t", {"b": 2, "a": 1})
    assert det.check("t", {"a": 1, "b": 2}) == lg.WARN  # 第 3 次同签名 → warn
    assert det.check("t", {"b": 2, "a": 1}) == lg.WARN


def test_different_signature_does_not_count():
    det = LoopDetector()
    for _ in range(4):
        det.check("t", {"cmd": "same"})
    assert det.check("t", {"cmd": "different"}) is None
    assert det.check("t", "not-a-dict") is None


def test_window_eviction():
    det = LoopDetector(window=4, warn_threshold=3, break_threshold=5)
    # 计数含当前这次：第 4 次调用后窗口 [a,a,b,a] → a 出现 3 次 → warn
    det.check("t", "a")
    det.check("t", "a")
    det.check("t", "b")
    assert det.check("t", "a") == lg.WARN
    # 驱逐后（窗口 [a,b,a,a]）仍是 3 → warn 而非 break
    assert det.check("t", "a") == lg.WARN


def test_break_persists_while_repeating():
    det = LoopDetector()
    for _ in range(5):
        det.check("t", "x")
    assert det.check("t", "x") == lg.BREAK
    assert det.check("t", "x") == lg.BREAK


def test_reset_clears_state():
    det = LoopDetector()
    for _ in range(4):
        det.check("t", "x")
    det.reset()
    assert det.check("t", "x") is None


def test_kill_switch(monkeypatch):
    monkeypatch.setenv(lg.ENV_LOOP_GUARD, "0")
    det = LoopDetector()
    for _ in range(6):
        assert det.check("t", "x") is None


# ── hooks 接线 ──────────────────────────────────────────────────────────

def _call_pre(tool_name, args):
    from fulilian_ctf.hooks import _ctf_pre_tool_hook

    return _ctf_pre_tool_hook(tool_name=tool_name, args=args)


def _call_post(tool_name="terminal", result=""):
    from fulilian_ctf.hooks import _ctf_post_tool_hook

    return _ctf_post_tool_hook(tool_name=tool_name, result=result)


def test_pre_hook_blocks_on_break():
    # 前两次放行（第 3 次起 warn），第 5 次同签名 → block
    args = {"command": "echo hi"}
    assert _call_pre("terminal", args) is None
    assert _call_pre("terminal", args) is None
    assert _call_pre("terminal", args) is None  # warn：pre 不 block
    assert _call_pre("terminal", args) is None
    out = _call_pre("terminal", args)
    assert isinstance(out, dict) and out["action"] == "block"
    assert "loop-guard" in out["message"]


def test_pre_hook_non_terminal_tool_also_guarded():
    args = {"url": "http://x"}
    for _ in range(4):
        assert _call_pre("http_fetch", args) is None
    out = _call_pre("http_fetch", args)
    assert isinstance(out, dict) and out["action"] == "block"


def test_warn_injected_via_post_context():
    args = {"command": "ls -la"}
    for _ in range(3):
        _call_pre("terminal", args)
    out = _call_post(result="plain output")
    assert out is not None and "[loop-guard]" in out["context"]


def test_warn_and_flag_candidate_coexist():
    args = {"command": "strings dump.bin"}
    for _ in range(3):
        _call_pre("terminal", args)
    out = _call_post(result="found flag{abc123} here")
    assert out is not None
    assert "[loop-guard]" in out["context"]
    assert "[flag-candidate]" in out["context"]


def test_no_warn_no_context(monkeypatch):
    args = {"command": "ls"}
    _call_pre("terminal", args)
    monkeypatch.delenv(lg.ENV_LOOP_GUARD, raising=False)
    assert _call_post(result="nothing here") is None
