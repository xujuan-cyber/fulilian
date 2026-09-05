"""solve_reference — crypto-rsa-01 参考解（fixture 自证）。

正确流程：n 很小可试除分解 → 求 d → 逐字节解密 c 列表。
"""
SOLUTION_STEPS = 3


from pathlib import Path
import re


def solve(work_dir: str) -> str:
    """读取 n/e/c → 试除分解 n → 计算 d → 逐字节 RSA 解密。"""
    work = Path(work_dir)
    text = (work / "output.txt").read_text(encoding="utf-8")
    n = int(re.search(r"n = (\d+)", text).group(1))
    e = int(re.search(r"e = (\d+)", text).group(1))
    c = [int(x) for x in re.search(r"c = \[([^]]+)\]", text).group(1).split(",")]
    outs = ["$ cat output.txt\n" + text.strip()]
    p = q = None
    for cand in range(2, int(n ** 0.5) + 1):
        if n % cand == 0:
            p, q = cand, n // cand
            break
    d = pow(e, -1, (p - 1) * (q - 1))
    msg = "".join(chr(pow(ci, d, n)) for ci in c)
    outs.append(f"# p={p} q={q}\n$ decrypted:\n{msg}")
    return "\n".join(outs)
