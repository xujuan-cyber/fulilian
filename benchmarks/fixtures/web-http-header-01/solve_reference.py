"""solve_reference — web-http-header-01 参考解（fixture 自证）。

正确流程：检查响应头 → 在自定义 X-Debug-Flag 头中发现 flag。
"""
SOLUTION_STEPS = 2


from pathlib import Path


def solve(work_dir: str) -> str:
    """读取响应头 dump，输出全部响应头（含自定义头）。"""
    work = Path(work_dir)
    resp = (work / "response.txt").read_text(encoding="utf-8")
    headers = resp.split("\r\n\r\n", 1)[0]
    return "$ curl -sI http://challenge/\n" + headers
