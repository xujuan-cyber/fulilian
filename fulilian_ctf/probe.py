"""可解性探针 — 开局快速探活（F2-003）。

调度器在分配 solver 前对每个新题做探活。判定依据 connect errno 语义
（不依赖 ping——WSL 默认无 cap_net_raw，ping 不可用）：

- connect 成功            → REACHABLE（端口开放）
- ECONNREFUSED           → REACHABLE（收到 RST = 主机在线，仅端口关闭）
- EHOSTUNREACH/ENETUNREACH/EHOSTDOWN → INFRA_BLOCKED（无路由/主机不可达）
- 超时/被防火墙丢弃        → ping 回退：ping 通 → REACHABLE；
                           否则 UNKNOWN（放行尝试，不误杀）

注意：``socket.connect_ex`` 在拒绝/不可达时以 errno 返回而非抛
``ConnectionRefusedError``，因此统一按 errno 判定。
"""

from __future__ import annotations

import errno
import socket
import subprocess
from typing import Optional


class ProbeResult:
    """探针结果常量。"""

    REACHABLE = "reachable"          # 目标可达（端口开或主机在线）
    INFRA_BLOCKED = "infra_blocked"  # 基础设施不可达，跳过
    UNKNOWN = "unknown"              # 无法判定（防火墙/超时），放行尝试


def probe_challenge(target_host: str, target_port: int, timeout: int = 60) -> str:
    """快速探针确定题目是否可达。

    Args:
        target_host: 目标 IP 或主机名（空串视为本地文件类题目，直接可达）
        target_port: 目标端口
        timeout: 探针超时（秒），socket 层实际取 min(timeout, 10)

    Returns:
        ProbeResult: REACHABLE / INFRA_BLOCKED / UNKNOWN
    """
    if not target_host:
        # 无网络目标（本地文件/二进制题）不需要探活
        return ProbeResult.REACHABLE

    # 1. TCP 连接测试（connect_ex：0=成功，其余为 errno）
    connect_err: Optional[int] = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(min(max(int(timeout), 1), 10))
        try:
            connect_err = sock.connect_ex((str(target_host), int(target_port or 0)))
        finally:
            sock.close()
    except (socket.timeout, OSError):
        connect_err = None  # 超时/网络异常 → 走 ping 回退
    except ValueError:
        return ProbeResult.INFRA_BLOCKED  # 非法参数（端口非数字等）

    if connect_err == 0:
        return ProbeResult.REACHABLE
    if connect_err == errno.ECONNREFUSED:
        # 收到 RST：主机在线（仅端口关闭）→ 基础设施可达
        return ProbeResult.REACHABLE
    if connect_err in (errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN):
        return ProbeResult.INFRA_BLOCKED

    # 2. ping 回退（超时/被丢弃）：主机在线说明基础设施可达
    try:
        ping_result = subprocess.run(
            ["ping", "-c", "1", "-W", "5", str(target_host)],
            capture_output=True,
            timeout=10,
        )
        if ping_result.returncode == 0:
            return ProbeResult.REACHABLE
        # ping 失败（防火墙丢弃 / 无 cap_net_raw 权限）→ 无法判定，放行
        return ProbeResult.UNKNOWN
    except subprocess.TimeoutExpired:
        return ProbeResult.UNKNOWN
    except (FileNotFoundError, OSError):
        return ProbeResult.UNKNOWN


__all__ = ["ProbeResult", "probe_challenge"]
