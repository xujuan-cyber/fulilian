"""solve_reference — web-cookie-01 参考解（fixture 自证）。

正确流程：检查会话 Cookie → base64 解码 admin_session 值得到 flag。
"""
SOLUTION_STEPS = 3


import base64
from pathlib import Path


def solve(work_dir: str) -> str:
    """读取请求 dump → 解析 Cookie → base64 解码 admin_session。"""
    work = Path(work_dir)
    req = (work / "session.txt").read_text(encoding="utf-8")
    cookie_line = next(ln for ln in req.splitlines() if ln.startswith("Cookie:"))
    kv = dict(
        item.split("=", 1) for item in cookie_line[len("Cookie: "):].split("; ") if "=" in item
    )
    raw = kv["admin_session"]
    decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
    return f"$ echo '{raw}' | base64 -d\n{decoded}"
