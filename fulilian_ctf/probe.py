"""可解性探针（F2-003 扩展）。

保留原有 ProbeResult / probe_challenge 探活能力，新增：
- FileInfo / QuickScanResult / NetworkInfo / EnvInfo 数据类

设计要点：
- 所有扫描操作只读，有超时保护
- 只扫描小文件（<1MB），避免大文件拖慢
- 监听器异常不影响主流程
"""

from __future__ import annotations

import errno
import math
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .env_overrides import (
    ENV_PROBE_SCAN_TIMEOUT,
    ENV_PROBE_TIMEOUT,
    env_float,
    env_int,
)

# 探针超时默认值（秒）。socket 层实际取 min(timeout, 10)（见 probe_challenge），
# 所以调大到 10 以上只影响"总超时"预算，不改变单次 connect 的等待。
DEFAULT_PROBE_TIMEOUT = 60
DEFAULT_PROBE_SCAN_TIMEOUT = 5.0


def probe_timeout_default() -> int:
    """生效的探针超时（env ``FULILIAN_CTF_PROBE_TIMEOUT``，秒）。

    dispatcher 也复用本函数，保证"探针超时"只有一个旋钮、一处默认。
    """
    return env_int(ENV_PROBE_TIMEOUT, DEFAULT_PROBE_TIMEOUT, min_value=1)


def probe_scan_timeout_default() -> float:
    """生效的兜底端口扫描总超时（env ``FULILIAN_CTF_PROBE_SCAN_TIMEOUT``，秒）。"""
    return env_float(ENV_PROBE_SCAN_TIMEOUT, DEFAULT_PROBE_SCAN_TIMEOUT, min_value=0.1)


# 常见 CTF 端口（按类别分组）
_COMMON_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 993, 995,
    1433, 1521, 2049, 3306, 3389, 5432, 5900, 6379, 8080,
    8443, 9200, 11211, 27017, 50070,
]

# 文件扩展名 → CTF 类别映射
_EXT_CATEGORY_MAP: dict[str, str] = {
    ".pcap": "forensics",
    ".pcapng": "forensics",
    ".png": "forensics",
    ".jpg": "forensics",
    ".jpeg": "forensics",
    ".gif": "forensics",
    ".bmp": "forensics",
    ".wav": "forensics",
    ".mp3": "forensics",
    ".flac": "forensics",
    ".raw": "forensics",
    ".elf": "reverse",
    ".so": "reverse",
    ".dll": "reverse",
    ".exe": "reverse",
    ".apk": "reverse",
    ".dex": "reverse",
    ".pyc": "reverse",
    ".wasm": "reverse",
    ".zip": "misc",
    ".7z": "misc",
    ".rar": "misc",
    ".tar": "misc",
    ".gz": "misc",
    ".bz2": "misc",
    ".xz": "misc",
    ".py": "misc",
    ".js": "web",
    ".php": "web",
    ".html": "web",
    ".sql": "web",
    ".xml": "web",
    ".json": "web",
    ".pem": "crypto",
    ".key": "crypto",
    ".crt": "crypto",
    ".enc": "crypto",
    ".asc": "crypto",
    ".gpg": "crypto",
}

# 文件类型字符串 → CTF 类别映射
_TYPE_CATEGORY_MAP: dict[str, str] = {
    "PCAP": "forensics",
    "pcap": "forensics",
    "PNG": "forensics",
    "JPEG": "forensics",
    "GIF": "forensics",
    "RIFF": "forensics",
    "ELF": "reverse",
    "PE32": "reverse",
    "MS-DOS": "reverse",
    "Zip": "misc",
    "gzip": "misc",
    "bzip2": "misc",
    "XZ": "misc",
    "HTML": "web",
    "XML": "web",
    "JSON": "web",
    "PEM": "crypto",
    "OpenPGP": "crypto",
}


# ── 数据类 ────────────────────────────────────────────────────────────────


@dataclass
class FileInfo:
    """文件信息。"""

    filename: str = ""
    path: str = ""
    size: int = 0
    extension: str = ""
    file_type: str = ""

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "path": self.path,
            "size": self.size,
            "extension": self.extension,
            "file_type": self.file_type,
        }


@dataclass
class QuickScanResult:
    """快速扫描结果。"""

    file: str = ""
    file_type: str = ""
    strings: list[str] = field(default_factory=list)
    entropy: float = 0.0

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "file_type": self.file_type,
            "strings": self.strings[:20],  # 只保留前 20 条
            "entropy": round(self.entropy, 4),
        }


@dataclass
class NetworkInfo:
    """网络探测信息。"""

    host: str = ""
    port: int = 0
    http_headers: str = ""
    service_banner: str = ""

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "http_headers": self.http_headers[:500] if self.http_headers else "",
            "service_banner": self.service_banner[:200] if self.service_banner else "",
        }


@dataclass
class EnvInfo:
    """环境信息汇总。"""

    files: list[FileInfo] = field(default_factory=list)
    quick_scans: list[QuickScanResult] = field(default_factory=list)
    network_info: list[NetworkInfo] = field(default_factory=list)
    custom_prompt: str = ""
    category_hint: str = ""

    def format_markdown(self) -> str:
        """格式化为 Markdown 报告。"""
        lines = ["## Environment Scan Report", ""]

        # 文件列表
        lines.append(f"### Files ({len(self.files)})")
        if self.files:
            lines.append("| File | Size | Type |")
            lines.append("|------|------|------|")
            for f in self.files[:30]:  # 最多 30 条
                size_str = (
                    f"{f.size / 1024:.1f}KB"
                    if f.size >= 1024
                    else f"{f.size}B"
                )
                lines.append(f"| {f.filename} | {size_str} | {f.file_type[:40]} |")
        lines.append("")

        # 快速扫描
        if self.quick_scans:
            lines.append(f"### Quick Scans ({len(self.quick_scans)})")
            for qs in self.quick_scans:
                lines.append(f"- **{qs.file}** (entropy={qs.entropy:.2f})")
                if qs.strings:
                    # 过滤掉太短/无意义的字符串
                    meaningful = [s for s in qs.strings if len(s) >= 4][:10]
                    if meaningful:
                        lines.append("  - Strings: `" + "`, `".join(meaningful) + "`")
            lines.append("")

        # 网络信息
        if self.network_info:
            lines.append(f"### Network ({len(self.network_info)} ports)")
            for ni in self.network_info:
                lines.append(f"- **{ni.host}:{ni.port}**")
                if ni.service_banner:
                    lines.append(f"  - Banner: {ni.service_banner[:100]}")
                if ni.http_headers:
                    lines.append(f"  - HTTP: {ni.http_headers[:100]}")
            lines.append("")

        # 类别提示
        if self.category_hint:
            lines.append(f"**Category hint:** {self.category_hint}")
            lines.append("")

        # 定制 prompt
        if self.custom_prompt:
            lines.append("### Generated Prompt")
            lines.append("")
            lines.append(self.custom_prompt)

        return "\n".join(lines)


# ── 增强探活：多端口扫描 + 隐藏端口发现 ────────────────────────────────────


class ProbeResult:
    """探针结果常量。"""

    REACHABLE = "reachable"          # 目标可达（端口开或主机在线）
    INFRA_BLOCKED = "infra_blocked"  # 基础设施不可达，跳过
    UNKNOWN = "unknown"              # 无法判定（防火墙/超时），放行尝试
    DISCOVERED = "discovered"        # 主端口不通，但发现其他开放端口


# 常见 CTF 端口（用于主端口不通时的兜底扫描）
_SCAN_PORTS = [
    80, 443, 8080, 8443, 8000, 8888, 3000, 5000, 9000, 9090, 9443,
    22, 21, 23, 3389, 5900, 5901,
    3306, 5432, 6379, 27017, 9200, 11211,
    7000, 7001, 5001, 7860, 7861, 9090,
]


def _scan_common_ports(
    host: str, exclude_port: int = 0, scan_timeout: Optional[float] = None
) -> list[int]:
    """扫描常见端口，返回所有开放端口列表。

    Args:
        host: 目标主机
        exclude_port: 排除的端口（已检测过的主端口）
        scan_timeout: 扫描总超时（秒）；``None`` → env → 默认 5.0

    Returns:
        list[int]: 开放端口列表
    """
    open_ports: list[int] = []
    resolved_scan_timeout = (
        float(scan_timeout) if scan_timeout is not None else probe_scan_timeout_default()
    )
    deadline = time.time() + resolved_scan_timeout
    for port in _SCAN_PORTS:
        if port == exclude_port:
            continue
        if time.time() > deadline:
            break
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            try:
                result = sock.connect_ex((host, port))
                if result == 0:
                    open_ports.append(port)
            finally:
                sock.close()
        except (socket.timeout, OSError):
            continue
    return open_ports


def probe_challenge(
    target_host: str, target_port: int = 0, timeout: Optional[int] = None
) -> str | tuple[str, int]:
    """快速探针确定题目是否可达。

    增强行为：
    - 主端口不通时，自动扫描常见端口列表
    - 如果发现其他开放端口，返回 ``(ProbeResult.DISCOVERED, discovered_port)``
    - 调度器收到 DISCOVERED 后会更新 target_port 并重试

    Args:
        target_host: 目标 IP 或主机名（空串视为本地文件类题目，直接可达）
        target_port: 目标端口
        timeout: 探针超时（秒）；``None`` → env ``FULILIAN_CTF_PROBE_TIMEOUT``
            → 默认 60。socket 层实际取 min(timeout, 10)

    Returns:
        ProbeResult: REACHABLE / INFRA_BLOCKED / UNKNOWN
        或 ``(ProbeResult.DISCOVERED, port)``: 发现隐藏端口
    """
    if timeout is None:
        timeout = probe_timeout_default()
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
        # 收到 RST：主机在线（仅端口关闭）→ 扫描常见端口
        open_ports = _scan_common_ports(target_host, exclude_port=target_port)
        if open_ports:
            return (ProbeResult.DISCOVERED, open_ports[0])
        return ProbeResult.REACHABLE  # 主机可达，但端口不对
    if connect_err in (errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN):
        # 主机不可达 → 再试一次，可能临时网络抖动
        try:
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock2.settimeout(3.0)
            retry = sock2.connect_ex((str(target_host), int(target_port or 0)))
            sock2.close()
            if retry == 0:
                return ProbeResult.REACHABLE
        except (socket.timeout, OSError):
            pass
        return ProbeResult.INFRA_BLOCKED

    # 超时/连接被丢弃 → 扫描常见端口
    open_ports = _scan_common_ports(target_host, exclude_port=target_port)
    if open_ports:
        return (ProbeResult.DISCOVERED, open_ports[0])

    # 2. ping 回退（超时/被丢弃）：主机在线说明基础设施可达
    try:
        ping_result = subprocess.run(
            ["ping", "-c", "1", "-W", "5", str(target_host)],
            capture_output=True,
            timeout=10,
        )
        if ping_result.returncode == 0:
            return ProbeResult.REACHABLE
        return ProbeResult.UNKNOWN
    except subprocess.TimeoutExpired:
        return ProbeResult.UNKNOWN
    except (FileNotFoundError, OSError):
        return ProbeResult.UNKNOWN


__all__ = [
    "DEFAULT_PROBE_SCAN_TIMEOUT",
    "DEFAULT_PROBE_TIMEOUT",
    "EnvInfo",
    "FileInfo",
    "NetworkInfo",
    "ProbeResult",
    "QuickScanResult",
    "probe_challenge",
    "probe_scan_timeout_default",
    "probe_timeout_default",
]