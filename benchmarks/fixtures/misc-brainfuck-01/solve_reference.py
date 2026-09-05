"""solve_reference — misc-brainfuck-01 参考解（fixture 自证）。

正确流程：识别 brainfuck → 实现最小解释器（+ . >）执行程序得到输出。
"""
SOLUTION_STEPS = 2


from pathlib import Path


def solve(work_dir: str) -> str:
    """读取 brainfuck 程序 → 最小解释器执行（支持 + . > < - [ ]）。"""
    work = Path(work_dir)
    prog = (work / "program.b").read_text(encoding="utf-8")
    tape = [0] * 1024
    ptr = ip = 0
    out = []
    bracket = {}
    stack = []
    for i, c in enumerate(prog):
        if c == "[":
            stack.append(i)
        elif c == "]":
            j = stack.pop()
            bracket[i] = j
            bracket[j] = i
    steps = 0
    while ip < len(prog) and steps < 5_000_000:
        c = prog[ip]
        if c == "+":
            tape[ptr] = (tape[ptr] + 1) % 256
        elif c == "-":
            tape[ptr] = (tape[ptr] - 1) % 256
        elif c == ".":
            out.append(chr(tape[ptr]))
        elif c == ">":
            ptr += 1
        elif c == "<":
            ptr -= 1
        elif c == "[" and tape[ptr] == 0:
            ip = bracket[ip]
        elif c == "]" and tape[ptr] != 0:
            ip = bracket[ip]
        ip += 1
        steps += 1
    return "$ bf program.b\n" + "".join(out)
