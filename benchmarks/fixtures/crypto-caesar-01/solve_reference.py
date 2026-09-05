"""solve_reference — crypto-caesar-01 参考解（fixture 自证）。

正确流程：识别凯撒密码 → 暴力枚举 26 个移位 → 按常见平台前缀选中正确明文。
"""
SOLUTION_STEPS = 2


from pathlib import Path

COMMON_PREFIXES = ("flag", "ctfshow", "nssctf", "dasctf", "iscc", "ctf", "htb")


def solve(work_dir: str) -> str:
    """读取密文（hex 形式展示，避免诱饵）→ 枚举移位 → 按常见平台前缀选定明文。"""
    work = Path(work_dir)
    ct = (work / "cipher.txt").read_text(encoding="utf-8").strip()
    outs = [f"$ cat cipher.txt (hex)\n{ct.encode().hex()}"]
    answer = None
    for k in range(26):
        dec = []
        for ch in ct:
            if ch.isalpha():
                base = ord("A") if ch.isupper() else ord("a")
                dec.append(chr((ord(ch) - base - k) % 26 + base))
            else:
                dec.append(ch)
        cand = "".join(dec)
        if cand.split("{", 1)[0].lower() in COMMON_PREFIXES:
            answer = cand
            outs.append(f"shift={k}: {cand}")
    return "\n".join(outs)
