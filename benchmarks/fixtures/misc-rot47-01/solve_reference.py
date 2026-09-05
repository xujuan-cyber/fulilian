"""solve_reference — misc-rot47-01 参考解（fixture 自证）。

正确流程：识别 ROT47（可打印 ASCII 94 字符轮转）→ 自逆变换解码。
"""
SOLUTION_STEPS = 2


from pathlib import Path


def solve(work_dir: str) -> str:
    """读取 ROT47 编码串 → 应用自逆 ROT47 变换。"""

    def rot47(s):
        return "".join(
            chr(33 + ((ord(c) - 33 + 47) % 94)) if 33 <= ord(c) <= 126 else c for c in s
        )

    work = Path(work_dir)
    data = (work / "encoded.txt").read_text(encoding="utf-8").strip()
    return f"$ cat encoded.txt\n{data}\n$ rot47:\n" + rot47(data)
