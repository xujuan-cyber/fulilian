"""CTF 危险命令检查表（F4-003）。

硬拦截清单：命中即 block（Hermes hardline/approval 层在其之外仍生效，
两者互补——这里管 CTF 场景特有模式，那里管通用系统破坏）。
"""

from __future__ import annotations

import re

# (标签, 正则) —— 标签用于 block 消息展示
DANGEROUS_PATTERNS = [
    # 文件系统破坏
    ("recursive force delete at filesystem root", r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+/(\s|$)"),
    ("mkfs (format filesystem)", r"mkfs\.\w+"),
    ("dd write to raw block device", r"dd\s+if=.*of=/dev/(sd|hd|nvme|vd)"),
    # 权限提升 / 全盘权限修改
    ("chmod 777 on filesystem root", r"chmod\s+(-R\s+)?777\s+/(\s|$)"),
    ("recursive chown on filesystem root", r"chown\s+(-R\s+)?[^ ]+\s+/(\s|$)"),
    # 系统配置破坏
    ("iptables flush (firewall teardown)", r"iptables\s+(-F|--flush)"),
    ("systemctl stop/disable of critical service", r"systemctl\s+(stop|disable|mask)\s+(ssh|sshd|networking|docker)\b"),
    ("system power state change", r"shutdown|reboot|halt|poweroff"),
    # fork bomb
    ("fork bomb", r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
]

DANGEROUS_PATTERNS_COMPILED = [
    (label, re.compile(pattern)) for label, pattern in DANGEROUS_PATTERNS
]

__all__ = ["DANGEROUS_PATTERNS", "DANGEROUS_PATTERNS_COMPILED"]
