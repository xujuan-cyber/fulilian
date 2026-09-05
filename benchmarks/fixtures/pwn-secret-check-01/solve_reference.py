"""solve_reference — pwn-secret-check-01 参考解（fixture 自证）。

正确流程：file/strings 静态分析 ELF → 提取可打印字符串 → 发现 .rodata 中的 flag。
"""
SOLUTION_STEPS = 2


import re
from pathlib import Path


def solve(work_dir: str) -> str:
    """对二进制做 strings 层静态分析，输出全部可打印字符串。"""
    work = Path(work_dir)
    outs = ["$ file chall"]
    for cand in sorted(work.rglob("*")):
        if cand.is_file() and cand.name in ("chall",):
            data = cand.read_bytes()
            strings = re.findall(rb"[ -~]{4,}", data)
            outs[-1] += "\n$ strings chall"
            outs.append("\n".join(s.decode("ascii") for s in strings))
    return "\n".join(outs)
