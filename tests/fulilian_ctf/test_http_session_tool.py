"""http_session 工具单测（P2-3 部分）——mock HTTP，不打真实网络。

覆盖：会话 cookies 跨调用延续与落盘 / close 丢弃 / body 截断与上限可配 /
headers 透传 / work_dir 边界（P0-4 同口径）/ 网络失败降级不抛。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import tools.ctf_solve as ctf_solve


@pytest.fixture(autouse=True)
def _clear_bound_env(monkeypatch):
    """隔离全量回归的环境泄漏：进程内跑过 solver_worker 的测试会把
    FULILIAN_CTF_WORK_DIR 留在 os.environ（solver.py:457 无清除），
    导致本文件所有用例意外进入绑定模式。除非用例显式 setenv，一律清除。
    """
    monkeypatch.delenv("FULILIAN_CTF_WORK_DIR", raising=False)


class FakeCookie:
    def __init__(self, name, value, domain="", path="/"):
        self.name, self.value, self.domain, self.path = name, value, domain, path


class FakeCookieJar:
    def __init__(self):
        self._cookies = {}

    def set(self, name, value, domain="", path="/"):
        self._cookies[name] = FakeCookie(name, value, domain, path)

    def __iter__(self):
        return iter(self._cookies.values())

    def dump(self):
        return {c.name: c.value for c in self._cookies.values()}


class FakeResponse:
    def __init__(self, status=200, url="http://target/", headers=None, text="ok"):
        self.status_code = status
        self.url = url
        self.headers = headers or {"Content-Type": "text/html"}
        self.text = text


class FakeSession:
    """行为仿真：request 时模拟服务端 Set-Cookie，并记录收到的 cookies。"""

    server_cookie = ("sid", "s3cret")

    def __init__(self):
        self.headers = {}
        self.cookies = FakeCookieJar()
        self.calls = []

    def request(self, method, url, headers=None, data=None,
                timeout=10, allow_redirects=True):
        self.calls.append({
            "method": method, "url": url, "headers": dict(headers or {}),
            "data": data, "cookies_sent": self.cookies.dump(),
        })
        # 模拟服务端下发会话 cookie
        name, value = self.server_cookie
        self.cookies.set(name, value, domain="target")
        return FakeResponse(text="hello world")


@pytest.fixture
def fake_http(monkeypatch):
    made = []

    def factory():
        s = FakeSession()
        made.append(s)
        return s

    monkeypatch.setattr(ctf_solve, "_new_session", factory)
    return made


def test_request_and_cookie_persistence(tmp_path, fake_http):
    work = str(tmp_path)
    out1 = ctf_solve._http_session_impl(work_dir=work, url="http://target/login")
    assert "status: 200" in out1
    # 服务端下发的 cookie 已落盘
    session_file = tmp_path / ".http_sessions" / "default.json"
    data = json.loads(session_file.read_text(encoding="utf-8"))
    assert any(c["name"] == "sid" and c["value"] == "s3cret"
               for c in data["cookies"])

    # 第二次调用：全新 Session 实例（模拟新进程），cookies 从盘上恢复并随请求发出
    out2 = ctf_solve._http_session_impl(work_dir=work, url="http://target/profile")
    sent = fake_http[-1].calls[-1]["cookies_sent"]
    assert sent.get("sid") == "s3cret"


def test_close_drops_session(tmp_path, fake_http):
    work = str(tmp_path)
    ctf_solve._http_session_impl(work_dir=work, url="http://target/a")
    session_file = tmp_path / ".http_sessions" / "default.json"
    assert session_file.is_file()
    out = ctf_solve._http_session_impl(work_dir=work, action="close")
    assert "closed" in out
    assert not session_file.exists()
    # close 后再请求 → 新会话，无历史 cookie
    ctf_solve._http_session_impl(work_dir=work, url="http://target/b")
    assert fake_http[-1].calls[-1]["cookies_sent"] == {}


def test_body_truncated_and_limit_configurable(tmp_path, fake_http, monkeypatch):
    work = str(tmp_path)
    monkeypatch.setattr(FakeSession, "server_cookie", ("x", "y"))
    big = "A" * 8000 + "B" * 6000  # 截断点后必须是可区分字符

    class BigSession(FakeSession):
        def request(self, *a, **kw):
            resp = super().request(*a, **kw)
            resp.text = big
            return resp

    monkeypatch.setattr(ctf_solve, "_new_session", lambda: BigSession())

    out = ctf_solve._http_session_impl(work_dir=work, url="http://target/big")
    assert "(truncated at 8000 chars" in out
    assert big[:8000] in out and "BBBBBB" not in out

    monkeypatch.setenv("FULILIAN_HTTP_BODY_LIMIT", "500")
    out2 = ctf_solve._http_session_impl(work_dir=work, url="http://target/big")
    assert "(truncated at 500 chars" in out2


def test_headers_passthrough(tmp_path, fake_http):
    work = str(tmp_path)
    ctf_solve._http_session_impl(
        work_dir=work, url="http://target/api", method="POST",
        headers="X-A: 1\nContent-Type: application/json", data='{"q":1}',
    )
    call = fake_http[-1].calls[-1]
    assert call["method"] == "POST"
    assert call["headers"].get("X-A") == "1"
    assert call["headers"].get("Content-Type") == "application/json"
    assert call["data"] == '{"q":1}'


def test_out_of_bound_work_dir_rejected(tmp_path, monkeypatch):
    bound = tmp_path / "ws"
    bound.mkdir()
    evil = tmp_path / "evil"
    evil.mkdir()
    monkeypatch.setenv("FULILIAN_CTF_WORK_DIR", str(bound))
    out = ctf_solve._http_session_impl(work_dir=str(evil), url="http://target/")
    assert "outside the bound" in out
    assert list(evil.iterdir()) == []


def test_network_failure_degrades_without_raise(tmp_path, monkeypatch, fake_http):
    work = str(tmp_path)

    class BoomSession(FakeSession):
        def request(self, *a, **kw):
            raise ConnectionError("refused")

    monkeypatch.setattr(ctf_solve, "_new_session", lambda: BoomSession())
    out = ctf_solve._http_session_impl(work_dir=work, url="http://target/")
    assert "request failed" in out  # 错误文本而非异常


def test_tool_registered_in_ctf_solve_toolset():
    from tools.registry import registry

    entry = registry.get_entry("http_session")
    assert entry is not None
    assert entry.toolset == "ctf_solve"
