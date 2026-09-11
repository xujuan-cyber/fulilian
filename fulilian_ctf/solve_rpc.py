"""Dedicated newline-delimited JSON-RPC transport for ``fulilian solve`` (F4-002).

协议约定（客户端必须能依赖）：**stdout 上只有 JSON-RPC 帧**，一帧一行，
`json.loads` 即可解析；诊断日志、进度输出一律走 stderr。

历史缺陷（本模块修复的重点）：``handle_solve_command`` 在 ``--json`` 下会把
``{"event": "start", ...}`` / ``{"event": "result", ...}`` 直接 print 到
``sys.stdout``。它和 ``serve()`` 的协议帧挤在同一条流里，客户端读到的第一行
是既无 ``jsonrpc`` 也无 ``id`` 的事件对象，按 JSON-RPC 解析立刻失败。现在
solve 期间的 stdout 被截留下来，解析成事件后并入响应结果的 ``events`` 字段
——协议流保持纯净，信息也不丢。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from types import SimpleNamespace

# solve 期间会被改写的环境变量：长驻 RPC 进程里必须按请求隔离，否则上一题
# 的工作目录/沙箱档会被下一题继承（下一题若在设置前失败，hook 层就会按
# 上一题的目录安全检查命令）。
_REQUEST_SCOPED_ENV = ("FULILIAN_CTF_WORK_DIR", "FULILIAN_SANDBOX_MODE", "FULILIAN_CTF_MODE")


def _response(request_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def _exit_code(code) -> int:
    """``SystemExit.code`` → 进程退出码（按 CPython 的语义）。

    ``sys.exit("msg")`` 的 code 是**字符串**，直接 ``int(code)`` 会抛
    ValueError；而这里若抛出，异常会穿出 ``handle_request``、穿出 ``serve()``
    的请求循环 —— 一条畸形退出码就能终止整个 RPC 服务进程。

    规则与解释器一致：``None`` → 0，整数（含 bool）原样，**其它任何对象**
    （字符串/浮点）一律按「错误消息」计 1，不再尝试 ``int()`` 强转。
    """
    if code is None:
        return 0
    if isinstance(code, (int, bool)):  # bool 是 int 子类，但 JSON 里须是 1/0
        return int(code)
    return 1


@contextlib.contextmanager
def _capture_stdout():
    """把 solve 期间写向 stdout 的内容截留到缓冲区（见模块 docstring）。"""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


@contextlib.contextmanager
def _isolated_env():
    """按请求隔离 ``_REQUEST_SCOPED_ENV`` 里的环境变量。"""
    import os

    saved = {k: os.environ.get(k) for k in _REQUEST_SCOPED_ENV}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _parse_events(text: str) -> list:
    """把 solve 期间 stdout 上的输出解析成事件列表。

    非 JSON 行（第三方库的杂散打印，如进度条）按 ``{"raw": line}`` 保留，
    便于排查；空行忽略。
    """
    events: list = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"raw": line})
    return events


def handle_request(request: dict, solve_fn=None) -> dict:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _response(request.get("id") if isinstance(request, dict) else None,
                          error={"code": -32600, "message": "Invalid Request"})
    method = request.get("method")
    request_id = request.get("id")
    if method == "health":
        return _response(request_id, {"ok": True, "service": "fulilian-solve"})
    if method != "solve":
        return _response(request_id, error={"code": -32601, "message": "Method not found"})
    params = request.get("params") or {}
    if not isinstance(params, dict):
        # params 允许是数组/对象，本方法只定义对象形态：类型不符时按无效参数
        # 拒绝，而不是让 params.get 抛 AttributeError 打穿服务循环
        return _response(request_id, error={"code": -32602, "message": "params must be an object"})
    challenge_id = str(params.get("id") or "").strip()
    if not challenge_id:
        return _response(request_id, error={"code": -32602, "message": "params.id is required"})
    if solve_fn is None:
        from .cli import handle_solve_command
        args = SimpleNamespace(
            id=challenge_id, model=params.get("model") or "",
            architect_model=params.get("architect_model") or "",
            executor_model=params.get("executor_model") or "",
            race=bool(params.get("race")), race_models=params.get("race_models"),
            multi_agent=bool(params.get("multi_agent")), directions=params.get("directions"),
            explorers=params.get("explorers"), oneshot=True, json=True,
        )
        solve_fn = lambda: handle_solve_command(args)  # noqa: E731

    with _isolated_env(), _capture_stdout() as captured:
        try:
            result = solve_fn()
        except SystemExit as exc:
            result = {"exit_code": _exit_code(exc.code), "challenge": challenge_id}
        except Exception as exc:  # noqa: BLE001 — 传输层边界：任何 solve 异常都不该打穿
            return _response(request_id, error={"code": -32000, "message": str(exc)})

    payload = result if result else {"challenge": challenge_id, "accepted": True}
    events = _parse_events(captured.getvalue())
    if events and isinstance(payload, dict):
        payload = {**payload, "events": events}
    return _response(request_id, payload)


def serve(stdin=None, stdout=None, solve_fn=None) -> int:
    """Serve one JSON-RPC request per input line; logs stay off stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _response(None, error={"code": -32700, "message": "Parse error"})
        else:
            try:
                response = handle_request(request, solve_fn=solve_fn)
            except Exception as exc:  # noqa: BLE001 — 单条请求的意外异常不得杀死服务
                rid = request.get("id") if isinstance(request, dict) else None
                response = _response(rid, error={"code": -32603, "message": f"Internal error: {exc}"})
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
