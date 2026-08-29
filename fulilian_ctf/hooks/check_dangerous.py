#!/usr/bin/env python3
"""check_dangerous.py — pre_tool_call 独立 hook 脚本（F4-003/F4-004）。

FuLiLian 的 `fulilian solve` 路径默认通过
``fulilian_ctf.hooks.register_ctf_tool_hooks()`` 在进程内注册同等检查，
不需要任何配置。本脚本供用户想以 shell-hook 形式全局启用时手动注册用::

    hooks:
      pre_tool_call:
        - matcher: "terminal"
          command: "<项目根>/fulilian_ctf/hooks/check_dangerous.py"
          timeout: 10

wire 协议（agent/shell_hooks.py）：stdin JSON ``args.command`` 为终端命令；
命中危险模式/沙箱限制 → stdout ``{"action":"block",...}`` + 退出码 2。
内部错误 fail-open 放行（hardline/approval 层在 hook 之外兜底）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _extract_command(payload: dict) -> str:
    """从 hook payload 提取终端命令（兼容 args.command / tool_input.command）。"""
    args = payload.get("args") or payload.get("tool_input") or {}
    if isinstance(args, str):
        return args
    return str(args.get("command", "") or "")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — 无输入/坏 JSON：fail-open
        return 0
    if not isinstance(payload, dict):
        return 0

    command = _extract_command(payload)
    if not command:
        return 0

    try:
        from fulilian_ctf.hooks import check_command

        blocked, message = check_command(command, str(payload.get("cwd") or "."))
    except Exception:  # noqa: BLE001 — 检查失败不阻断工具调用
        return 0

    if blocked:
        print(json.dumps({"action": "block", "message": message}))
        return 2  # BLOCK_EXIT_CODE 双保险（agent/shell_hooks.py）
    return 0


if __name__ == "__main__":
    sys.exit(main())
