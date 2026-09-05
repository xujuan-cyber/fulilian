"""solve_reference — web-source-comment-01 参考解（fixture 自证）。

正确流程：查看页面源码 → 在 HTML 注释中发现开发遗留 flag。
"""
SOLUTION_STEPS = 2


from pathlib import Path
import re


def solve(work_dir: str) -> str:
    """抓取页面源码并提取全部 HTML 注释。"""
    work = Path(work_dir)
    html = (work / "index.html").read_text(encoding="utf-8")
    comments = re.findall(r"<!--(.*?)-->", html, re.DOTALL)
    out = "$ curl -s http://challenge/index.html\n" + html + "\n$ comments:\n"
    out += "\n".join(c.strip() for c in comments)
    return out
