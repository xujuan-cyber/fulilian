from __future__ import annotations

import io
import json

from fulilian_ctf.solve_rpc import handle_request, serve


def test_rpc_health_and_invalid_methods():
    assert handle_request({"jsonrpc": "2.0", "id": 1, "method": "health"})["result"]["ok"] is True
    assert handle_request({"jsonrpc": "2.0", "id": 2, "method": "unknown"})["error"]["code"] == -32601
    assert handle_request({"id": 3, "method": "health"})["error"]["code"] == -32600


def test_rpc_solve_dispatches_and_returns_jsonrpc_result():
    calls = []

    def solve():
        calls.append(True)
        return {"accepted": True, "challenge": "demo"}

    response = handle_request(
        {"jsonrpc": "2.0", "id": "r1", "method": "solve", "params": {"id": "demo"}},
        solve_fn=solve,
    )
    assert response == {"jsonrpc": "2.0", "id": "r1", "result": {"accepted": True, "challenge": "demo"}}
    assert calls == [True]


def test_rpc_stdio_protocol_is_one_response_per_request():
    incoming = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"health"}\n'
        'not-json\n'
    )
    outgoing = io.StringIO()
    assert serve(incoming, outgoing) == 0
    rows = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert rows[0]["result"]["service"] == "fulilian-solve"
    assert rows[1]["error"]["code"] == -32700


# ── P1 回归锁：协议流纯净 / 退出码 / 长驻进程隔离 ────────────────────────────
# 改动前：solve 路径把 --json 事件 print 到 sys.stdout，与协议帧混在一条流里，
# 客户端读到的第一行是既无 jsonrpc 也无 id 的事件对象；且 sys.exit("msg")
# 的字符串退出码会让 int() 抛 ValueError 打穿服务循环。

def test_rpc_solve_events_do_not_pollute_protocol_stream():
    """solve 期间写 stdout 的事件必须并入响应，而不是混进协议流。"""

    def solve():
        print(json.dumps({"event": "start", "challenge": "demo"}))
        print(json.dumps({"event": "result", "solved": True, "flag": "flag{x}"}))
        return None

    incoming = io.StringIO(
        '{"jsonrpc":"2.0","id":7,"method":"solve","params":{"id":"demo"}}\n'
    )
    outgoing = io.StringIO()
    assert serve(incoming, outgoing, solve_fn=solve) == 0

    lines = [ln for ln in outgoing.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1, f"协议流被污染，输出 {len(lines)} 行: {lines}"
    frame = json.loads(lines[0])                      # 必须是可解析的 JSON-RPC 帧
    assert frame["jsonrpc"] == "2.0" and frame["id"] == 7
    events = frame["result"]["events"]
    assert [e["event"] for e in events] == ["start", "result"]
    assert events[1]["flag"] == "flag{x}"


def test_rpc_captures_stray_non_json_stdout_lines():
    """非 JSON 行（第三方库打印）也截留进 events，不污染协议流。"""

    def solve():
        print("progress: 42%")
        return None

    response = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "solve", "params": {"id": "demo"}},
        solve_fn=solve,
    )
    assert response["result"]["events"] == [{"raw": "progress: 42%"}]


def test_rpc_string_systemexit_does_not_kill_server():
    """sys.exit("msg") 的字符串退出码不得让 int() 抛异常打穿服务。"""

    def solve():
        raise SystemExit("boom")

    response = handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": "solve", "params": {"id": "demo"}},
        solve_fn=solve,
    )
    assert response["result"]["exit_code"] == 1
    assert response["result"]["challenge"] == "demo"


def test_rpc_exit_codes_map_correctly():
    # 口径同 CPython：None→0，整数原样，字符串/浮点等一律按错误消息计 1
    for code_in, want in [(None, 0), (0, 0), (2, 2), ("", 1), ("oops", 1), ("2", 1), (3.7, 1)]:
        def solve(_code=code_in):
            raise SystemExit(_code)

        response = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "solve", "params": {"id": "d"}},
            solve_fn=solve,
        )
        assert response["result"]["exit_code"] == want, code_in


def test_rpc_solve_exception_is_isolated_per_request():
    """一条请求里 solve 崩溃，下一条仍须被正常服务。"""
    state = {"n": 0}

    def solve():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("solver exploded")
        return {"ok": True}

    incoming = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"solve","params":{"id":"a"}}\n'
        '{"jsonrpc":"2.0","id":2,"method":"solve","params":{"id":"b"}}\n'
    )
    outgoing = io.StringIO()
    assert serve(incoming, outgoing, solve_fn=solve) == 0
    rows = [json.loads(ln) for ln in outgoing.getvalue().splitlines() if ln.strip()]
    assert rows[0]["error"]["code"] == -32000
    assert rows[1]["result"] == {"ok": True}


def test_rpc_non_object_params_rejected_not_crashing():
    for params in ["a string", [1, 2], 5]:
        response = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "solve", "params": params}
        )
        assert response["error"]["code"] == -32602, params


def test_rpc_request_env_is_isolated(monkeypatch):
    """长驻 RPC 进程里，一次 solve 改写的环境变量不得泄漏给下一次请求。"""
    import os

    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)

    def solve():
        os.environ["FULILIAN_CTF_WORK_DIR"] = "/challenge/a"
        return {"ok": True}

    handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "solve", "params": {"id": "a"}},
        solve_fn=solve,
    )
    assert "FULILIAN_CTF_WORK_DIR" not in os.environ


def test_rpc_request_env_isolated_on_failure(monkeypatch):
    """solve 抛异常时同样要恢复环境变量。"""
    import os

    # 必须先置空：本测试断言的是「恢复成请求前的状态」，若同批别的测试留下
    # 了非空值，恢复出的就是这个遗留值（隔离本身是对的，断言会误报）。
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)

    def solve():
        os.environ["FULILIAN_CTF_WORK_DIR"] = "/challenge/b"
        raise RuntimeError("nope")

    handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "solve", "params": {"id": "b"}},
        solve_fn=solve,
    )
    assert "FULILIAN_CTF_WORK_DIR" not in os.environ
