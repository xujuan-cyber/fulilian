"""三档沙箱模式 (F4-004) 单元测试。"""

from __future__ import annotations

import pytest

from fulilian_ctf.sandbox import (
    ENV_SANDBOX_MODE,
    SandboxMode,
    current_mode,
    enforce_sandbox,
)


# ── SandboxMode 解析 ────────────────────────────────────────────────────────

def test_for_phase_mapping():
    assert SandboxMode.for_phase("RECON") == SandboxMode.READ_ONLY
    assert SandboxMode.for_phase("EXECUTE") == SandboxMode.WORKSPACE_WRITE
    assert SandboxMode.for_phase("EXPLOIT") == SandboxMode.DANGER_FULL
    assert SandboxMode.for_phase("unknown") == SandboxMode.WORKSPACE_WRITE


def test_from_name_aliases():
    assert SandboxMode.from_name("read-only") == SandboxMode.READ_ONLY
    assert SandboxMode.from_name("0") == SandboxMode.READ_ONLY
    assert SandboxMode.from_name("WORKSPACE") == SandboxMode.WORKSPACE_WRITE
    assert SandboxMode.from_name("danger full") == SandboxMode.DANGER_FULL
    with pytest.raises(ValueError):
        SandboxMode.from_name("bogus")


def test_current_mode_env(monkeypatch):
    monkeypatch.delenv(ENV_SANDBOX_MODE, raising=False)
    assert current_mode() == SandboxMode.WORKSPACE_WRITE  # 默认档
    monkeypatch.setenv(ENV_SANDBOX_MODE, "read-only")
    assert current_mode() == SandboxMode.READ_ONLY
    monkeypatch.setenv(ENV_SANDBOX_MODE, "bogus")
    assert current_mode() == SandboxMode.WORKSPACE_WRITE  # 非法值回默认


# ── READ_ONLY ───────────────────────────────────────────────────────────────

def test_read_only_blocks_write_commands():
    allowed, reason = enforce_sandbox("rm -rf ./build", SandboxMode.READ_ONLY, "/tmp/w")
    assert not allowed and "READ_ONLY" in reason
    allowed, _ = enforce_sandbox("mkdir exfil", SandboxMode.READ_ONLY, "/tmp/w")
    assert not allowed
    allowed, _ = enforce_sandbox("touch note.txt", SandboxMode.READ_ONLY, "/tmp/w")
    assert not allowed


def test_read_only_blocks_redirection():
    allowed, reason = enforce_sandbox("ls > out.txt", SandboxMode.READ_ONLY, "/tmp/w")
    assert not allowed and "READ_ONLY" in reason


def test_read_only_allows_recon():
    allowed, _ = enforce_sandbox("nmap -sV 10.0.0.5", SandboxMode.READ_ONLY, "/tmp/w")
    assert allowed
    allowed, _ = enforce_sandbox("curl -s http://target/", SandboxMode.READ_ONLY, "/tmp/w")
    assert allowed
    allowed, _ = enforce_sandbox("cat /etc/passwd", SandboxMode.READ_ONLY, "/tmp/w")
    assert allowed


# ── WORKSPACE_WRITE ─────────────────────────────────────────────────────────

def test_workspace_write_allows_inside(tmp_path):
    allowed, _ = enforce_sandbox(
        f"echo hi > {tmp_path / 'out.txt'}", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert allowed
    allowed, _ = enforce_sandbox("echo hi > out.txt", SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert allowed  # 相对路径按工作区解析
    allowed, _ = enforce_sandbox("echo hi >> /dev/null", SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert allowed  # /dev/null 放行


def test_workspace_write_blocks_outside(tmp_path):
    allowed, reason = enforce_sandbox(
        "echo hi > /etc/evil", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert not allowed and "outside workspace" in reason
    allowed, _ = enforce_sandbox(
        "echo hi >> /tmp/other/out.txt", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert not allowed
    allowed, _ = enforce_sandbox(
        f"cat /etc/passwd | tee /tmp/leak", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert not allowed


def test_workspace_write_allows_non_write_commands(tmp_path):
    allowed, _ = enforce_sandbox("nmap -sV 10.0.0.5", SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert allowed


# ── DANGER_FULL ─────────────────────────────────────────────────────────────

def test_danger_full_allows_but_approval_layer_remains(tmp_path):
    allowed, _ = enforce_sandbox("rm -rf /some/dir", SandboxMode.DANGER_FULL, str(tmp_path))
    assert allowed  # 沙箱放行，危险命令由 hooks 危险检查表 / approval 审批兜底


# ── WORKSPACE_WRITE：写类命令目标路径检查（P1 修复）────────────────────────

def test_ww_blocks_cp_to_outside(tmp_path):
    allowed, reason = enforce_sandbox(
        "cp ./evil /etc/cron.d/backdoor", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert not allowed and "/etc/cron.d/backdoor" in reason


def test_ww_allows_cp_source_outside(tmp_path):
    # 读取源在工作区外是合法侦察动作（字典/词表拷入工作区），不得误伤
    allowed, _ = enforce_sandbox(
        "cp /usr/share/wordlists/rockyou.txt .", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert allowed


def test_ww_blocks_dd_of_outside(tmp_path):
    allowed, reason = enforce_sandbox(
        "dd if=/dev/zero of=/etc/magic bs=1M count=1",
        SandboxMode.WORKSPACE_WRITE, str(tmp_path),
    )
    assert not allowed and "/etc/magic" in reason


def test_ww_allows_dd_of_inside(tmp_path):
    allowed, _ = enforce_sandbox(
        "dd if=/dev/zero of=./blob bs=1M count=1", SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert allowed


def test_ww_blocks_mv_install_touch_chmod_outside(tmp_path):
    for cmd, target in [
        ("mv ./x /etc/passwd-writable", "/etc/passwd-writable"),
        ("install -m 644 ./a /etc/persistence", "/etc/persistence"),
        ("touch /tmp/outside-marker", "/tmp/outside-marker"),
        ("chmod 755 /etc/unsafe", "/etc/unsafe"),
        ("truncate -s 0 /var/log/audit.log", "/var/log/audit.log"),
    ]:
        allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
        assert not allowed, f"{cmd} should be blocked"
        assert target in reason


def test_ww_blocks_write_command_in_chained_line(tmp_path):
    allowed, _ = enforce_sandbox(
        "cat /etc/passwd > ./notes.txt && cp ./notes.txt /etc/cron.d/x",
        SandboxMode.WORKSPACE_WRITE, str(tmp_path),
    )
    assert not allowed


def test_ww_allows_write_commands_inside(tmp_path):
    for cmd in ["touch ./a", "mkdir ./d", "mv ./a ./b", "chmod 755 ./b"]:
        allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
        assert allowed, f"{cmd} blocked: {reason}"
