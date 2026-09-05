"""solve_reference — web-info-leak-01 参考解（fixture 自证）。

正确流程：目录列举发现 index.php.bak 备份泄露 → 读取备份文件内容。
"""
SOLUTION_STEPS = 2


import os
from pathlib import Path


def solve(work_dir: str) -> str:
    """列举目录 → 读取 .bak 备份泄露文件，返回其内容作为工具输出。"""
    work = Path(work_dir)
    listing = "\n".join(sorted(p.name for p in work.iterdir()))
    outs = ["$ ls -la\n" + listing]
    for p in sorted(work.glob("*.bak")):
        outs.append(f"$ cat {p.name}\n" + p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(outs)
