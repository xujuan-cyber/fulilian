"""solve_reference — pwn-encoded-01 参考解（fixture 自证）。

正确流程：strings 发现乱码段 → 结合反编译产物的 XOR key → 解码 .rodata 得到 flag。
"""
SOLUTION_STEPS = 3


import re
from pathlib import Path


def solve(work_dir: str) -> str:
    """解析反编译产物中的 enc[] 与 key → XOR 解码 .rodata 数据。"""
    work = Path(work_dir)
    dec = (work / "decompiled.c").read_text(encoding="utf-8")
    outs = ["$ cat decompiled.c\n" + dec]
    arr = re.search(r"enc\[\]\s*=\s*\{([^}]*)\}", dec).group(1)
    key = int(re.search(r"key\s*=\s*(0x[0-9a-fA-F]+)", dec).group(1), 16)
    data = bytes(int(x, 16) for x in arr.split(",") if x.strip())
    decoded = bytes(b ^ key for b in data if b != 0)
    outs.append(f"$ python3 -c \"decode\"\n{decoded.decode('ascii', errors='replace')}")
    return "\n".join(outs)
