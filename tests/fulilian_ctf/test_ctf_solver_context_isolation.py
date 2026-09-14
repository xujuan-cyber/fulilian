"""P3.5 回归锁：CTF solve 路径绝不注入 cwd 项目上下文。

`_run_solver_turn` 构造 AIAgent 时必须传 ``skip_context_files=True``
（隔离 AGENTS.md / CLAUDE.md / .cursorrules —— 本仓库自己的 AGENTS.md
有 96KB，动态 cap 对 1M 窗口放行 240K，会全文进前缀）+ ``load_soul_identity=True``
（SOUL.md 身份保留，只隔离 cwd 链上的项目文件）。
"""

from __future__ import annotations

import run_agent


class _StubAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run_conversation(self, query):
        return {"completed": True, "api_calls": 1, "messages": [], "final_response": "ok"}


def test_ctf_solver_skips_cwd_context_files(monkeypatch):
    captured = {}

    def _recorder(**kwargs):
        captured.update(kwargs)
        return _StubAgent(**kwargs)

    monkeypatch.setattr(run_agent, "AIAgent", _recorder)
    out = run_agent._run_solver_turn(
        query="solve the challenge",
        model="test-model",
        max_turns=3,
        base_url="http://localhost:1/v1",
        api_key="k",
        enabled_toolsets_list=["ctf_solve"],
        disabled_toolsets_list=[],
        save_trajectories=False,
        verbose=False,
        log_prefix_chars=20,
        ctf_prompt=None,
    )
    assert out["result"]["completed"] is True
    assert captured.get("skip_context_files") is True
    assert captured.get("load_soul_identity") is True
