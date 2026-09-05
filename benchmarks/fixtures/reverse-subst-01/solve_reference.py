"""solve_reference — reverse-subst-01 参考解（fixture 自证）。

正确流程：从程序数据段提取替换表（subst.json）→ 构造逆映射 → 解码密文。
"""
SOLUTION_STEPS = 3


import json
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取替换表 → 构造逆映射 → 解码 encoded.txt。"""
    work = Path(work_dir)
    table = json.loads((work / "subst.json").read_text(encoding="utf-8"))
    ct = (work / "encoded.txt").read_text(encoding="utf-8").strip()
    inv = {v: k for k, v in table.items()}
    pt = "".join(inv.get(ch, ch) for ch in ct)
    return f"$ cat subst.json\n{json.dumps(table)}\n$ decoded:\n{pt}"
