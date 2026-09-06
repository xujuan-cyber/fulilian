"""快速端口连通性检测脚本。

在启动 solver 前快速检测所有题目的端口可达性，识别不可达题目和隐藏端口。

用法:
    python tools/port_check.py <manifest.json>          # 从 manifest 文件读取
    python tools/port_check.py <platform_dir>            # 从平台目录读取
    python tools/port_check.py --host 10.0.0.1 --ports 80,443,8080  # 指定主机
    python tools/port_check.py <manifest.json> --nmap    # 启用 nmap 深度扫描
    python tools/port_check.py <manifest.json> --json    # JSON 输出

输出:
    - 终端表格：题目 ID、主机、端口、状态、响应时间、服务
    - Markdown 报告：port_check_report.md（含分类汇总）
    - JSON 详情：--json 时输出结构化数据
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── 常见 CTF 端口（按用途分组） ──────────────────────────────────────────────

WEB_PORTS = [80, 443, 8080, 8443, 8000, 8888, 3000, 5000, 9000, 9090, 9443]
API_PORTS = [8000, 8443, 443, 80, 8080, 5000, 3000, 9090, 9000, 5001, 7000, 7001, 7860, 7861]
DB_PORTS = [3306, 5432, 6379, 27017, 1433, 1521, 9200, 11211, 50070]
SVC_PORTS = [21, 22, 23, 25, 53, 110, 143, 445, 993, 995, 2049, 3389, 5900, 5901]
ALL_COMMON_PORTS = sorted(set(WEB_PORTS + API_PORTS + DB_PORTS + SVC_PORTS))

# 端口 → 服务名映射
_PORT_SERVICE: dict[int, str] = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB",
    993: "IMAPS", 995: "POP3S", 1433: "MSSQL", 1521: "Oracle",
    2049: "NFS", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 5901: "VNC-1", 6379: "Redis", 8080: "HTTP-Alt",
    8000: "HTTP-Alt2", 8443: "HTTPS-Alt", 8888: "HTTP-Alt3",
    9200: "Elasticsearch", 11211: "Memcached", 27017: "MongoDB",
    50070: "HDFS", 3000: "HTTP-Alt4", 5000: "HTTP-Alt5",
    9000: "HTTP-Alt6", 9090: "HTTP-Alt7", 9443: "HTTPS-Alt2",
    7860: "Gradio", 7861: "Gradio-Alt", 7000: "HTTP-Alt8",
    7001: "HTTP-Alt9", 5001: "HTTP-Alt10",
}


@dataclass
class PortResult:
    """单个端口的检测结果。"""

    host: str
    port: int
    reachable: bool
    response_time: float = 0.0
    banner: str = ""
    service: str = ""

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "reachable": self.reachable,
            "response_time": round(self.response_time, 3),
            "banner": self.banner[:200] if self.banner else "",
            "service": self.service,
        }


@dataclass
class HostResult:
    """单个主机的检测结果。"""

    host: str
    primary_port: int = 0
    primary_reachable: bool = False
    primary_response_time: float = 0.0
    discovered_ports: list[PortResult] = field(default_factory=list)
    ping_ok: bool = False

    @property
    def any_reachable(self) -> bool:
        return self.primary_reachable or bool(self.discovered_ports)

    @property
    def all_open_ports(self) -> list[PortResult]:
        """返回所有可达端口（含主端口）。"""
        ports = list(self.discovered_ports)
        if self.primary_reachable:
            ports.insert(
                0,
                PortResult(
                    host=self.host,
                    port=self.primary_port,
                    reachable=True,
                    response_time=self.primary_response_time,
                    service=_PORT_SERVICE.get(self.primary_port, ""),
                ),
            )
        return ports

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "primary_port": self.primary_port,
            "primary_reachable": self.primary_reachable,
            "primary_response_time": round(self.primary_response_time, 3),
            "ping_ok": self.ping_ok,
            "discovered_ports": [p.to_dict() for p in self.discovered_ports],
        }


# ── 核心检测函数 ────────────────────────────────────────────────────────────


def _probe_tcp(host: str, port: int, timeout: float = 3.0) -> tuple[bool, float, str]:
    """TCP 连接测试，返回 (可达, 响应时间, banner)。"""
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed = time.time() - start
        if result != 0:
            sock.close()
            return False, elapsed, ""
        # 读 banner
        banner = ""
        try:
            sock.settimeout(1.0)
            data = sock.recv(1024)
            banner = data.decode("utf-8", errors="replace").strip()
        except (socket.timeout, OSError):
            pass
        sock.close()
        return True, elapsed, banner
    except (socket.timeout, socket.gaierror, OSError):
        elapsed = time.time() - start
        return False, elapsed, ""


def _ping_host(host: str, timeout: float = 5.0) -> bool:
    """Ping 测试主机是否在线。"""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(int(timeout)), str(host)],
            capture_output=True,
            timeout=timeout + 1,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def check_host(
    host: str,
    primary_port: int = 0,
    scan_common: bool = True,
    probe_timeout: float = 3.0,
    scan_timeout: float = 5.0,
) -> HostResult:
    """检测单个主机。

    Args:
        host: 目标主机
        primary_port: 主端口（API 返回的）
        scan_common: 主端口不通时是否扫描常见端口
        probe_timeout: 单端口超时
        scan_timeout: 扫描总超时

    Returns:
        HostResult: 检测结果
    """
    result = HostResult(host=host, primary_port=primary_port)

    # 1. 检测主端口
    if primary_port > 0:
        reachable, elapsed, banner = _probe_tcp(host, primary_port, probe_timeout)
        result.primary_reachable = reachable
        result.primary_response_time = elapsed
        if reachable:
            result.discovered_ports.append(
                PortResult(
                    host=host,
                    port=primary_port,
                    reachable=True,
                    response_time=elapsed,
                    banner=banner,
                    service=_PORT_SERVICE.get(primary_port, ""),
                )
            )
            return result  # 主端口可达，无需继续

    # 2. 主端口不通 → 扫描常见端口
    if scan_common:
        deadline = time.time() + scan_timeout
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {
                ex.submit(_probe_tcp, host, port, min(probe_timeout, 2.0)): port
                for port in ALL_COMMON_PORTS
                if port != primary_port
            }
            for future in as_completed(futures):
                if time.time() > deadline:
                    break
                port = futures[future]
                try:
                    reachable, elapsed, banner = future.result(timeout=1)
                except Exception:  # noqa: BLE001
                    continue
                if reachable:
                    result.discovered_ports.append(
                        PortResult(
                            host=host,
                            port=port,
                            reachable=True,
                            response_time=elapsed,
                            banner=banner,
                            service=_PORT_SERVICE.get(port, ""),
                        )
                    )

    # 3. 所有端口不通 → ping 回退
    if not result.any_reachable:
        result.ping_ok = _ping_host(host, timeout=5.0)

    return result


def check_hosts(
    hosts: list[tuple[str, int]],
    max_workers: int = 10,
    probe_timeout: float = 3.0,
    scan_timeout: float = 5.0,
) -> list[HostResult]:
    """并行检测多个主机。"""
    results: list[HostResult] = []

    def _check(h: str, p: int) -> HostResult:
        return check_host(h, p, probe_timeout=probe_timeout, scan_timeout=scan_timeout)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_check, h, p): (h, p) for h, p in hosts}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:  # noqa: BLE001
                h, p = futures[future]
                results.append(HostResult(host=h, primary_port=p))
    return results


# ── 报告生成 ────────────────────────────────────────────────────────────────


def _classify(host_result: HostResult) -> str:
    """分类：reachable / port_discovered / host_alive / dead"""
    if host_result.primary_reachable:
        return "reachable"
    if host_result.discovered_ports:
        return "port_discovered"
    if host_result.ping_ok:
        return "host_alive"
    return "dead"


def generate_report(
    results: list[HostResult], manifest_path: str = ""
) -> str:
    """生成 Markdown 端口检测报告。"""
    lines = ["# 端口连通性检测报告", ""]
    if manifest_path:
        lines.append(f"- 来源: `{manifest_path}`")
    lines.append(f"- 检测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 检测主机数: {len(results)}")
    lines.append("")

    # 按分类统计
    classified: dict[str, list[HostResult]] = {}
    for r in results:
        cat = _classify(r)
        classified.setdefault(cat, []).append(r)

    total_reachable = len(classified.get("reachable", []))
    total_discovered = len(classified.get("port_discovered", []))
    total_alive = len(classified.get("host_alive", []))
    total_dead = len(classified.get("dead", []))

    lines.append("## 汇总")
    lines.append("")
    lines.append(f"| 分类 | 数量 | 说明 |")
    lines.append(f"|------|------|------|")
    lines.append(
        f"| ✅ 主端口可达 | {total_reachable} | API 返回的端口可直接连接 |"
    )
    lines.append(
        f"| 🔍 发现隐藏端口 | {total_discovered} | 主端口不通，但发现其他开放端口 |"
    )
    lines.append(
        f"| ⚠️ 主机在线无端口 | {total_alive} | Ping 通但 TCP 端口全关 |"
    )
    lines.append(
        f"| ❌ 完全不可达 | {total_dead} | 主机离线或防火墙拦截 |"
    )
    lines.append("")

    # 主端口可达
    if total_reachable:
        lines.append("## ✅ 主端口可达")
        lines.append("")
        lines.append("| 主机 | 端口 | 响应时间 | Banner |")
        lines.append("|------|------|----------|--------|")
        for r in classified.get("reachable", []):
            for p in r.all_open_ports:
                lines.append(
                    f"| {p.host} | {p.port} | {p.response_time:.2f}s | {p.banner[:60]} |"
                )
        lines.append("")

    # 发现隐藏端口
    if total_discovered:
        lines.append("## 🔍 发现隐藏端口（主端口不通）")
        lines.append("")
        lines.append("| 主机 | 原端口 | 发现端口 | 服务 | 响应时间 |")
        lines.append("|------|--------|----------|------|----------|")
        for r in classified.get("port_discovered", []):
            for p in r.discovered_ports:
                lines.append(
                    f"| {p.host} | {r.primary_port} | {p.port} | "
                    f"{p.service or p.banner[:30]} | {p.response_time:.2f}s |"
                )
        lines.append("")

    # 完全不可达
    if total_dead:
        lines.append("## ❌ 完全不可达（建议跳过）")
        lines.append("")
        for r in classified.get("dead", []):
            host_str = r.host
            if r.primary_port:
                host_str += f":{r.primary_port}"
            lines.append(f"- {host_str}")
        lines.append("")

    # 建议
    lines.append("## 建议")
    lines.append("")
    if total_discovered > 0:
        lines.append(
            f"- 发现 {total_discovered} 个主机有隐藏端口，"
            f"建议更新 manifest 中的 target_port 后重新尝试"
        )
    if total_dead > 0:
        lines.append(
            f"- {total_dead} 个主机完全不可达，建议标记为 INFRA_BLOCKED 跳过"
        )
    if total_alive > 0:
        lines.append(
            f"- {total_alive} 个主机在线但无端口开放，"
            f"可能是防火墙策略或服务尚未启动"
        )
    lines.append("- 优先处理主端口可达的题目，再处理发现隐藏端口的题目")
    lines.append("")

    return "\n".join(lines)


def generate_json_report(results: list[HostResult]) -> str:
    """生成 JSON 格式报告。"""
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_hosts": len(results),
        "results": [r.to_dict() for r in results],
        "summary": {
            "reachable": sum(1 for r in results if r.primary_reachable),
            "port_discovered": sum(
                1 for r in results if not r.primary_reachable and r.discovered_ports
            ),
            "host_alive": sum(
                1
                for r in results
                if not r.any_reachable and r.ping_ok
            ),
            "dead": sum(1 for r in results if not r.any_reachable and not r.ping_ok),
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ── 从 manifest 读取题目列表 ────────────────────────────────────────────────


def _load_entries(platform: str | Path) -> list[dict]:
    """从平台路径加载挑战条目。"""
    p = Path(platform).expanduser()
    if p.is_file():
        # 直接 JSON
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: invalid JSON in {p}: {e}", file=sys.stderr)
            sys.exit(2)
        entries = data.get("challenges", []) if isinstance(data, dict) else []
        if not entries and isinstance(data, list):
            entries = data
        if not entries:
            print(f"error: no challenges found in {p}", file=sys.stderr)
            sys.exit(2)
        return entries
    # 目录：尝试加载 manifest
    if p.is_dir():
        for name in ("platform.json", "manifest.json", "challenges.json"):
            mf = p / name
            if mf.is_file():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                entries = data.get("challenges", []) if isinstance(data, dict) else []
                if entries:
                    return entries
        # 子目录 challenge.json
        entries = []
        for sub in sorted(p.iterdir()):
            if sub.is_dir():
                cf = sub / "challenge.json"
                if cf.is_file():
                    try:
                        entry = json.loads(cf.read_text(encoding="utf-8"))
                        if isinstance(entry, dict) and "id" in entry:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        if entries:
            return entries
        print(f"error: no challenges found in {p}", file=sys.stderr)
        sys.exit(2)
    print(f"error: path not found: {p}", file=sys.stderr)
    sys.exit(2)


def _extract_hosts(entries: list[dict]) -> list[tuple[str, int]]:
    """从条目提取 (host, port) 列表。"""
    hosts: list[tuple[str, int]] = []
    for entry in entries:
        host = str(entry.get("target_host", "") or "").strip()
        port = int(entry.get("target_port", 0) or 0)
        if host:
            hosts.append((host, port))
    return hosts


# ── CLI 入口 ────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="CTF 端口连通性快速检测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("platform", nargs="?", help="manifest 文件或平台目录")
    parser.add_argument(
        "--host", help="指定单个目标主机（与 --ports 配合）"
    )
    parser.add_argument(
        "--ports", help="指定端口列表，逗号分隔（与 --host 配合）"
    )
    parser.add_argument(
        "--nmap", action="store_true", help="启用 nmap 深度扫描（需安装 nmap）"
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON 格式输出"
    )
    parser.add_argument(
        "--output", "-o", default="port_check_report.md", help="报告输出路径"
    )
    parser.add_argument(
        "--timeout", type=float, default=3.0, help="单端口超时（秒）"
    )
    parser.add_argument(
        "--scan-timeout", type=float, default=5.0, help="扫描总超时（秒）"
    )
    parser.add_argument(
        "--workers", type=int, default=10, help="并行检测数"
    )

    args = parser.parse_args()

    # 收集待检测的目标
    hosts: list[tuple[str, int]] = []

    if args.host:
        # 指定主机模式
        if args.ports:
            for p_str in args.ports.split(","):
                p_str = p_str.strip()
                if p_str.isdigit():
                    hosts.append((args.host, int(p_str)))
        else:
            hosts.append((args.host, 0))
    elif args.platform:
        entries = _load_entries(args.platform)
        hosts = _extract_hosts(entries)
        if not hosts:
            print("warning: no target_host/target_port found in manifest", file=sys.stderr)
            # 从 entries 提取唯一主机
            seen = set()
            for entry in entries:
                host = str(entry.get("target_host", "") or "").strip()
                if host and host not in seen:
                    seen.add(host)
                    hosts.append((host, 0))
            if not hosts:
                print("error: no hosts to check", file=sys.stderr)
                sys.exit(2)
        print(f"检测 {len(hosts)} 个目标 ...")
    else:
        parser.print_help()
        sys.exit(2)

    # 运行检测
    print(f"并行检测中 (workers={args.workers}) ...")
    start = time.time()
    results = check_hosts(
        hosts,
        max_workers=args.workers,
        probe_timeout=args.timeout,
        scan_timeout=args.scan_timeout,
    )
    elapsed = time.time() - start

    # 输出报告
    if args.json:
        print(generate_json_report(results))
    else:
        report = generate_report(results, manifest_path=args.platform or "")
        if args.output:
            out_path = Path(args.output)
            out_path.write_text(report, encoding="utf-8")
            print(f"报告已保存: {out_path}")
        print(report)

    print(f"\n检测完成: {len(results)} 主机, {elapsed:.1f}s")

    # 返回码：有至少一个可达主机则 0
    any_ok = any(r.any_reachable for r in results)
    sys.exit(0 if any_ok else 1)


if __name__ == "__main__":
    main()