"""solve_reference — reverse-stackstr-01 参考解（fixture 自证）。

正确流程：程序把敏感字符串逆序存放 → 将 dump 内容反转还原。
"""
SOLUTION_STEPS = 2


from pathlib import Path


def solve(work_dir: str) -> str:
    """读取逆序字符串 dump（截断展示，避免诱饵）→ 反转还原。"""
    work = Path(work_dir)
    data = (work / "dump.txt").read_text(encoding="utf-8").strip()
    shown = data[:6] + "...(" + str(len(data)) + " chars)"
    return f"$ cat dump.txt\n{shown}\n$ reversed:\n" + data[::-1]
