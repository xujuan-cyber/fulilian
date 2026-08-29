"""AGENTS.md 项目级配置 (F4-001) 单元测试。"""

from __future__ import annotations

import json

from fulilian_ctf.agents_md import AGENTS_MD_FILENAME, ensure_agents_md, generate_agents_md
from fulilian_ctf.dispatcher import Project


def test_generate_agents_md_contains_sections():
    md = generate_agents_md(
        challenge_id="web-01",
        description="Apache path traversal",
        flag_format="flag{[a-f0-9]{32}}",
        category="web",
        target="10.0.0.5:80",
    )
    assert "题目 web-01" in md
    assert "## 题目描述" in md and "Apache path traversal" in md
    assert "flag{[a-f0-9]{32}}" in md
    assert "## 分类" in md and "web" in md
    assert "10.0.0.5:80" in md
    assert "## 已尝试方向" in md
    # 默认工具清单
    assert "nmap" in md and "python3" in md


def test_ensure_agents_md_creates_file(tmp_path):
    project = Project(
        challenge_id="crypto-easy",
        description="XOR cipher",
        category="crypto",
        target_host="10.0.0.5",
        target_port=1337,
    )
    path = ensure_agents_md(tmp_path / "crypto-easy", project)
    assert path is not None and path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "crypto-easy" in content and "XOR cipher" in content
    assert "10.0.0.5:1337" in content


def test_ensure_agents_md_does_not_overwrite(tmp_path):
    work = tmp_path / "web-01"
    work.mkdir()
    (work / AGENTS_MD_FILENAME).write_text("# 我手写的进度\n- CVE-2021-41773: 404", encoding="utf-8")
    project = Project(challenge_id="web-01", description="new desc")
    path = ensure_agents_md(work, project)
    assert "我手写的进度" in path.read_text(encoding="utf-8")  # 原 content 保留
    assert "new desc" not in path.read_text(encoding="utf-8")


def test_ensure_agents_md_reads_flag_format_from_challenge_json(tmp_path):
    work = tmp_path / "misc-1"
    work.mkdir()
    (work / "challenge.json").write_text(
        json.dumps({"id": "misc-1", "flag_format": "NSSCTF{...}"}), encoding="utf-8"
    )
    project = Project(challenge_id="misc-1")
    path = ensure_agents_md(work, project)
    assert "NSSCTF{...}" in path.read_text(encoding="utf-8")


def test_solver_worker_writes_agents_md(tmp_path, monkeypatch):
    """solver 进程入口会在工作目录生成 AGENTS.md（真实链路冒烟）。"""
    import queue as queue_mod

    from fulilian_ctf.solver import solver_worker

    project = Project(challenge_id="web-agents", category="web", description="d")
    work = tmp_path / "web-agents"
    q = queue_mod.Queue()

    captured = {}

    def fake_impl(proj, wd, query):
        captured["agents_md"] = (wd / "AGENTS.md").read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr("fulilian_ctf.solver.resolve_default_model", lambda: "test/model")
    solver_worker(project, str(work), "", q, solver_impl=fake_impl)
    assert "web-agents" in captured["agents_md"]
