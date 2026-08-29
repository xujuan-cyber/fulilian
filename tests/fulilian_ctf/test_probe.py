"""可解性探针（F2-003）单元测试。

判定依据 connect errno 语义（WSL 无 cap_net_raw，ping 仅作回退）：
ECONNREFUSED=主机在线；EHOSTUNREACH=不可达；超时→ping 回退→UNKNOWN 放行。
"""

from __future__ import annotations

import errno
import socket
import subprocess
from unittest.mock import MagicMock

from fulilian_ctf.probe import ProbeResult, probe_challenge


class FakeSock:
    """可编程 connect_ex errno 的假 socket。"""

    def __init__(self, err):
        self._err = err
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t

    def connect_ex(self, addr):
        if isinstance(self._err, BaseException):
            raise self._err
        return self._err

    def close(self):
        pass


def _patch_socket(monkeypatch, err):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock(err))


def test_no_target_is_reachable():
    """无网络目标（本地文件类题目）直接可达。"""
    assert probe_challenge("", 0, timeout=2) == ProbeResult.REACHABLE


def test_open_port_reachable():
    """监听中的端口 → REACHABLE（真实 socket）。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert probe_challenge("127.0.0.1", port, timeout=2) == ProbeResult.REACHABLE
    finally:
        srv.close()


def test_refused_means_host_up():
    """ECONNREFUSED：主机在线（端口关闭）→ REACHABLE，不依赖 ping。"""
    assert probe_challenge("127.0.0.1", 1, timeout=2) == ProbeResult.REACHABLE


def test_no_route_is_infra_blocked(monkeypatch):
    """EHOSTUNREACH → INFRA_BLOCKED（无需 ping）。"""
    _patch_socket(monkeypatch, errno.EHOSTUNREACH)
    assert probe_challenge("192.0.2.1", 80, timeout=2) == ProbeResult.INFRA_BLOCKED


def test_timeout_with_ping_success_reachable(monkeypatch):
    """连接超时 + ping 成功 → REACHABLE。"""
    _patch_socket(monkeypatch, errno.ETIMEDOUT)

    class FakeProc:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    assert probe_challenge("192.0.2.1", 80, timeout=2) == ProbeResult.REACHABLE


def test_timeout_with_ping_fail_unknown(monkeypatch):
    """连接超时 + ping 失败（防火墙/无权限）→ UNKNOWN 放行，不误杀。"""
    _patch_socket(monkeypatch, errno.ETIMEDOUT)

    class FakeProc:
        returncode = 1

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    assert probe_challenge("192.0.2.1", 80, timeout=2) == ProbeResult.UNKNOWN


def test_ping_times_out_unknown(monkeypatch):
    """ping 超时 → UNKNOWN。"""
    _patch_socket(monkeypatch, errno.ETIMEDOUT)

    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe_challenge("192.0.2.1", 80, timeout=2) == ProbeResult.UNKNOWN


def test_no_ping_binary_unknown(monkeypatch):
    """无 ping 工具 → UNKNOWN。"""
    _patch_socket(monkeypatch, errno.ETIMEDOUT)

    def fake_run(*a, **k):
        raise FileNotFoundError("ping not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe_challenge("192.0.2.1", 80, timeout=2) == ProbeResult.UNKNOWN


def test_socket_exception_falls_back_to_ping(monkeypatch):
    """socket 层抛异常 → ping 回退。"""
    _patch_socket(monkeypatch, socket.timeout())

    class FakeProc:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    assert probe_challenge("192.0.2.1", 80, timeout=2) == ProbeResult.REACHABLE


def test_bad_port_is_infra_blocked(monkeypatch):
    """非法端口 → INFRA_BLOCKED。"""
    _patch_socket(monkeypatch, MagicMock())  # 不会真正走 socket 逻辑
    assert probe_challenge("127.0.0.1", "not-a-port", timeout=2) == ProbeResult.INFRA_BLOCKED
