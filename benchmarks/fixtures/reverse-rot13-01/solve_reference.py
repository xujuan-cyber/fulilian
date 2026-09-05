"""solve_reference — reverse-rot13-01 参考解（fixture 自证）。

正确流程：识别 ROT13 → 解码得到 flag。
"""
SOLUTION_STEPS = 2


import codecs
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取编码文本（截断展示，避免诱饵）→ ROT13 解码。"""
    work = Path(work_dir)
    data = (work / "encoded.txt").read_text(encoding="utf-8").strip()
    shown = data[:4] + "...(" + str(len(data)) + " chars)"
    return f"$ cat encoded.txt\n{shown}\n$ rot13:\n" + codecs.decode(data, "rot13")
