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

另含进程内 hook ``kb_nudge._kb_nudge_post_tool_hook``（仅随
:func:`register_ctf_tool_hooks` 注册，无独立脚本）：单题求解超过阈值
（默认 600 秒）后一次性检索 Des-CTF-Knowledge，把历史思路作为
``{"context": ...}`` 注入运行中的解题会话（详见 kb_nudge.py 模块文档）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 独立脚本场景（hook 子进程 cwd 是题目工作目录）：把项目根加入 sys.path
if __package__ in (None, ""):  # pragma: no cover — 直接以脚本运行时
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# kb_nudge 顶层仅依赖 stdlib，模块级导入无循环风险（knowledge_retriever
# 等重依赖在函数内延迟 import）；导出模块属性供测试与注册方引用
from fulilian_ctf.hooks.kb_nudge import _kb_nudge_post_tool_hook


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

# P0-2 loop-guard：warn 级提示经 post_tool_call 注入（pre 只能 block），
# 这里暂存待注入消息（进程内单条即可，重复 warn 以最新为准）
_LOOP_WARN_PENDING: dict = {}


def _check_loop(tool_name, args):
    """P0-2 loop-guard（所有工具）。返回 None | ("block", msg) | ("warn", msg)。

    fail-open：检查自身异常时放行，避免断题。
    FULILIAN_LOOP_GUARD=0 时 LoopDetector.check 恒返回 None。
    """
    try:
        from fulilian_ctf.loop_guard import BREAK, WARN, default_detector

        verdict = default_detector().check(tool_name, args)
        if verdict == BREAK:
            return ("block", default_detector().describe(tool_name, args))
        if verdict == WARN:
            return (
                "warn",
                "[loop-guard] This exact call has repeated 3+ times recently; "
                "the next identical call will be BLOCKED. Change approach now: "
                "different tool or materially different arguments.",
            )
    except Exception:  # noqa: BLE001 — fail-open
        return None
    return None


def _ctf_pre_tool_hook(*, tool_name=None, args=None, **_kw):
    """pre_tool_call 回调：loop-guard（所有工具）+ terminal 危险命令检查 + 沙箱。"""
    loop = _check_loop(tool_name, args)
    if loop is not None and loop[0] == "block":
        _LOOP_WARN_PENDING.pop("msg", None)
        return {"action": "block", "message": loop[1]}
    if tool_name == "terminal":
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
    if loop is not None and loop[0] == "warn":
        _LOOP_WARN_PENDING["msg"] = loop[1]
    return None


def _ctf_post_tool_hook(*, tool_name=None, result=None, **_kw):
    """post_tool_call 回调：loop-guard warn 提示 + 工具输出 flag 候选检测。"""
    if tool_name != "terminal":
        return None
    # F1-007: checkpoint every successful terminal step. The helper is bound
    # to the solver's current cwd and never accepts a model-supplied path.
    try:
        status = str(_kw.get("status") or "ok").lower()
        if (
            os.environ.get("FULILIAN_CTF_MODE") == "1"
            and status == "ok"
            and os.environ.get("FULILIAN_CTF_AUTOCOMMIT", "1") != "0"
        ):
            from tools.ctf_solve import _git_auto_commit_impl
            _git_auto_commit_impl(os.getcwd(), "ctf: auto checkpoint after terminal step")
    except Exception:  # noqa: BLE001 — checkpoint failure must not stop solving
        pass
    parts = []
    # P0-2：pre 阶段判为 warn 的提示在这里注入（post 支持 context 注入）
    loop_msg = _LOOP_WARN_PENDING.pop("msg", None)
    if loop_msg:
        parts.append(loop_msg)
    text = _extract_result_text(result)
    if text:
        try:
            from fulilian_ctf.verify import extract_flag_candidates

            candidates = extract_flag_candidates(text)[:3]
        except Exception:  # noqa: BLE001 — 检测失败不出声
            candidates = []
        if candidates:
            listed = ", ".join(c[:80] for c in candidates)
            parts.append(
                f"[flag-candidate] Detected flag-shaped token(s): {listed}. "
                "If this is the flag, write it to the FLAG file in the challenge "
                "directory (declarative submission) and verify it with verify_flag."
            )
    if parts:
        return {"context": "\n".join(parts)}
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
    from fulilian_ctf.hooks.kb_nudge import _kb_nudge_post_tool_hook

    manager = get_plugin_manager()
    registered = []
    # kb_nudge 与 detect_flag 同挂 post_tool_call（各自独立回调，互不影响）
    for event, callback in (
        ("pre_tool_call", _ctf_pre_tool_hook),
        ("post_tool_call", _ctf_post_tool_hook),
        ("post_tool_call", _kb_nudge_post_tool_hook),
    ):
        hooks = manager._hooks.setdefault(event, [])
        if callback not in hooks:
            hooks.append(callback)
            if event not in registered:
                registered.append(event)
    return registered


__all__ = [
    "check_command",
    "register_ctf_tool_hooks",
    "_kb_nudge_post_tool_hook",
]
