"""回归锁：hard-solve-protocol 的 env 门控注入必须按设计送达 CTF system prompt。

背景（静默失效类故障）：solve 路径在 A9 后没有 ``skill_view``/``skills_list``
工具，技能库文件本身到不了 solver，所以协议走 ``_resolve_hard_solve_protocol()``
注入 CTF system prompt，正文以 ``hard-solve-protocol/SKILL.md`` 为单一来源。

本测试锁四条：
  (a) env 关 → 不注入（实验组/对照组靠 env 区分，关闭侧必须干净）；
  (b) env 开 + 文件在 → 注入，且位于架构与用户纪律之间；
  (c) env 开 + 文件缺失 → 返回空串**且大声报错**（"实验组静默变对照组"
      是假对照，必须看得见，不许冒充协议效果）；
  (d) frontmatter 不泄漏进注入正文。
"""

from __future__ import annotations

import logging

import run_agent as ra

ARCH_MARKER = "4 阶段循环"
PROTOCOL_MARKER = "难题解题协议"
OVERLAY_HEADER = "用户配置的工作纪律"

PROTOCOL_BODY = (
    "## 难题解题协议（hard-solve-protocol）\n"
    "1. **状态卡落盘**：在 ctf-notes.md 建「事实 / 假设 / 已排除 / 证据」四段。\n"
    "5. **收尾证伪**：写候选 flag 前跑一遍反方向。\n"
)


def _make_skill(tmp_path):
    """在隔离 FULILIAN_HOME 下布一份最小 SKILL.md，路径与产品一致。"""
    d = tmp_path / "skills" / "hard-solve-protocol"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: hard-solve-protocol\ncategory: ctf\n---\n" + PROTOCOL_BODY,
        encoding="utf-8")
    return d


# ── (a) env 门控 ──────────────────────────────────────────────────────

def test_env_off_no_injection(monkeypatch):
    monkeypatch.delenv("FULILIAN_CTF_HARD_SOLVE_PROTOCOL", raising=False)
    assert ra._resolve_hard_solve_protocol() == ""
    # 且整条 prompt 里也没有协议段
    assert PROTOCOL_MARKER not in ra._build_ctf_system_prompt()


# ── (b) 注入位置 ──────────────────────────────────────────────────────

def test_env_on_injects_between_arch_and_overlay(monkeypatch, tmp_path):
    _make_skill(tmp_path)
    monkeypatch.setenv("FULILIAN_CTF_HARD_SOLVE_PROTOCOL", "1")
    monkeypatch.setenv("FULILIAN_HOME", str(tmp_path))
    monkeypatch.setattr(ra, "_resolve_ctf_user_overlay", lambda: "1) 发现即落盘。")

    p = ra._build_ctf_system_prompt()
    assert ARCH_MARKER in p
    assert PROTOCOL_MARKER in p
    assert OVERLAY_HEADER in p
    # 顺序：架构 → 协议 → 用户纪律（用户显式写的最后，优先级最高）
    assert (p.index(ARCH_MARKER) < p.index(PROTOCOL_MARKER)
            < p.index(OVERLAY_HEADER))


def test_env_on_overlay_absent_protocol_present(monkeypatch, tmp_path):
    _make_skill(tmp_path)
    monkeypatch.setenv("FULILIAN_CTF_HARD_SOLVE_PROTOCOL", "1")
    monkeypatch.setenv("FULILIAN_HOME", str(tmp_path))
    monkeypatch.setattr(ra, "_resolve_ctf_user_overlay", lambda: "")
    p = ra._build_ctf_system_prompt()
    assert PROTOCOL_MARKER in p
    assert OVERLAY_HEADER not in p, "无 overlay 时不应留空标题"
    assert not p.endswith("\n\n")


# ── (c) 文件缺失必须大声 ──────────────────────────────────────────────

def test_env_on_missing_file_logs_loud(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("FULILIAN_CTF_HARD_SOLVE_PROTOCOL", "1")
    monkeypatch.setenv("FULILIAN_HOME", str(tmp_path))  # 目录下没有技能文件
    with caplog.at_level(logging.ERROR, logger=ra.__name__):
        out = ra._resolve_hard_solve_protocol()
    assert out == ""
    assert any("读不到" in r.message for r in caplog.records), \
        "文件缺失必须记 error（A/B 里静默 = 假对照）"


def test_env_on_empty_body_logs_loud(monkeypatch, tmp_path, caplog):
    d = tmp_path / "skills" / "hard-solve-protocol"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: hard-solve-protocol\n---\n\n",
                                encoding="utf-8")
    monkeypatch.setenv("FULILIAN_CTF_HARD_SOLVE_PROTOCOL", "1")
    monkeypatch.setenv("FULILIAN_HOME", str(tmp_path))
    with caplog.at_level(logging.ERROR, logger=ra.__name__):
        out = ra._resolve_hard_solve_protocol()
    assert out == ""
    assert any("正文为空" in r.message for r in caplog.records)


# ── (d) frontmatter 不泄漏 ────────────────────────────────────────────

def test_frontmatter_not_leaked(monkeypatch, tmp_path):
    _make_skill(tmp_path)
    monkeypatch.setenv("FULILIAN_CTF_HARD_SOLVE_PROTOCOL", "1")
    monkeypatch.setenv("FULILIAN_HOME", str(tmp_path))
    body = ra._resolve_hard_solve_protocol()
    assert "name: hard-solve-protocol" not in body
    assert "---" not in body
    assert "状态卡落盘" in body
