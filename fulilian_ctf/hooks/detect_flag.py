#!/usr/bin/env python3
"""detect_flag.py — post_tool_call 独立 hook 脚本（F4-003 配套）。

FuLiLian 的 `fulilian solve` 路径默认通过
``fulilian_ctf.hooks.register_ctf_tool_hooks()`` 在进程内注册同等检测，
不需要任何配置。本脚本供手动 shell-hook 注册用::

    hooks:
      post_tool_call:
        - matcher: "terminal"
          command: "<项目根>/fulilian_ctf/hooks/detect_flag.py"
          timeout: 10

wire 协议（agent/shell_hooks.py）：stdin JSON ``result`` 为工具输出文本；
检测到 flag 形态候选时输出 ``{"context": "..."}`` 引导声明式提交。
内部错误 fail-open（不输出、exit 0）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — 无输入/坏 JSON：不出声
        return 0
    if not isinstance(payload, dict):
        return 0

    try:
        from fulilian_ctf.hooks import _ctf_post_tool_hook

        directive = _ctf_post_tool_hook(
            tool_name=payload.get("tool_name", "terminal"),
            result=payload.get("result"),
        )
    except Exception:  # noqa: BLE001 — 检测失败不出声
        return 0

    if directive and isinstance(directive, dict) and directive.get("context"):
        print(json.dumps(directive, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
