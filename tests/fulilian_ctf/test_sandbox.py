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


# ── 沙箱逃逸回归锁（P1）─────────────────────────────────────────────────────
# 四类绕过：带引号目标 / cd 后相对路径 / 指定目标目录的选项 / 管道与包装器。
# 每条都对应一个改动前会**放行**的实际命令。

@pytest.mark.parametrize("cmd, target", [
    ('echo pwned > "/etc/cron.d/evil"', "/etc/cron.d/evil"),
    ("echo pwned > '/etc/passwd'", "/etc/passwd"),
    ('cat x > "/tmp/leak"', "/tmp/leak"),
    ('echo x >> "./a" ; echo y > "/etc/y"', "/etc/y"),
])
def test_ww_blocks_quoted_redirect_target(tmp_path, cmd, target):
    """引号目标必须剥引号后再判定落点。

    旧实现用 `(\\S+)` 捕获目标，拿到的是含引号字符的 `"/etc/cron.d/evil"`；
    `Path()` 视为不含绝对路径前缀的相对路径，按工作区解析 → 放行。
    """
    allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert not allowed, f"escaped: {cmd}"
    assert target in reason


def test_ww_allows_quoted_redirect_inside(tmp_path):
    allowed, _ = enforce_sandbox(
        f'echo hi > "{tmp_path / "out.txt"}"', SandboxMode.WORKSPACE_WRITE, str(tmp_path)
    )
    assert allowed


@pytest.mark.parametrize("cmd", [
    "cd /tmp && echo x > evil",
    "cd /etc; echo x > passwd",
    "cd / && touch evil",
    "cd $UNRESOLVED && touch evil",     # cwd 不可静态确定 → 保守拒绝
    "cd - && touch evil",
    "cd .. && touch evil",              # 相对逃逸：解析后落在工作区外
    "mkdir /tmp/x && cd /tmp/x && echo y > z",
])
def test_ww_blocks_write_after_cd(tmp_path, cmd):
    """`cd` 改变相对路径的解析基准，后续相对写入必须按新 cwd 判定。

    旧实现把所有相对路径一律按 work_dir 解析，`cd /tmp && echo x > evil`
    于是被判定为「工作区内」而放行，实际写到 /tmp/evil。
    """
    allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert not allowed, f"escaped: {cmd}"
    assert "outside workspace" in reason


def test_ww_allows_cd_staying_inside(tmp_path):
    (tmp_path / "sub").mkdir()
    for cmd in ["cd sub && touch x", "cd sub && echo y > ../out.txt"]:
        allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
        assert allowed, f"{cmd} blocked: {reason}"


@pytest.mark.parametrize("cmd", [
    "cp -t /etc/cron.d evil",
    "cp --target-directory=/etc/cron.d evil",
    "cp --target-directory /etc/cron.d evil",
    "mv -t /etc evil",
    "install -T /etc/persistence evil",
    "cp ./evil -t /etc/cron.d",
])
def test_ww_blocks_target_directory_option(tmp_path, cmd):
    """`-t/--target-directory` 给的是写入落点，不是源。

    旧实现跳过一切 `-` 开头的 token，`cp -t /etc/cron.d evil` 的操作数只剩
    evil，被当作「源=evil、无目标」→ 取 operands[-1:] == ["evil"] 而放行。
    """
    allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert not allowed, f"escaped: {cmd}"
    assert "/etc" in reason


def test_ww_allows_target_directory_inside(tmp_path):
    (tmp_path / "sub").mkdir()
    for cmd in ["cp -t ./sub evil", "cp --target-directory=./sub evil",
                "cp ./evil -t ./sub"]:
        allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
        assert allowed, f"{cmd} blocked: {reason}"


@pytest.mark.parametrize("cmd", [
    "cat /etc/passwd | tee /tmp/leak",
    "cat a | tee -a /tmp/leak",
    "cat a | grep x | tee /tmp/leak",
    "echo x | dd of=/etc/magic",
    "echo x | cp /dev/stdin /etc/cron.d/y",
])
def test_ww_blocks_write_downstream_of_pipe(tmp_path, cmd):
    """管道下游的写命令同样要检查（旧实现只看首 token，`cat` 不是写命令→放行）。"""
    allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert not allowed, f"escaped: {cmd}"
    assert "outside workspace" in reason


@pytest.mark.parametrize("cmd", [
    "sudo cp ./evil /etc/cron.d/x",
    "env FOO=1 touch /etc/persistence",
    "nohup cp ./evil /etc/evil",
    "sudo -n dd if=/dev/zero of=/etc/magic",
])
def test_ww_unwraps_prefix_commands(tmp_path, cmd):
    """`sudo`/`env`/`nohup` 等透明前缀后的命令才是真正要执行的命令。"""
    allowed, reason = enforce_sandbox(cmd, SandboxMode.WORKSPACE_WRITE, str(tmp_path))
    assert not allowed, f"escaped: {cmd}"
    assert "outside workspace" in reason


@pytest.mark.parametrize("cmd", [
    "cat x | tee /tmp/leak",
    "cat x | grep -v y | tee /tmp/leak",
    "sudo rm -rf /var/lib",
    "sudo touch /etc/persistence",
    "nohup touch /tmp/marker",
    "sh -c 'touch /tmp/marker'",
    "bash -c \"mkdir /tmp/dir\"",
    "/usr/bin/rm -rf /tmp/x",
])
def test_read_only_blocks_write_behind_wrapper_or_pipe(cmd):
    """READ_ONLY 只看首 token 时，管道/包装器后的写命令全部绕过。"""
    allowed, reason = enforce_sandbox(cmd, SandboxMode.READ_ONLY, "/tmp/w")
    assert not allowed, f"escaped: {cmd}"
    assert "READ_ONLY" in reason


def test_read_only_still_allows_recon_pipelines():
    for cmd in ["cat /etc/passwd | grep root", "nmap -sV 10.0.0.5 | head -20",
                "ls -la | sort", "curl -s http://t/ | grep flag"]:
        allowed, reason = enforce_sandbox(cmd, SandboxMode.READ_ONLY, "/tmp/w")
        assert allowed, f"{cmd} blocked: {reason}"


@pytest.mark.parametrize("cmd", [
    "echo x > out.txt ; echo y > '/etc/y",
    'echo "unterminated',
])
def test_unbalanced_quotes_fail_closed(tmp_path, cmd):
    """引号不配对时无法可靠切分 → 一律拒绝，不猜。"""
    for mode in (SandboxMode.READ_ONLY, SandboxMode.WORKSPACE_WRITE):
        allowed, reason = enforce_sandbox(cmd, mode, str(tmp_path))
        assert not allowed, f"escaped: {cmd} in {mode}"
        assert "quotes" in reason
