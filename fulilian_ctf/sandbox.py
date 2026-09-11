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

# 重定向操作符 + 目标。目标可以是带引号串（**必须**识别，否则
# `> "/etc/passwd"` 会被当作相对路径 "/etc/passwd"（含引号字符）而放行）。
# 裸词分支排除引号/拼接符/重定向符，避免吃掉后续命令。
# 不含 `2>&1` 这类 fd 复制：其目标不是文件，捕获分支开头的 `&` 已被排除。
_REDIRECT_RE = re.compile(
    r"""(?:\d?>>|&>>|\d?>|&>|>\|)\s*"""
    r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s;|&<>()]+)"""
)

# 未加引号的拼接符——简单命令的分隔点（`|` `;` `&` 与换行）
_JOINER_CHARS = set(";|&\n")

# 透明前缀命令：真正要执行的命令在其参数之后。不剥掉的话
# `sudo rm -rf /` 的「命令名」会被当成 sudo 而放行。
_WRAPPER_COMMANDS = {
    "sudo", "doas", "env", "nohup", "time", "command", "builtin", "exec",
}
_ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")

# 指定「目标目录」的选项：其后（或 `=` 后）的操作数是**写入落点**而非源。
# 不识别的话 `cp -t /etc/cron.d evil` 会被读成「源=evil，只有一个操作数」
# 而拿到 `operands[-1:] == ["evil"]` → 放行。
_TARGET_DIR_LONG = "--target-directory"
_TARGET_DIR_OPTS = {"-t", "-T", _TARGET_DIR_LONG}

# 内层命令：`sh -c "<cmd>"` 把真正的命令藏在引号参数里，只看外层命令名
# 会漏掉（`sh` / `bash` 都不在写命令名单里）。递归解析其 `-c` 参数。
_SHELL_COMMANDS = {"sh", "bash", "dash", "zsh", "ksh", "ash"}
_MAX_NESTING = 4  # 递归深度上限（`sh -c "sh -c ..."` 防止无限递归）

# WORKSPACE_WRITE 档需要检查"写入目标路径"的写类命令。
# 规则：READ_ONLY_WRITE_COMMANDS 中除 rm 外全部纳入。
# 已知边界（有意保留）：rm 只删不写，其操作数不进本检查——即
# WORKSPACE_WRITE 下 `rm -rf /tmp/x` 不会被拦（删除的落点不受工作区约束），
# 与改动前语义一致；确需收紧时把 "rm" 从下面的差集里去掉即可。
_WRITE_TARGET_COMMANDS = READ_ONLY_WRITE_COMMANDS - {"rm"}


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


def _unquote(token: str) -> str:
    """剥掉最外层成对引号并解转义（`"/etc/x"` → `/etc/x`）。"""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        inner = token[1:-1]
        if token[0] == '"':
            inner = re.sub(r"\\(.)", r"\1", inner)
        return inner
    return token


def _split_segments(command: str) -> Tuple[list, bool]:
    """按**未加引号**的拼接符切分成简单命令。

    Returns:
        (segments, unterminated_quote)：引号不配对时第二项为 True，调用方
        应保守拒绝——切不准的输入无法判定写入落点。
    """
    segments: list = []
    buf: list = []
    quote = ""
    escaped = False
    for ch in command:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            elif ch == "\\" and quote == '"':
                escaped = True
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == "\\":
            buf.append(ch)
            escaped = True
            continue
        if ch in _JOINER_CHARS:
            segments.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()], bool(quote)


def _tokens(segment: str) -> list:
    """简单命令 → token 列表（已剥引号）。引号不配对时退回朴素切分。"""
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return re.sub(r"""["'\\]""", "", segment).split()


def _unwrap(tokens: list) -> list:
    """剥掉透明前缀命令，返回真正要执行的命令及其参数。"""
    idx = 0
    while idx < len(tokens):
        if Path(tokens[idx]).name not in _WRAPPER_COMMANDS:
            break
        idx += 1
        # 包装器自身的参数：-flag，或 env 的 VAR=VAL
        while idx < len(tokens) and (
            tokens[idx].startswith("-") or _ENV_ASSIGN_RE.fullmatch(tokens[idx])
        ):
            idx += 1
    return tokens[idx:]


def _shell_c_argument(tokens: list) -> Optional[str]:
    """取 ``sh -c "<cmd>"`` 形态的内层命令串；非该形态返回 None。

    兼容组合短选项（``-lc``、``-xc``）与 ``--`` 终止符：只要某个短选项簇里
    含 ``c``，紧随其后的操作数就是内层命令。
    """
    if not tokens or Path(tokens[0]).name not in _SHELL_COMMANDS:
        return None
    rest = tokens[1:]
    for i, tok in enumerate(rest):
        if tok == "--":
            continue
        if tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:]:
            if i + 1 < len(rest):
                return rest[i + 1]
    return None


def _resolve_within(cmd_path: str, base: Path, root: Path) -> bool:
    """判断写入目标是否落在工作区**根**内。

    ``base`` 是解析相对路径的基准目录（可能被 ``cd`` 改变），``root`` 是工作区
    根。两者必须分开：`cd sub && echo x > ../evil` 的相对路径要按 sub 解析，
    但落点仍必须落在 root 之内。base 为 None 表示 cwd 已不可静态确定 → 保守拒绝。
    """
    if base is None:
        return False
    raw = _unquote(cmd_path)
    if not raw:
        return False
    if raw in _SAFE_REDIRECT_TARGETS:
        return True
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = base / p
        resolved = p.resolve()
        # /dev/null 等特殊设备放行
        if str(resolved) in _SAFE_REDIRECT_TARGETS:
            return True
        resolved.relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _write_targets(tokens: list) -> list:
    """提取写命令的"写入目标"操作数（``tokens`` 含命令名）。

    目标位置按命令语义区分（读取源允许在工作区外，只有写入落点受限）：
    - dd：仅 ``of=``（``if=`` 是读取源），兼容 ``of FILE`` 分离写法；
    - cp/mv/install/ln：``-t``/``-T``/``--target-directory`` 给的是目标目录；
      否则最后一个非 flag 操作数（其余是源）；
    - chmod/chown：跳过第一个非 flag 操作数（mode/owner，非路径）；
    - touch/mkdir/rmdir/truncate/shred/mkfs/tee：全部非 flag 操作数。
    """
    cmd = Path(tokens[0]).name
    operands: list = []
    explicit: list = []
    rest = tokens[1:]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in _TARGET_DIR_OPTS:
            if i + 1 < len(rest):
                explicit.append(rest[i + 1])
            i += 2
            continue
        if tok.startswith(_TARGET_DIR_LONG + "="):
            explicit.append(tok.split("=", 1)[1])
            i += 1
            continue
        if tok.startswith("-") or tok == "--":
            i += 1
            continue
        operands.append(tok)
        i += 1
    if cmd == "dd":
        out = [t[3:] for t in operands if t.startswith("of=")]
        out += [
            operands[k + 1]
            for k, t in enumerate(operands)
            if t == "of" and k + 1 < len(operands)
        ]
        return out + explicit
    if cmd in ("chmod", "chown"):
        return operands[1:] + explicit
    if cmd in ("cp", "mv", "install", "ln"):
        return explicit or operands[-1:]
    return operands + explicit


def _blocked(target: str) -> Tuple[bool, str]:
    return False, f"WORKSPACE_WRITE: writing outside workspace blocked ({target})"


def _check_workspace_write(command: str, work_dir: Path) -> Tuple[bool, str]:
    """WORKSPACE_WRITE：拦截把输出/数据写到工作区外的命令。

    逐条简单命令检查（而非只看整串的首 token），因此管道/`sudo`/`cd`
    等形态都在覆盖范围内：

    - 重定向目标逐段抽取，带引号的目标先剥引号再解析（`> "/etc/x"` 不能
      因为引号字符留在路径里而被当成工作区内相对路径）；
    - 写类命令（cp/mv/install/dd of=/touch/...）的操作数里只放行工作区内的
      写入落点，读取源允许在工作区外；
    - ``cd`` 会改变后续相对路径的解析基准，按静态可知的目标跟踪；目标
      不可静态确定（``cd $X`` / ``cd -`` / 通配符）时基准置空 → 之后任何
      相对写入一律拒绝；
    - ``sh -c "<cmd>"`` 的内层命令串递归检查（内层相对路径沿用同一 base）。
    """
    root = work_dir.resolve()
    return _check_ww_segments(command, root, root, 0)


def _check_ww_segments(
    command: str, root: Path, base: Optional[Path], depth: int
) -> Tuple[bool, str]:
    """``_check_workspace_write`` 的递归主体（base 随 ``cd`` 变化）。"""
    segments, unterminated = _split_segments(command)
    if unterminated:
        return False, "WORKSPACE_WRITE: unbalanced quotes — cannot verify write targets"
    for seg in segments:
        # 重定向：逐段抽取，目标按其所属段的 cwd 解析
        for match in _REDIRECT_RE.finditer(seg):
            target = match.group(1)
            if _unquote(target) in _SAFE_REDIRECT_TARGETS:
                continue
            if not _resolve_within(target, base, root):
                return _blocked(target)
        head = _unwrap(_tokens(seg))
        if not head:
            continue
        cmd = Path(head[0]).name
        if cmd == "cd":
            target = head[1] if len(head) > 1 else ""
            base = _cd_base(target, base)
            continue
        if cmd in _WRITE_TARGET_COMMANDS:
            for target in _write_targets(head):
                if not _resolve_within(target, base, root):
                    return _blocked(target)
        inner = _shell_c_argument(head) if depth < _MAX_NESTING else None
        if inner:
            ok, reason = _check_ww_segments(inner, root, base, depth + 1)
            if not ok:
                return ok, reason
    return True, ""


def _cd_base(target: str, base: Optional[Path]) -> Optional[Path]:
    """``cd`` 之后新的相对路径解析基准；不可静态确定时返回 None。"""
    raw = _unquote(target)
    # 空 / 选项（`cd -` 是上一个目录，`cd -P`） / 变量 / 命令替换 / 通配符 /
    # `~` 展开都算不可确定
    if not raw or raw.startswith("-") or any(ch in raw for ch in "$`*?[~{"):
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    return base / p if base is not None else None


def _check_read_only(command: str, depth: int = 0) -> Tuple[bool, str]:
    """READ_ONLY：禁止任何写入类命令与输出重定向。

    逐条简单命令检查命令名，而不是只看整串首 token：否则
    ``cat x | tee /tmp/leak``、``sudo rm -rf /``、``sh -c "touch /tmp/y"``
    这些把写命令放在管道/包装器/内层 shell 后面的形态全部绕过（首 token
    是 cat/sudo/sh，都不在写命令名单里）。管道下游与内层命令同样是「要执行
    的命令」，必须一并登记。
    """
    segments, unterminated = _split_segments(command)
    if unterminated:
        return False, "READ_ONLY mode: unbalanced quotes — cannot verify command"
    for seg in segments:
        head = _unwrap(_tokens(seg))
        if not head:
            continue
        if Path(head[0]).name in READ_ONLY_WRITE_COMMANDS:
            return False, (
                f"READ_ONLY mode: write command blocked ({head[0]}) — "
                "upgrade sandbox to WRITE (FULILIAN_SANDBOX_MODE=workspace-write) to run this"
            )
        inner = _shell_c_argument(head) if depth < _MAX_NESTING else None
        if inner:
            ok, reason = _check_read_only(inner, depth + 1)
            if not ok:
                return ok, reason
    # 重定向写入也算写（含 `> ` 与带引号目标；此处一律拒绝，不看落点）
    if _REDIRECT_RE.search(command):
        return False, "READ_ONLY mode: output redirection blocked"
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
        return _check_read_only(command)

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
