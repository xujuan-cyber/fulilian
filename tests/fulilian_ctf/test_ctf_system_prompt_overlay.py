"""回归锁：``agent.system_prompt`` 的会话 overlay 必须作用于 CTF 求解路径。

背景（静默失效类故障）：``resolve_ephemeral_system_prompt`` 的唯一读取点
``fulilian_cli/personality.py:160``，调用者此前只有 ``cli.py`` /
``gateway/run.py`` / ``tui_gateway/server.py`` —— **CTF 路径不在其中**；
而 ``agent/system_prompt.py:781`` 又要求 ``system_message is not None`` 才追加
该 overlay，CTF 路径传的是 None。两条路都堵死 → 用户写在 config 里的
「CTF 工作纪律」在求解器上完全不可见，配置看着生效、实际没有。

判据：``_build_ctf_system_prompt()`` 必须
  (a) 永远包含 CTF 认知架构；
  (b) 有 overlay 时把它附上；
  (c) 无 overlay 时不留下悬空的标题；
  (d) 走 ``fulilian_cli`` 的共享解析器，不自己读 ``agent.system_prompt`` 键
      （single-owner：overlay 解析只有一个所有者，重复实现会漂移）。
"""

from __future__ import annotations

import run_agent as ra

ARCH_MARKER = "4 阶段循环"
OVERLAY_HEADER = "用户配置的工作纪律"


# ── (a)(b)(c) 组合行为 ─────────────────────────────────────────────

def test_arch_always_present():
    assert ARCH_MARKER in ra._build_ctf_system_prompt()


def test_overlay_is_appended_when_present(monkeypatch):
    monkeypatch.setattr(ra, "_resolve_ctf_user_overlay",
                        lambda: "1) 发现即落盘：写 ctf-notes.md。")
    p = ra._build_ctf_system_prompt()
    assert ARCH_MARKER in p            # 架构没被顶掉
    assert OVERLAY_HEADER in p         # 有标题
    assert "ctf-notes.md" in p         # 有正文
    assert p.index(ARCH_MARKER) < p.index(OVERLAY_HEADER)  # 架构在前、纪律在后


def test_no_overlay_leaves_no_dangling_header(monkeypatch):
    monkeypatch.setattr(ra, "_resolve_ctf_user_overlay", lambda: "")
    p = ra._build_ctf_system_prompt()
    assert ARCH_MARKER in p
    assert OVERLAY_HEADER not in p, "无 overlay 时不应留下空标题"
    assert not p.endswith("\n\n"), "无 overlay 时不应多出空段"


# ── (d) 委托共享解析器，而不是自己读键 ─────────────────────────────

def test_delegates_to_shared_resolver(monkeypatch):
    """必须调用 fulilian_cli 的共享解析器（single-owner）。"""
    import fulilian_cli.config as fcfg

    called = {"n": 0}

    def _fake_resolver(cfg):
        called["n"] += 1
        return "来自共享解析器的纪律"

    monkeypatch.delenv("FULILIAN_EPHEMERAL_SYSTEM_PROMPT", raising=False)
    monkeypatch.setattr(fcfg, "load_config", lambda: {"agent": {"system_prompt": "不该被直接读到"}})
    monkeypatch.setattr(fcfg, "resolve_ephemeral_system_prompt_from_config", _fake_resolver)

    out = ra._resolve_ctf_user_overlay()
    assert called["n"] == 1, "没有走共享解析器"
    assert out == "来自共享解析器的纪律"
    assert "不该被直接读到" not in out, "绕过解析器直接读了 config 键"


def test_env_var_wins_over_config(monkeypatch):
    import fulilian_cli.config as fcfg

    monkeypatch.setenv("FULILIAN_EPHEMERAL_SYSTEM_PROMPT", "env 优先")
    monkeypatch.setattr(fcfg, "resolve_ephemeral_system_prompt_from_config",
                        lambda cfg: "config 不该赢")
    assert ra._resolve_ctf_user_overlay() == "env 优先"


def test_resolver_failure_yields_empty_not_crash(monkeypatch):
    """overlay 是增强项：解析炸了也不能把解题带崩。"""
    import fulilian_cli.config as fcfg

    monkeypatch.delenv("FULILIAN_EPHEMERAL_SYSTEM_PROMPT", raising=False)

    def _boom():
        raise RuntimeError("config 损坏")

    monkeypatch.setattr(fcfg, "load_config", _boom)
    assert ra._resolve_ctf_user_overlay() == ""
    # 且此时仍能拿到可用的 CTF prompt
    assert ARCH_MARKER in ra._build_ctf_system_prompt()
