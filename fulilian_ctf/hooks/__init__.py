"""FuLiLian CTF tool-call hooks（F4-003 / F4-004）。

**进程内注册**（:func:`register_ctf_tool_hooks`）：CTF 求解路径调用后，
pre/post_tool_call 钩子直接挂到 plugin manager 上，与
``agent/shell_hooks.register_from_config`` 内部同一挂载点，复用上游
pre_tool_call 的 block 语义（``{"action": "block", "message": ...}``）与
post_tool_call 的 ``{"context": ...}`` 上下文注入。

不写 ~/.fulilian 的任何文件：不走 shell-hook 的 consent/allowlist 通道
（那条路即使 accept_hooks=True 也会往用户 Fulilian home 写白名单），
改动范围自包含在 FuLiLian 项目内。

同时提供独立可执行的脚本（``check_dangerous.py`` / ``detect_flag.py``），
遵循 agent/shell_hooks.py 的 stdin/stdout wire 协议，供用户在自己的
config.yaml 手动注册（脚本不自动落任何配置）。

脚本内部错误一律 fail-open（放行），避免断题。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 独立脚本场景（hook 子进程 cwd 是题目工作目录）：把项目根加入 sys.path
if __package__ in (None, ""):  # pragma: no cover — 直接以脚本运行时
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ── 检查逻辑（进程内回调与脚本共用） ─────────────────────────────────────────

def check_command(command: str, work_dir: str = ".") -> tuple:
    """纯函数检查：返回 (blocked, message)。

    危险模式 → 拦截；随后按沙箱档位调用 enforce_sandbox。
    """
    from fulilian_ctf.sandbox import SandboxMode, current_mode, enforce_sandbox
    from fulilian_ctf.hooks.dangerous_patterns import DANGEROUS_PATTERNS_COMPILED

    for label, rx in DANGEROUS_PATTERNS_COMPILED:
        if rx.search(command):
            return True, f"CTF dangerous command blocked: {label}"

    mode = current_mode(default=SandboxMode.WORKSPACE_WRITE)
    allowed, reason = enforce_sandbox(command, mode, work_dir or ".")
    if not allowed:
        return True, reason
    return False, ""


# ── 进程内回调 ───────────────────────────────────────────────────────────────

def _ctf_pre_tool_hook(*, tool_name=None, args=None, **_kw):
    """pre_tool_call 回调：terminal 命令危险检查 + 沙箱（F4-003/F4-004）。"""
    if tool_name != "terminal":
        return None
    command = ""
    if isinstance(args, str):
        command = args
    elif isinstance(args, dict):
        command = str(args.get("command", "") or "")
    if not command:
        return None
    try:
        blocked, message = check_command(command, os.getcwd())
    except Exception:  # noqa: BLE001 — 检查失败不阻断工具调用（fail-open）
        return None
    if blocked:
        return {"action": "block", "message": message}
    return None


def _ctf_post_tool_hook(*, tool_name=None, result=None, **_kw):
    """post_tool_call 回调：工具输出中的 flag 候选检测（声明式提交提示）。"""
    if tool_name != "terminal":
        return None
    text = _extract_result_text(result)
    if not text:
        return None
    try:
        from fulilian_ctf.verify import extract_flag_candidates

        candidates = extract_flag_candidates(text)[:3]
    except Exception:  # noqa: BLE001 — 检测失败不出声
        return None
    if candidates:
        listed = ", ".join(c[:80] for c in candidates)
        return {
            "context": (
                f"[flag-candidate] Detected flag-shaped token(s): {listed}. "
                "If this is the flag, write it to the FLAG file in the challenge "
                "directory (declarative submission) and verify it with verify_flag."
            )
        }
    return None


def _extract_result_text(result) -> str:
    """从 post_tool_call 的 result 提取输出文本。"""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("output", "stdout", "content", "text"):
            value = result.get(key)
            if isinstance(value, str):
                return value
        try:
            return json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(result)
    return ""


def register_ctf_tool_hooks() -> list:
    """把 CTF pre/post_tool_call 钩子注册到当前进程的 plugin manager。

    - 幂等（同一回调对象只挂一次）
    - 不写任何用户配置/白名单文件
    - FULILIAN_SAFE_MODE=1 时跳过（与 shell-hook 注册语义一致）

    Returns:
        实际注册的事件名列表（如 ["pre_tool_call", "post_tool_call"]）。
    """
    from utils import env_var_enabled

    if env_var_enabled("FULILIAN_SAFE_MODE"):
        return []

    from fulilian_cli.plugins import get_plugin_manager

    manager = get_plugin_manager()
    registered = []
    for event, callback in (
        ("pre_tool_call", _ctf_pre_tool_hook),
        ("post_tool_call", _ctf_post_tool_hook),
    ):
        hooks = manager._hooks.setdefault(event, [])
        if callback not in hooks:
            hooks.append(callback)
            registered.append(event)
    return registered


__all__ = [
    "check_command",
    "register_ctf_tool_hooks",
]
