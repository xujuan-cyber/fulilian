"""CTF shell hooks (F4-003/F4-004) 子进程协议测试。

按 agent/shell_hooks.py 的 wire 协议：stdin JSON → stdout JSON / 退出码。
"""

from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[2] / "fulilian_ctf" / "hooks"
CHECK_DANGEROUS = HOOKS_DIR / "check_dangerous.py"
DETECT_FLAG = HOOKS_DIR / "detect_flag.py"


def _run_hook(script: Path, payload: dict, env: dict | None = None):
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _pre_payload(command: str, cwd: str = ".") -> dict:
    return {
        "hook_event_name": "pre_tool_call",
        "tool_name": "terminal",
        "args": {"command": command},
        "cwd": cwd,
    }


# ── check_dangerous.py ──────────────────────────────────────────────────────

def test_dangerous_command_blocked():
    for cmd in (
        "rm -rf /",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "chmod 777 /",
        "iptables -F",
        "shutdown now",
    ):
        proc = _run_hook(CHECK_DANGEROUS, _pre_payload(cmd))
        assert proc.returncode == 2, f"{cmd} should block (exit 2), got {proc.returncode}"
        out = json.loads(proc.stdout)
        assert out["action"] == "block"
        assert "blocked" in out["message"]


def test_benign_command_allowed(monkeypatch):
    proc = _run_hook(CHECK_DANGEROUS, _pre_payload("nmap -sV 10.0.0.5"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""  # 放行时不输出 block JSON


def test_sandbox_read_only_blocks_write(tmp_path):
    import os

    env = dict(os.environ)
    env["FULILIAN_SANDBOX_MODE"] = "read-only"
    proc = _run_hook(CHECK_DANGEROUS, _pre_payload("touch pwned.txt", cwd=str(tmp_path)), env=env)
    assert proc.returncode == 2
    out = json.loads(proc.stdout)
    assert "READ_ONLY" in out["message"]


def test_sandbox_workspace_write_blocks_outside_redirect(tmp_path):
    import os

    env = dict(os.environ)
    env["FULILIAN_SANDBOX_MODE"] = "workspace-write"
    proc = _run_hook(
        CHECK_DANGEROUS, _pre_payload("echo hi > /etc/pwned", cwd=str(tmp_path)), env=env
    )
    assert proc.returncode == 2
    out = json.loads(proc.stdout)
    assert "outside workspace" in out["message"]


def test_sandbox_workspace_write_allows_inside(tmp_path):
    import os

    env = dict(os.environ)
    env["FULILIAN_SANDBOX_MODE"] = "workspace-write"
    proc = _run_hook(
        CHECK_DANGEROUS, _pre_payload("echo hi > out.txt", cwd=str(tmp_path)), env=env
    )
    assert proc.returncode == 0


def test_bad_json_fail_open():
    proc = subprocess.run(
        [sys.executable, str(CHECK_DANGEROUS)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0  # fail-open


# ── detect_flag.py ──────────────────────────────────────────────────────────

def test_detect_flag_emits_context():
    payload = {
        "hook_event_name": "post_tool_call",
        "tool_name": "terminal",
        "args": {"command": "curl target"},
        "result": json.dumps({"output": " exploitation done, flag{abc123def456} found"}),
    }
    proc = _run_hook(DETECT_FLAG, payload)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert "context" in out
    assert "flag{abc123def456}" in out["context"]
    assert "FLAG file" in out["context"]  # 引导声明式提交


def test_detect_flag_silent_without_flag():
    payload = {
        "hook_event_name": "post_tool_call",
        "tool_name": "terminal",
        "args": {"command": "ls"},
        "result": json.dumps({"output": "no flag here"}),
    }
    proc = _run_hook(DETECT_FLAG, payload)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ── 进程内回调 + 注册（fulilian solve 默认路径，无 ~/.fulilian 写入） ──────────

def test_inprocess_pre_hook_blocks_dangerous():
    from fulilian_ctf.hooks import _ctf_pre_tool_hook

    directive = _ctf_pre_tool_hook(
        tool_name="terminal", args={"command": "rm -rf /"}, cwd="/tmp"
    )
    assert directive == {"action": "block", "message": directive["message"]}
    assert "blocked" in directive["message"]
    assert _ctf_pre_tool_hook(tool_name="file", args={"path": "x"}) is None
    assert _ctf_pre_tool_hook(
        tool_name="terminal", args={"command": "nmap -sV target"}
    ) is None


def test_inprocess_pre_hook_enforces_sandbox(monkeypatch, tmp_path):
    from fulilian_ctf.hooks import _ctf_pre_tool_hook
    from fulilian_ctf.sandbox import ENV_SANDBOX_MODE

    monkeypatch.setenv(ENV_SANDBOX_MODE, "read-only")
    directive = _ctf_pre_tool_hook(
        tool_name="terminal", args={"command": "touch pwned"}, cwd=str(tmp_path)
    )
    assert directive and "READ_ONLY" in directive["message"]


def test_inprocess_post_hook_context(monkeypatch, tmp_path):
    from fulilian_ctf.hooks import _ctf_post_tool_hook

    directive = _ctf_post_tool_hook(
        tool_name="terminal", result={"output": "done, flag{abc123def456}"}
    )
    assert directive and "flag{abc123def456}" in directive["context"]
    assert _ctf_post_tool_hook(tool_name="terminal", result={"output": "nothing"}) is None


def test_inprocess_post_hook_autocommits_only_in_ctf_mode(monkeypatch, tmp_path):
    from fulilian_ctf.hooks import _ctf_post_tool_hook

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FULILIAN_CTF_MODE", "1")
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)
    (tmp_path / "progress.txt").write_text("step 1", encoding="utf-8")
    _ctf_post_tool_hook(tool_name="terminal", result={"output": "ok"}, status="ok")
    commits = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert commits.stdout.strip() == "1"

    other = tmp_path / "other"
    other.mkdir()
    assert not (other / ".git").exists()


def test_git_auto_commit_rejects_path_outside_bound_workspace(monkeypatch, tmp_path):
    from tools.ctf_solve import _git_auto_commit_impl

    workspace = tmp_path / "challenge"
    outside = tmp_path / "outside"
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(workspace))
    message = _git_auto_commit_impl(str(outside), "should not commit")
    assert "outside" in message
    assert not (outside / ".git").exists()


class _FakeManager:
    def __init__(self):
        self._hooks = {}


def test_register_ctf_tool_hooks_idempotent(monkeypatch):
    import fulilian_ctf.hooks as hooks_mod

    manager = _FakeManager()
    monkeypatch.setattr(
        "fulilian_cli.plugins.get_plugin_manager", lambda: manager
    )
    registered = hooks_mod.register_ctf_tool_hooks()
    assert registered == ["pre_tool_call", "post_tool_call"]
    assert len(manager._hooks["pre_tool_call"]) == 1
    assert len(manager._hooks["post_tool_call"]) == 1
    # 再次注册：幂等
    assert hooks_mod.register_ctf_tool_hooks() == []
    assert len(manager._hooks["pre_tool_call"]) == 1


def test_register_skipped_in_safe_mode(monkeypatch):
    import fulilian_ctf.hooks as hooks_mod

    monkeypatch.setenv("FULILIAN_SAFE_MODE", "1")
    assert hooks_mod.register_ctf_tool_hooks() == []


def test_check_command_shared_logic(monkeypatch, tmp_path):
    from fulilian_ctf.hooks import check_command
    from fulilian_ctf.sandbox import ENV_SANDBOX_MODE

    blocked, msg = check_command("mkfs.ext4 /dev/sda1")
    assert blocked and "dangerous" in msg
    monkeypatch.delenv(ENV_SANDBOX_MODE, raising=False)
    blocked, msg = check_command("echo hi > /etc/evil", str(tmp_path))
    assert blocked and "outside workspace" in msg
    assert check_command("nmap -sV 10.0.0.5", str(tmp_path)) == (False, "")
