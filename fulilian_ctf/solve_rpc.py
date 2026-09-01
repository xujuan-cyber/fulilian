"""Dedicated newline-delimited JSON-RPC transport for ``fulilian solve`` (F4-002)."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace


def _response(request_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


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
        try:
            solve_fn = lambda: handle_solve_command(args)
        except Exception as exc:
            return _response(request_id, error={"code": -32000, "message": str(exc)})
    try:
        result = solve_fn()
    except SystemExit as exc:
        result = {"exit_code": int(exc.code or 0), "challenge": challenge_id}
    except Exception as exc:  # pragma: no cover - defensive transport boundary
        return _response(request_id, error={"code": -32000, "message": str(exc)})
    return _response(request_id, result or {"challenge": challenge_id, "accepted": True})


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
            response = handle_request(request, solve_fn=solve_fn)
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
