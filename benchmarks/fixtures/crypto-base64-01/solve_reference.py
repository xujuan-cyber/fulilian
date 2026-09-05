"""solve_reference — crypto-base64-01 参考解（fixture 自证）。

正确流程：识别多层 base64 → 连续解码 3 次 → 得到 flag。
"""
SOLUTION_STEPS = 2


import base64
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取编码串 → 循环 base64 解码直到明文稳定。"""
    work = Path(work_dir)
    data = (work / "encoded.txt").read_text(encoding="utf-8").strip()
    outs = [f"$ cat encoded.txt\n{data}"]
    for i in range(4):
        try:
            data = base64.b64decode(data).decode("utf-8", errors="strict")
        except Exception:
            break
        outs.append(f"round {i + 1}: {data}")
    return "\n".join(outs)
