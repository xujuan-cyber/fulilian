"""可解性探针 + Auto-Prompter 动态提示词（F2-003 扩展）。

保留原有 ProbeResult / probe_challenge 探活能力，新增：
- FileInfo / QuickScanResult / NetworkInfo / EnvInfo 数据类
- AutoPrompter：三阶段文件系统扫描 + 快速扫描 + 网络探测 → 动态 prompt

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


# ── AutoPrompter ──────────────────────────────────────────────────────────


class AutoPrompter:
    """自动环境探测与动态 Prompt 生成器。

    三阶段流程：
    1. _scan_directory — 递归扫描目录，识别文件类型
    2. _quick_scan — 对小文件做 strings + 熵分析
    3. _probe_network — 网络端口扫描 + banner 抓取
    → _guess_category + _generate_prompt 输出
    """

    def __init__(self, timeout: int = 30):
        self.timeout = max(5, int(timeout))
        self._started: float = 0.0

    # ── 阶段 1：目录扫描 ─────────────────────────────────────────────────

    def _scan_directory(self, path: str) -> list[FileInfo]:
        """递归扫描目录，用 file -b 识别类型。超时保护。"""
        files: list[FileInfo] = []
        base = Path(path).resolve()
        if not base.is_dir():
            return files

        try:
            for root, dirs, entries in os.walk(str(base)):
                # 跳过隐藏目录和常见无关目录
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith(".")
                    and d not in ("__pycache__", "node_modules", ".git", ".svn")
                ]
                for entry in entries:
                    if len(files) >= 200:
                        return files  # 上限保护
                    full = Path(root) / entry
                    try:
                        if not full.is_file():
                            continue
                        stat = full.stat()
                        fi = FileInfo(
                            filename=entry,
                            path=str(full.resolve()),
                            size=stat.st_size,
                            extension=full.suffix.lower(),
                        )
                        # 用 file -b 识别类型（超时 2s）
                        fi.file_type = self._identify_file(full)
                        files.append(fi)
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return files

    @staticmethod
    def _identify_file(path: Path) -> str:
        """用 file -b 识别文件类型。"""
        try:
            result = subprocess.run(
                ["file", "-b", str(path)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                return (result.stdout or "").strip()[:80]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return ""

    # ── 阶段 2：快速扫描 ─────────────────────────────────────────────────

    def _quick_scan(self, files: list[FileInfo]) -> list[QuickScanResult]:
        """对小文件（<1MB）运行 strings 扫描 + 熵计算。"""
        results: list[QuickScanResult] = []
        for fi in files:
            if fi.size <= 0 or fi.size > 1_000_000:
                continue
            if len(results) >= 30:
                break
            try:
                path = Path(fi.path)
                if not path.is_file():
                    continue
                data = path.read_bytes()
                qs = QuickScanResult(
                    file=fi.filename,
                    file_type=fi.file_type,
                    entropy=self._compute_entropy(data),
                    strings=self._extract_strings(data),
                )
                results.append(qs)
            except (OSError, PermissionError, MemoryError):
                continue
        return results

    @staticmethod
    def _compute_entropy(data: bytes) -> float:
        """计算 Shannon 熵。"""
        if not data:
            return 0.0
        counts = [0] * 256
        for b in data:
            counts[b] += 1
        entropy = 0.0
        length = len(data)
        for c in counts:
            if c == 0:
                continue
            p = c / length
            entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def _extract_strings(data: bytes, min_len: int = 4) -> list[str]:
        """提取可读字符串（类似 strings 命令）。"""
        strings: list[str] = []
        current: list[bytes] = []
        for b in data:
            if 32 <= b <= 126:
                current.append(bytes([b]))
            else:
                if current:
                    s = b"".join(current).decode("ascii", errors="replace")
                    if len(s) >= min_len:
                        strings.append(s)
                    current = []
        if current:
            s = b"".join(current).decode("ascii", errors="replace")
            if len(s) >= min_len:
                strings.append(s)
        return strings

    # ── 阶段 3：网络探测 ─────────────────────────────────────────────────

    def _probe_network(self, host: str) -> list[NetworkInfo]:
        """扫描常见端口，读取 banner 和 HTTP 头。"""
        if not host:
            return []
        results: list[NetworkInfo] = []
        deadline = time.time() + self.timeout

        for port in _COMMON_PORTS:
            if time.time() > deadline:
                break
            if len(results) >= 15:
                break
            try:
                ni = self._probe_port(host, port)
                if ni is not None:
                    results.append(ni)
            except Exception:  # noqa: BLE001 — 单个端口失败不阻断
                continue
        return results

    def _probe_port(self, host: str, port: int) -> Optional[NetworkInfo]:
        """探测单个端口：TCP 连接 + banner 读取 + HTTP 请求。"""
        ni = NetworkInfo(host=host, port=port)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, port))
            if result != 0:
                sock.close()
                return None

            # 读取 banner
            try:
                banner = sock.recv(1024)
                ni.service_banner = banner.decode("utf-8", errors="replace").strip()
            except (socket.timeout, OSError):
                pass

            # HTTP 请求（标准端口/常见 Web 端口）
            if port in (80, 443, 8080, 8443, 8000, 8888):
                try:
                    sock.sendall(
                        b"GET / HTTP/1.0\r\nHost: " + host.encode() + b"\r\n\r\n"
                    )
                    resp = sock.recv(2048)
                    ni.http_headers = resp.decode("utf-8", errors="replace").strip()
                except (socket.timeout, OSError):
                    pass

            sock.close()
            return ni
        except (socket.timeout, socket.gaierror, OSError):
            return None

    # ── 类别猜测 ─────────────────────────────────────────────────────────

    def _guess_category(self, env_info: EnvInfo) -> str:
        """根据扩展名和文件类型猜测 CTF 类别。"""
        seen: list[str] = []

        # 统计扩展名匹配
        for f in env_info.files:
            cat = _EXT_CATEGORY_MAP.get(f.extension)
            if cat:
                seen.append(cat)

        # 统计 file 类型匹配
        for f in env_info.files:
            for key, cat in _TYPE_CATEGORY_MAP.items():
                if key in f.file_type:
                    seen.append(cat)

        # 找出现最多的类别
        if seen:
            return max(set(seen), key=seen.count)
        return ""

    # ── Prompt 生成 ──────────────────────────────────────────────────────

    def _generate_prompt(self, env_info: EnvInfo) -> str:
        """根据环境信息生成定制化解题 prompt。"""
        lines: list[str] = []
        cat = env_info.category_hint or self._guess_category(env_info)

        # 类别引导
        if cat:
            strategy_map = {
                "forensics": (
                    "This appears to be a forensics challenge. "
                    "Analyze the provided files for hidden data, steganography, "
                    "or encoded information. Check file headers, metadata, "
                    "and use tools like binwalk, strings, and foremost."
                ),
                "reverse": (
                    "This appears to be a reverse engineering challenge. "
                    "Analyze the binary with tools like strings, objdump, "
                    "and a disassembler. Look for hidden strings, custom "
                    "encryption, or validation logic."
                ),
                "web": (
                    "This appears to be a web challenge. "
                    "Check for common web vulnerabilities: SQL injection, "
                    "XSS, SSTI, path traversal, and hidden endpoints. "
                    "Inspect HTML/JS files for clues. "
                    "If a PHP site routes pages via an include-like param "
                    "(e.g. ?page=/?file=), try PHP filter chain RCE via "
                    "php://filter converters to turn LFI into RCE."
                ),
                "pwn": (
                    "This appears to be a binary exploitation challenge. "
                    "Run checksec first, then identify the bug (stack/heap "
                    "overflow, format string). "
                    "Fingerprint the libc before choosing an exploit chain: "
                    "use ldd or strings on the provided binary/libc to "
                    "determine the glibc major version, then pick matching "
                    "offsets/one_gadget."
                ),
                "crypto": (
                    "This appears to be a cryptography challenge. "
                    "Analyze the provided keys, ciphertexts, or encoded "
                    "data. Look for weak encryption, known plaintext, "
                    "or implementation flaws."
                ),
                "misc": (
                    "This appears to be a miscellaneous challenge. "
                    "Check file formats, encodings, and look for hidden "
                    "data. Try common CTF techniques like file carving, "
                    "base64 decoding, and steganography."
                ),
            }
            lines.append(strategy_map.get(cat, ""))
            lines.append("")

        # 文件线索
        if env_info.files:
            lines.append("Files in workspace:")
            for f in env_info.files[:10]:
                size_str = f"{f.size / 1024:.1f}KB" if f.size >= 1024 else f"{f.size}B"
                lines.append(f"- {f.filename} ({size_str}, {f.file_type})")
            lines.append("")

        # 高熵文件（疑似加密/压缩）
        high_entropy = [
            qs for qs in env_info.quick_scans if qs.entropy > 7.5
        ]
        if high_entropy:
            lines.append("High entropy files (possibly encrypted/compressed):")
            for qs in high_entropy:
                lines.append(f"- {qs.file} (entropy={qs.entropy:.2f})")
            lines.append("")

        # 网络服务
        if env_info.network_info:
            lines.append("Open network services:")
            for ni in env_info.network_info:
                tag = ""
                if "HTTP" in (ni.http_headers or ""):
                    tag = " [HTTP]"
                if ni.service_banner:
                    tag += f" banner={ni.service_banner[:60]}"
                lines.append(f"- {ni.host}:{ni.port}{tag}")
            lines.append("")

        # 指令
        lines.append(
            "Work directly in the challenge directory to solve it. "
            "When you find the flag, write it to the FLAG file."
        )

        return "\n".join(lines)

    # ── 主入口 ───────────────────────────────────────────────────────────

    def explore_and_generate(self, path: str, host: str = "") -> EnvInfo:
        """三阶段探测 → 生成动态 prompt。

        Args:
            path: 扫描目录
            host: 可选目标主机（进行网络探测）

        Returns:
            EnvInfo: 环境信息 + 生成的 prompt
        """
        self._started = time.time()

        # 阶段 1：目录扫描
        files = self._scan_directory(path)

        # 阶段 2：快速扫描
        quick_scans = self._quick_scan(files)

        # 阶段 3：网络探测
        network_info = self._probe_network(host) if host else []

        # 组装
        env_info = EnvInfo(
            files=files,
            quick_scans=quick_scans,
            network_info=network_info,
        )

        # 类别猜测
        env_info.category_hint = self._guess_category(env_info)

        # Prompt 生成
        env_info.custom_prompt = self._generate_prompt(env_info)

        return env_info


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
    "AutoPrompter",
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