"""make_data — misc-bigscan-01 数据生成器（确定性，seed 固定）。

为什么不把 scan.log 直接放进仓库：4 MB 文本进 git 是纯负担，且
「难题 holdout 必须可复现」这一条靠 seed 保证比靠二进制文件更硬 ——
任何人 `python make_data.py` 都能得到逐字节相同的语料，能独立验证
"solver 解出的是这道题，而不是我偷偷换过的题"。

语料设计（四件事同时成立，缺一不可）：

1. **大** —— 约 4 MB / 15,000 台主机 / 110,000 行。工具在 20,000 字节处
   截断且不带指针，直接读整个文件必然丢掉目标行。这正是 P0.1 要暴露的场景。
2. **目标不在头部也不在尾部** —— 命中行埋在 65% 深度处。这样
   "读开头碰运气"和"读结尾碰运气"都不成立，只有过滤才能拿到。
3. **端口不构成答案** —— 目标在 8443，而另有 35 台诱饵主机也开 8443、
   banner 里也带 base64（解码后是运维噪音）。`grep 8443` 会得到 36 台，
   必须再按"备份目录列表"这个**服务属性**收敛。若只给目标一台开 8443，
   本题会退化成 `grep 一个端口号`，失去难度。
4. **命中行不含关键字** —— 它里面没有 "flag" / "secret" 字样（实测
   `scan.log` 里 "flag" 出现 0 次），只有一个 base64 blob。关键字 grep 无效。

**本题的性质要说清楚：它考的是「工具输出纪律」，不是推理。** 一个不分块、
直接 read_file 的 solver 会稳定失败，且失败原因是工具层截断而非想不出来。
这正是 P0.1（工具输出落盘）要修的病灶 —— 所以这道题是 P0.1 的探针，
不是"难题"的代表。推理难度由 reverse-obfchain-01 / forensics-brutelog-01 承担。

诚实说明一处刻意的简化：真 nmap 的 banner 折行规则复杂，这里用固定的
`| http-backup:` / `|_http-title:` 形态。真实感让位于确定性 —— holdout 的
可复现性优先于拟真度，因为要用它做前后对照。
"""

from __future__ import annotations

import base64
import random
from pathlib import Path

TARGET_PORT = 8443

# flag 只 base64 一层 —— 难度来自"找到它"，不来自"解开它"。
# holdout 不该把难度堆在密码学小花样上。
FLAG = "flag{backup_dir_left_open_2026}"
BLOB = base64.b64encode(FLAG.encode()).decode()

# 诱饵 base64 串：解码后是运维噪音，不含 flag。
# 它们让 "把所有 base64 都解一遍" 这条捷径变贵但不至于不可行 ——
# 捷径被允许，只是不够划算。
_DECOY_PLAINTEXT = [
    "maintenance window 02:00-04:00 UTC",
    "internal wiki: /wiki/net/inventory",
    "contact netops before touching 10.20.0.0/16",
    "cert rotates on the first monday",
    "this host is decommissioned, do not page",
    "vlan 41 is the lab, prod is vlan 40",
    "backup job runs at 03:15 via cron",
    "if you can read this, the ACL is still wrong",
]

_SERVICES = [
    ("22/tcp", "open", "ssh", "OpenSSH 8.9p1 Ubuntu 3ubuntu0.6"),
    ("80/tcp", "open", "http", "nginx 1.24.0"),
    ("443/tcp", "open", "ssl/http", "nginx 1.24.0"),
    ("3306/tcp", "open", "mysql", "MySQL 8.0.36"),
    ("6379/tcp", "open", "redis", "Redis key-value store 7.2.4"),
    ("8080/tcp", "open", "http-proxy", "Apache Tomcat/Coyote JSP engine 1.1"),
    ("9200/tcp", "open", "http", "Elasticsearch REST API 8.13.0"),
]

HOST_COUNT = 15000
TARGET_INDEX = int(HOST_COUNT * 0.65)   # 65% 深度 —— 本题的题眼
DECOY_8443_HOSTS = 35                   # 见模块 docstring 第 3 条


def _ip_for(index: int) -> str:
    """下标 → IP。**唯一真相**，不许另外写死一个 IP 常量。

    初版这里写死过 ``TARGET_IP = "10.20.7.143"``，而 TARGET_INDEX 实际
    对应 10.20.38.22 —— 那个常量从不匹配任何主机，只用来打日志，于是
    "日志说 10.20.7.143、实际命中 10.20.38.22" 静默共存了很久。是本
    fixture 的参考解把 IP 打出来才暴露的。派生 > 并列常量。
    """
    return f"10.20.{(index // 256) % 59}.{index % 256}"


TARGET_IP = _ip_for(TARGET_INDEX)


def _decoy_8443_indices(rng: random.Random) -> set[int]:
    """挑 35 台诱饵主机开 8443 —— 排除目标本身。"""
    pool = [i for i in range(HOST_COUNT) if i != TARGET_INDEX]
    return set(rng.sample(pool, DECOY_8443_HOSTS))


def _build_scan_log() -> str:
    rng = random.Random(20260911)
    out: list[str] = [
        "Starting Nmap 7.94 ( https://nmap.org ) at 2026-09-11 03:14 UTC",
        f"Nmap scan report for 10.20.0.0/16 ({HOST_COUNT} hosts up)",
        "",
    ]
    decoy_8443 = _decoy_8443_indices(rng)

    for i in range(HOST_COUNT):
        out.append(f"Nmap scan report for {_ip_for(i)}")
        out.append(f"Host is up ({rng.uniform(0.0004, 0.008):.4f}s latency).")

        picks = rng.sample(_SERVICES, rng.randint(1, 3))

        if i == TARGET_INDEX:
            picks = [s for s in picks if s[0] != f"{TARGET_PORT}/tcp"]
            picks.append((f"{TARGET_PORT}/tcp", "open", "ssl/http", "Jetty 9.4.53"))
        elif i in decoy_8443:
            picks = [s for s in picks if s[0] != f"{TARGET_PORT}/tcp"]
            picks.append((f"{TARGET_PORT}/tcp", "open", "ssl/http", "Jetty 9.4.53"))

        closed = 1000 - len(picks)
        out.append(f"Not shown: {closed} filtered tcp ports (no-response)")
        out.append("PORT     STATE SERVICE  VERSION")
        for port, state, svc, ver in sorted(picks, key=lambda s: int(s[0].split("/")[0])):
            out.append(f"{port:<8} {state:<5} {svc:<8} {ver}")

        # 诱饵 8443 主机：banner 里也有 base64，但解码后是运维噪音。
        # 它与命中行的**唯一**区别是有没有 "backup" 这个服务属性。
        if i in decoy_8443:
            decoy = base64.b64encode(rng.choice(_DECOY_PLAINTEXT).encode()).decode()
            out.append(f"|_http-title: Maintenance [{decoy}]")

        # 此外还有一批普通主机（非 8443）也带 base64 标题，作为第二层噪音。
        elif rng.random() < 0.33:
            decoy = base64.b64encode(rng.choice(_DECOY_PLAINTEXT).encode()).decode()
            out.append(f"|_http-title: Maintenance [{decoy}]")

        # 命中行：唯一一个把 base64 放进「备份目录列表」的。
        # 注意它不再有任何其他标记 —— 找不出它就是找不出。
        if i == TARGET_INDEX:
            out.append(f"| http-backup: /var/www/backup/ [{BLOB}]")

        out.append("")

    out.append(
        f"Nmap done: {HOST_COUNT} IP addresses ({HOST_COUNT} hosts up) "
        "scanned in 4903.12 seconds"
    )
    return "\n".join(out) + "\n"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="生成 misc-bigscan-01 的 scan.log")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent,
                    help="输出目录（默认 fixture 目录；runner 传 work_dir）")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    data = _build_scan_log()
    (args.out / "scan.log").write_text(data, encoding="utf-8")

    encoded = data.encode("utf-8")
    offset = encoded.index(b"http-backup")
    print(f"scan.log: {len(encoded):,} bytes, {data.count(chr(10)):,} 行")
    print(f"命中行偏移 {offset:,} = {100 * offset / len(encoded):.1f}% 深度")
    print(f"8443 主机数（含 {DECOY_8443_HOSTS} 台诱饵）: "
          f"{data.count('8443/tcp')}")
    print(f'"flag" 字面出现次数: {encoded.lower().count(b"flag")}')


if __name__ == "__main__":
    main()
