"""CTFd 对接（F3-011/F3-012）测试。

- CTFdAdapter：真实 HTTP 调用打本地 http.server stub（list/get/submit、
  Token 认证头、非 2xx 抛错）
- sync_challenges：导出 manifest 兼容 ``registry.load_challenges``（可被
  solve-all 直接消费）
- poll_new_challenges：新题检测 + 状态文件
- create_poll_job：复用 cron.jobs.create_job（monkeypatch，不碰真实 jobs.json）
- MCP server（F3-012）：initialize / tools/list / tools/call / 未知方法 /
  tool 报错的 JSON-RPC 处理
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from fulilian_ctf.ctfd_adapter import (
    CTFdAdapter,
    CTFdError,
    _handle_rpc_request,
    create_poll_job,
    mcp_call_tool,
    poll_new_challenges,
    sync_challenges,
)


# ── 本地 CTFd stub ────────────────────────────────────────────────────────

CHALLENGES = [
    {"id": 1, "name": "baby web", "category": "web", "value": 100, "type": "standard"},
    {"id": 2, "name": "rsa入门", "category": "crypto", "value": 500, "type": "standard"},
]

DETAILS = {
    1: {"id": 1, "name": "baby web", "category": "web", "value": 100,
        "description": "find the sqli", "connection_info": "10.0.0.1:80"},
    2: {"id": 2, "name": "rsa入门", "category": "crypto", "value": 500,
        "description": "small e attack", "connection_info": ""},
}


class _CTFdStub(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/v1/challenges":
            if self.headers.get("Authorization") != "Token valid-key":
                return self._json(401, {"success": False})
            return self._json(200, {"success": True, "data": CHALLENGES})
        if self.path.startswith("/api/v1/challenges/"):
            cid = int(self.path.rsplit("/", 1)[1])
            if cid in DETAILS:
                return self._json(200, {"success": True, "data": DETAILS[cid]})
            return self._json(404, {"success": False})
        return self._json(404, {"success": False})

    def do_POST(self):
        if self.path == "/api/v1/challenges/attempt":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            correct = payload.get("submission") == "flag{yes}"
            return self._json(200, {
                "success": True,
                "data": {"status": "correct" if correct else "incorrect"},
            })
        return self._json(404, {"success": False})

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture(scope="module")
def ctfd_base_url():
    server = HTTPServer(("127.0.0.1", 0), _CTFdStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


# ── CTFdAdapter ───────────────────────────────────────────────────────────

def test_adapter_list_challenges(ctfd_base_url):
    adapter = CTFdAdapter(ctfd_base_url, api_key="valid-key")
    items = adapter.list_challenges()
    assert len(items) == 2
    assert items[0]["name"] == "baby web"


def test_adapter_auth_header(ctfd_base_url):
    adapter = CTFdAdapter(ctfd_base_url, api_key="wrong")
    with pytest.raises(Exception):
        adapter.list_challenges()


def test_adapter_get_challenge(ctfd_base_url):
    adapter = CTFdAdapter(ctfd_base_url, api_key="valid-key")
    detail = adapter.get_challenge(1)
    assert detail["description"] == "find the sqli"
    with pytest.raises(Exception):
        adapter.get_challenge(999)


def test_adapter_submit_flag(ctfd_base_url):
    adapter = CTFdAdapter(ctfd_base_url, api_key="valid-key")
    ok = adapter.submit_flag(1, "flag{yes}")
    assert ok["data"]["status"] == "correct"
    bad = adapter.submit_flag(1, "flag{no}")
    assert bad["data"]["status"] == "incorrect"


# ── manifest 同步（对接 solve-all）────────────────────────────────────────

def test_sync_challenges_produces_registry_manifest(ctfd_base_url, tmp_path):
    from fulilian_ctf.registry import challenge_to_project, load_challenges

    out = tmp_path / "platform"
    entries = sync_challenges(CTFdAdapter(ctfd_base_url, "valid-key"), out)

    assert (out / "manifest.json").is_file()
    assert len(entries) == 2

    # registry.load_challenges 目录模式可直接消费
    loaded = load_challenges(str(out))
    assert {e["id"] for e in loaded} == {"ctfd-1", "ctfd-2"}

    # challenge_to_project 可构造 Project（target 解析自 connection_info）
    entry = next(e for e in loaded if e["id"] == "ctfd-1")
    project = challenge_to_project(entry, base_dir=out)
    assert project.target_host == "10.0.0.1"
    assert project.target_port == 80
    assert project.category == "web"

    # 分值 → 难度映射
    p2 = challenge_to_project(next(e for e in loaded if e["id"] == "ctfd-2"), base_dir=out)
    assert p2.difficulty == "medium"  # 500 分


def test_sync_challenges_degrades_without_detail(ctfd_base_url, tmp_path):
    """详情 404 时降级为列表信息，不失败。"""
    out = tmp_path / "plat2"
    entries = sync_challenges(CTFdAdapter(ctfd_base_url, "valid-key"), out)
    assert all(e["title"] for e in entries)


# ── F3-011 轮询 ───────────────────────────────────────────────────────────

def test_poll_new_challenges_first_run_and_update(ctfd_base_url, tmp_path):
    adapter = CTFdAdapter(ctfd_base_url, "valid-key")
    state = tmp_path / "poll-state.json"

    first = poll_new_challenges(adapter, state)
    assert {str(i["id"]) for i in first} == {"1", "2"}
    assert state.is_file()

    second = poll_new_challenges(adapter, state)
    assert second == []


def test_poll_new_challenges_detects_new(ctfd_base_url, tmp_path):
    adapter = CTFdAdapter(ctfd_base_url, "valid-key")
    state = tmp_path / "poll-state.json"
    poll_new_challenges(adapter, state)
    CHALLENGES.append({"id": 3, "name": "new pwn", "category": "pwn", "value": 200})
    try:
        new = poll_new_challenges(adapter, state)
        assert [str(i["id"]) for i in new] == ["3"]
    finally:
        CHALLENGES.pop()


def test_create_poll_job_uses_cron(tmp_path, monkeypatch):
    """复用 Fulilian cron 创建定时任务（不触碰真实 jobs.json）。"""
    captured = {}

    def fake_create_job(**kwargs):
        captured.update(kwargs)
        return {"id": "job-123", "next_run_at": "soon"}

    import cron.jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "create_job", fake_create_job)
    job = create_poll_job(
        base_url="https://ctf.example.com",
        api_key="k",
        platform_dir=tmp_path,
        schedule="every 5m",
    )
    assert job["id"] == "job-123"
    assert captured["schedule"] == "every 5m"
    assert captured["repeat"] is None  # 永久循环
    assert "solve-all" in captured["prompt"]


# ── F3-012 MCP server ─────────────────────────────────────────────────────

def _adapter_for_mcp(ctfd_base_url):
    return CTFdAdapter(ctfd_base_url, "valid-key")


def test_mcp_initialize():
    resp = _handle_rpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "fulilian-ctfd"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_tools_list():
    resp = _handle_rpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"ctfd_list_challenges", "ctfd_get_challenge", "ctfd_submit_flag"}


def test_mcp_tools_call(ctfd_base_url):
    adapter = _adapter_for_mcp(ctfd_base_url)
    resp = _handle_rpc_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "ctfd_list_challenges", "arguments": {}}},
        adapter=adapter,
    )
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert len(data["challenges"]) == 2


def test_mcp_submit_flag_call(ctfd_base_url):
    adapter = _adapter_for_mcp(ctfd_base_url)
    resp = _handle_rpc_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "ctfd_submit_flag",
                    "arguments": {"challenge_id": 1, "flag": "flag{yes}"}}},
        adapter=adapter,
    )
    assert resp["result"]["content"][0]["text"]  # JSON 文本结果
    assert "correct" in resp["result"]["content"][0]["text"]


def test_mcp_tool_error_is_tool_error(ctfd_base_url):
    """API 错误以 isError=true 的 tool 结果返回（MCP 规范），非协议错误。"""
    adapter = _adapter_for_mcp(ctfd_base_url)
    resp = _handle_rpc_request(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "ctfd_get_challenge", "arguments": {"challenge_id": 999}}},
        adapter=adapter,
    )
    assert resp["result"]["isError"] is True


def test_mcp_unknown_tool_and_method():
    resp = _handle_rpc_request(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}}
    )
    assert resp["result"]["isError"] is True

    resp2 = _handle_rpc_request({"jsonrpc": "2.0", "id": 7, "method": "bogus/method"})
    assert resp2["error"]["code"] == -32601


def test_mcp_notification_no_reply():
    assert _handle_rpc_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ) is None


def test_mcp_call_tool_requires_env():
    import os

    old = os.environ.pop("CTFD_BASE_URL", None)
    try:
        with pytest.raises(CTFdError):
            mcp_call_tool("ctfd_list_challenges", {})
    finally:
        if old is not None:
            os.environ["CTFD_BASE_URL"] = old
