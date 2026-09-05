"""solve_reference — crypto-vigenere-01 参考解（fixture 自证）。

正确流程：从运维备忘发现密钥提示（引号内 fulilian）→ 维吉尼亚解密。
"""
SOLUTION_STEPS = 4


import re
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取提示与密文 → 提取引号内密钥 → 维吉尼亚解密。"""
    work = Path(work_dir)
    hint = (work / "hint.txt").read_text(encoding="utf-8")
    ct = (work / "cipher.txt").read_text(encoding="utf-8").strip()
    key = re.search(r'"([a-z]+)"', hint).group(1)
    outs = ["$ cat hint.txt\n" + hint,
            f"$ cat cipher.txt (hex)\n{ct.encode().hex()}", f"# key={key}"]
    plain, ki = [], 0
    for ch in ct:
        if ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            k = ord(key[ki % len(key)]) - ord("a")
            plain.append(chr((ord(ch) - base - k) % 26 + base))
            ki += 1
        else:
            plain.append(ch)
    outs.append("$ decrypted:\n" + "".join(plain))
    return "\n".join(outs)
