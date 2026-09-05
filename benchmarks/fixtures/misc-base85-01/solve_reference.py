"""solve_reference — misc-base85-01 参考解（fixture 自证）。

正确流程：识别 base85/ascii85 字符集 → 解码得到 flag。
"""
SOLUTION_STEPS = 2


import base64
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取 base85 编码串（截断展示，避免诱饵）→ 解码。"""
    work = Path(work_dir)
    data = (work / "encoded.txt").read_text(encoding="utf-8").strip()
    shown = data[:4] + "...(" + str(len(data)) + " chars)"
    return (f"$ cat encoded.txt\n{shown}\n$ b85decode:\n"
            + base64.b85decode(data).decode("utf-8"))
