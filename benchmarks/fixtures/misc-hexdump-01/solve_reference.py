"""solve_reference — misc-hexdump-01 参考解（fixture 自证）。

正确流程：识别 xxd 风格 hexdump → 提取 hex 列还原字节 → 还原明文。
"""
SOLUTION_STEPS = 2


from pathlib import Path
import re


def solve(work_dir: str) -> str:
    """读取 hexdump → 提取每行 hex 字段 → 还原字节流。"""
    work = Path(work_dir)
    dump = (work / "dump.txt").read_text(encoding="utf-8")
    outs = ["$ cat dump.txt\n" + dump]
    hexstr = "".join(
        "".join(seg)
        for line in dump.splitlines()
        for seg in [line[10:57].split()] if seg
    )
    data = bytes.fromhex(hexstr)
    outs.append("$ xxd -r dump.txt\n" + data.decode("utf-8", errors="replace"))
    return "\n".join(outs)
