"""solve_reference — reverse-encchain-01 参考解（fixture 自证）。

正确流程：识别 base32 外层 → 逐层解码 base32/base64。
"""
SOLUTION_STEPS = 2


import base64
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取编码串 → base32 解码一次 → base64 解码一次。"""
    work = Path(work_dir)
    data = (work / "encoded.txt").read_text(encoding="utf-8").strip()
    outs = [f"$ cat encoded.txt\n{data}"]
    step1 = base64.b32decode(data)
    outs.append("b32decode: " + step1.decode("ascii", errors="replace"))
    step2 = base64.b64decode(step1)
    outs.append("b64decode: " + step2.decode("utf-8", errors="replace"))
    return "\n".join(outs)
