"""solve_reference — web-robots-01 参考解（fixture 自证）。

正确流程：读取 robots.txt → 逐个访问 Disallow 路径 → 在隐藏目录文件中发现 flag。
"""
SOLUTION_STEPS = 3


from pathlib import Path


def solve(work_dir: str) -> str:
    """解析 robots.txt 的 Disallow 路径并逐个读取，输出命中内容。"""
    work = Path(work_dir)
    robots = (work / "robots.txt").read_text(encoding="utf-8")
    paths = [
        ln.split(":", 1)[1].strip()
        for ln in robots.splitlines()
        if ln.startswith("Disallow:")
    ]
    outs = ["$ curl -s /robots.txt\n" + robots]
    for rel in paths:
        target = work / rel.lstrip("/")
        if target.is_file():
            outs.append(f"$ curl -s /{rel.strip('/')}/notes.txt\n" if target.is_dir() else
                        f"$ cat {rel}\n" + target.read_text(encoding="utf-8", errors="replace"))
        elif target.is_dir():
            for f in sorted(target.iterdir()):
                outs.append(f"$ curl -s {rel}{f.name}\n" + f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(outs)
