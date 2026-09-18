# templates/ — Exp 模板索引

16 份可直接改造的 exp 模板。Pwn 用 pwntools（结尾 `io.interactive()`），Web 用 requests + argparse。
每个模板头部 docstring 写明用途/适用条件/用法；`# TODO: 改这里` 标注所有需按题修改处。

使用约定：
- Pwn 模板顶部集中 CONFIG 区（BINARY/LIBC/HOST/PORT 等），行号见下表"关键参数"列。
- Web 模板为 argparse 驱动，无需改源码即可跑（`-h` 看参数）；"关键参数"列给出 docstring 用法示例行号与少数行内 TODO。
- 验证方式：`python -m py_compile`（venv: `~/.fulilian/fulilian-agent/venv/bin/python`），16/16 通过。

## Pwn（8）

| 文件 | 场景 | 适用条件 | 关键参数 |
|---|---|---|---|
| pwn_ret2libc.py | 栈溢出 -> 泄露 GOT -> libc 基址 -> system("/bin/sh") | NX 开、有输出函数、有/可配 libc | CONFIG 区 L15-23：BINARY/LIBC/ARCH(64/32 开关)/OFFSET/gadget |
| pwn_tcache_poison.py | UAF/double free 改 tcache fd，任意地址分配写 | glibc 2.26+；2.32+ 走 safe-linking 分支；2.34+ 别打 hook | CONFIG 区 L17-23；Menu 选项号 L36 起 |
| pwn_srop.py | 短 payload/无 libc：sigreturn 恢复寄存器 execve("/bin/sh") | 64 位；pop rax(15)+syscall gadget；能拿栈泄露 | CONFIG 区 L15-21；泄露解析 L33 起 |
| pwn_orw.py | seccomp 禁 execve：open/read/write shellcode 读 /flag | seccomp 白名单含 ORW；有可执行内存 | CONFIG 区 L15-18；FLAG 路径 L18；投放点 L79 起 |
| pwn_fmtstr.py | 格式化字符串：偏移探测 + fmtstr_payload 任意写/泄露 | printf 族把输入当格式串；32/64 位通用 | CONFIG 区 L15-19；probe_offset L31；写入目标 L65 起 |
| pwn_ret2csu_stack.py | gadget 不足控 rdx/rsi/edi + 栈迁移(leave;ret)到 bss | 64 位、glibc<=2.33（有 __libc_csu_init）；溢出长度短 | CONFIG 区 L16-26：CSU_POP/CSU_CALL/LEAVE_RET/BSS |
| pwn_fsop_apple2.py | glibc 2.34+ 无 hook：伪造 FILE 走 _IO_wfile_jumps 调 system | 2.27~2.41，堆漏洞能把堆地址写进 _IO_list_all；exit 触发 | CONFIG 区 L19-25；Menu 选项号 L33 起；触发选项 L135 |
| pwn_heap_menu.py | 通用堆菜单脚手架 + UAF/double free/越界一键验证 | 菜单式堆题（add/del/edit/show），先验漏洞再接利用链 | CONFIG 区 L18-22（LOCAL 开关）；Menu 选项号 L29 起 |

## Web（8）

| 文件 | 场景 | 适用条件 | 关键参数 |
|---|---|---|---|
| web_php_filter_chain.py | LFI->RCE：iconv 编码链合成任意 PHP 代码；可绕死亡 exit | include 参数完全可控（php://filter 可用）| 用法示例 docstring L10-13；CLI：-u/-p/-c/--gen-only |
| web_ssti_probe.py | SSTI 多引擎探测一把梭 -> 判引擎 -> 对应 RCE | Jinja2/Twig/Smarty/ERB；回显渲染结果 | 用法示例 docstring L9-11；CLI：-u/-p/--rce/--cmd |
| web_jwt_kit.py | JWT 三合一：alg=none / 字典爆破 / kid 注入 | 目站 JWT 鉴权，有 token 样本 | 用法示例 docstring L12-14；CLI 子命令 none/crack/kid |
| web_ssrf_gopher.py | SSRF：gopher 打 Redis（webshell/cron）与 FastCGI RCE | gopher 放行（取决于客户端构建与协议白名单）；Redis 未授权/FPM 9000 可达 | 用法示例 docstring L9-14；CLI：--redis-mode/--docroot/--double |
| web_sqlmap_kit.py | sqlmap 命令速查 + 自研布尔/时间盲注拖库脚本 | 已定位注入点，页面真/假特征或 sleep 差异 | 用法示例 docstring L9-13；CLI：--cheat/--blind/--template |
| web_phar_gen.py | 生成带恶意 metadata 的 phar（GIF 头/gzip 伪装可选） | 文件操作函数可达 phar://；有 POP 链 | 用法示例 docstring L10-11；CLI：--class/--props/--gif/--gzip |
| web_oob_rce.py | 无回显 RCE：DNSLog/HTTP 外带命令变体 + webshell 落点探活 | 盲执行点；目标能出网（DNS 或 HTTP） | 用法示例 docstring L9-11；CLI：gen/shell 子命令 |
| web_pickle_pt.py | pickle 反序列化 payload 生成 + Node 原型链污染速查/打点 | pickle.loads 可控点；递归 merge/lodash.set | 用法示例 docstring L9-11；CLI 子命令 pickle/proto；gadget 表 L65 |

## 版本/环境提示
- Pwn 模板需 pwntools（靶机环境按需装）；Web 模板 requests 即可，JWT 用标准库手搓签名，无额外依赖。
- glibc 版本判据速记：tcache>=2.26、safe-linking>=2.32、无 __free_hook>=2.34、无 __libc_csu_init>=2.34。
- 所有模板假设：填对 CONFIG/CLI 参数后直接可跑；交互提示符、chunk 下标等题目差异处均已用 TODO 注明。
