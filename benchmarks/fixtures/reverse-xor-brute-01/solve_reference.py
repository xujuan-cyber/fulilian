"""solve_reference — reverse-xor-brute-01 参考解（fixture 自证）。

正确流程：单字节异或文件 → 暴力枚举 256 key → 按常见平台前缀选中明文。
"""
SOLUTION_STEPS = 2


from pathlib import Path

COMMON_PREFIXES = ("flag", "ctfshow", "nssctf", "dasctf", "iscc", "ctf", "htb")


def solve(work_dir: str) -> str:
    """读取 encoded.bin → 枚举单字节 XOR 密钥 → 按常见平台前缀选定明文。"""
    work = Path(work_dir)
    raw = (work / "encoded.bin").read_bytes()
    outs = ["$ xxd encoded.bin | head"]
    for k in range(256):
        dec = bytes(b ^ k for b in raw)
        try:
            text = dec.decode("ascii")
        except UnicodeDecodeError:
            continue
        if all(32 <= ord(c) < 127 for c in text) and text.split("{", 1)[0].lower() in COMMON_PREFIXES:
            outs.append(f"key=0x{k:02x}: {text}")
    return "\n".join(outs)
