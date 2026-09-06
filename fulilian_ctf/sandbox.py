"""三档沙箱模式（F4-004）。

与 hooks（F4-003）集成：``fulilian_ctf/hooks/check_dangerous.py`` 在
pre_tool_call 阶段读取环境变量 ``FULILIAN_SANDBOX_MODE``（或 config），
对 terminal 命令调用 :func:`enforce_sandbox` 拦截。

三档语义：
- READ_ONLY（0）：只读侦察——禁止任何写入类命令
- WORKSPACE_WRITE（1）：只允许写题目工作区——重定向到工作区外被拦截
- DANGER_FULL（2）：全访问——危险命令交由 Fulilian approval 机制审批
"""

from __future__ import annotations

import os
import re
import shlex
from enum import IntEnum
from pathlib import Path
from typing import Optional, Tuple

ENV_SANDBOX_MODE = "FULILIAN_SANDBOX_MODE"

# READ_ONLY 模式下禁止的写入命令（按词匹配首词；> / >> 重定向另有检查覆盖）。
# 注意保持克制：curl/nc/nmap 等只读侦察工具不在名单里（curl -o 落盘由
# 重定向/调用方约束，避免误伤 RECON 阶段）。
READ_ONLY_WRITE_COMMANDS = {
    "touch", "mkdir", "mv", "cp", "rm", "rmdir", "chmod", "chown",
    "ln", "dd", "tee", "truncate", "shred", "mkfs", "install",
}

# 重定向目标放行的特殊设备（不算工作区外写入）
_SAFE_REDIRECT_TARGETS = {"/dev/null", "/dev/stderr", "/dev/stdout", "/dev/zero"}

_REDIRECT_RE = re.compile(r"(>>?|&>>?|2>>?|1>>?)\s*(\S+)")

# WORKSPACE_WRITE 档需要检查"写入目标路径"的写类命令（P1 修复）。
# 旧实现只查重定向，该档可用 `cp x /etc/cron.d/evil`、`dd of=/etc/...`
# 等无重定向形态把文件写到工作区外。规则：READ_ONLY_WRITE_COMMANDS
# 中除 rm（只删不写）与 tee（已有专项检查）外全部纳入。
_WRITE_TARGET_COMMANDS = READ_ONLY_WRITE_COMMANDS - {"rm", "tee"}

# 多命令拼接符：写命令的操作数扫描到拼接符即止（后面是另一条命令）
_SHELL_JOINERS = {"|", ";", "&&", "||", "&"}


class SandboxMode(IntEnum):
    """三档沙箱模式。"""

    READ_ONLY = 0           # 只读侦察
    WORKSPACE_WRITE = 1     # 写工作区
    DANGER_FULL = 2         # 全访问（需审批）

    @classmethod
    def for_phase(cls, phase: str) -> "SandboxMode":
        """CTF 四阶段 → 沙箱档位（RECON 只读 / EXECUTE 写工作区 / EXPLOIT 需审批）。"""
        return {
            "RECON": cls.READ_ONLY,
            "EXECUTE": cls.WORKSPACE_WRITE,
            "EXPLOIT": cls.DANGER_FULL,
        }.get(str(phase).upper(), cls.WORKSPACE_WRITE)

    @classmethod
    def from_name(cls, name: str) -> "SandboxMode":
        """从名称或数字解析（'read-only' / '0' / 'READ_ONLY'）。"""
        normalized = str(name).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "read_only": cls.READ_ONLY, "ro": cls.READ_ONLY, "0": cls.READ_ONLY,
            "workspace_write": cls.WORKSPACE_WRITE, "workspace": cls.WORKSPACE_WRITE,
            "ww": cls.WORKSPACE_WRITE, "1": cls.WORKSPACE_WRITE,
            "danger_full": cls.DANGER_FULL, "full": cls.DANGER_FULL,
            "danger": cls.DANGER_FULL, "2": cls.DANGER_FULL,
        }
        if normalized not in aliases:
            raise ValueError(f"unknown sandbox mode: {name!r}")
        return aliases[normalized]


def current_mode(default: SandboxMode = SandboxMode.WORKSPACE_WRITE) -> SandboxMode:
    """从环境变量解析当前沙箱档位；未设置/非法时用默认档。"""
    raw = os.environ.get(ENV_SANDBOX_MODE, "").strip()
    if not raw:
        return default
    try:
        return SandboxMode.from_name(raw)
    except ValueError:
        return default


def _resolve_within(cmd_path: str, work_dir: Path) -> bool:
    """判断重定向目标是否落在工作区内（相对路径按 work_dir 解析）。"""
    try:
        p = Path(cmd_path)
        if not p.is_absolute():
            p = work_dir / p
        resolved = p.resolve()
        # /dev/null 等特殊设备放行
        if str(resolved) in _SAFE_REDIRECT_TARGETS or str(p) in _SAFE_REDIRECT_TARGETS:
            return True
        resolved.relative_to(work_dir.resolve())
        return True
    except (OSError, ValueError):
        return False


def _write_targets(tokens: list, start: int) -> list:
    """提取写命令的"写入目标"操作数（供 WORKSPACE_WRITE 档检查）。

    目标位置按命令语义区分（读取源允许在工作区外，只有写入落点受限）：
    - dd：仅 ``of=`` 参数（``if=`` 是读取源）；
    - cp/mv/install/ln：最后一个非 flag 操作数（写入落点，其余是源）；
    - chmod/chown：跳过第一个非 flag 操作数（mode/owner，非路径）；
    - touch/mkdir/rmdir/truncate/shred/mkfs：全部非 flag 操作数。
    """
    cmd = Path(tokens[start]).name
    operands = []
    for tok in tokens[start + 1:]:
        if tok in _SHELL_JOINERS:
            break
        if tok.startswith("-") or tok == "--":
            continue
        operands.append(tok)
    if cmd == "dd":
        return [t[3:] for t in operands if t.startswith("of=")]
    if cmd in ("chmod", "chown"):
        return operands[1:]
    if cmd in ("cp", "mv", "install", "ln"):
        return operands[-1:]
    return operands


def _check_workspace_write(command: str, work_dir: Path) -> Tuple[bool, str]:
    """WORKSPACE_WRITE：拦截把输出/数据写到工作区外的命令。"""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for match in _REDIRECT_RE.finditer(command):
        target = match.group(2)
        if target in _SAFE_REDIRECT_TARGETS:
            continue
        if not _resolve_within(target, work_dir):
            return False, f"WORKSPACE_WRITE: writing outside workspace blocked ({target})"
    # tee 到工作区外（含管道形态 `... | tee FILE`）：tee 之后的非 flag 参数都是目标
    for i, tok in enumerate(tokens):
        if Path(tok).name == "tee":
            for target in tokens[i + 1:]:
                if target.startswith("-") or target == "--":
                    continue
                if not _resolve_within(target, work_dir):
                    return False, f"WORKSPACE_WRITE: writing outside workspace blocked ({target})"
    # 写类命令的目标路径检查（P1 修复）：无重定向落盘形态
    # （cp/mv/install/dd of=/touch/...）同样只允许写工作区内
    for i, tok in enumerate(tokens):
        if tok in _SHELL_JOINERS:
            continue
        if Path(tok).name in _WRITE_TARGET_COMMANDS:
            for target in _write_targets(tokens, i):
                if not _resolve_within(target, work_dir):
                    return False, f"WORKSPACE_WRITE: writing outside workspace blocked ({target})"
    return True, ""


def enforce_sandbox(
    command: str,
    mode: SandboxMode,
    work_dir: str = ".",
) -> Tuple[bool, str]:
    """执行沙箱检查。

    Args:
        command: 要执行的命令
        mode: 当前沙箱模式
        work_dir: 工作区目录

    Returns:
        (allowed, reason)——allowed=False 时 reason 说明拦截原因
    """
    if mode == SandboxMode.DANGER_FULL:
        # 全访问：危险命令交由 Fulilian approval / hardline 机制处理
        return True, ""

    if mode == SandboxMode.READ_ONLY:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if not tokens:
            return True, ""
        if Path(tokens[0]).name in READ_ONLY_WRITE_COMMANDS or tokens[0] in READ_ONLY_WRITE_COMMANDS:
            return False, (
                f"READ_ONLY mode: write command blocked ({tokens[0]}) — "
                "upgrade sandbox to WRITE (FULILIAN_SANDBOX_MODE=workspace-write) to run this"
            )
        # 重定向写入也算写
        if _REDIRECT_RE.search(command):
            return False, "READ_ONLY mode: output redirection blocked"
        return True, ""

    # WORKSPACE_WRITE
    wd = Path(work_dir) if work_dir else Path(".")
    if not wd.is_absolute():
        wd = Path.cwd() / wd
    return _check_workspace_write(command, wd)


__all__ = [
    "ENV_SANDBOX_MODE",
    "READ_ONLY_WRITE_COMMANDS",
    "SandboxMode",
    "current_mode",
    "enforce_sandbox",
]
