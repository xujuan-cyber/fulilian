"""solve_reference — misc-morse-01 参考解（fixture 自证）。

正确流程：识别摩斯电码 → 查表解码 → 按题面格式补 flag{} 包裹。
"""
SOLUTION_STEPS = 2


from pathlib import Path

_MORSE_REV = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z", "-----": "0", ".----": "1", "..---": "2",
    "...--": "3", "....-": "4", ".....": "5", "-....": "6", "--...": "7",
    "---..": "8", "----.": "9",
}


def solve(work_dir: str) -> str:
    """读取摩斯电码 → 查表解码 → 组合 flag{...}。"""
    work = Path(work_dir)
    data = (work / "morse.txt").read_text(encoding="utf-8").strip()
    decoded = "".join(_MORSE_REV[token] for token in data.split())
    out = f"$ cat morse.txt\n{data}\n$ decoded:\n{decoded}\nflag{{{decoded.lower()}}}"
    return out
