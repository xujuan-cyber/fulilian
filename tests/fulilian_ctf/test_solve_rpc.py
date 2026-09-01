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
