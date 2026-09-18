# Pwn 知识卡

> 2024-2026 考点补充：glibc 2.34+ 无 hook 利用链、safe-linking、现场版本识别、largebin attack。

## 常用工具
- pwntools, gdb+pwndbg/gef, one_gadget, ROPgadget/ropper, seccomp-tools, checksec
- patchelf 换运行环境：`patchelf --set-interpreter ./ld-x.so --set-rpath . ./pwn`（复现远程 libc）
- libc 检索：libc.rip / libc-database（用泄露地址低 12 位比对 __libc_start_main 等符号偏移）

## glibc 版本现场识别（第一步必做）
- `strings libc.so.6 | grep "GNU C Library"`；libc 可执行时直接 `./libc.so.6` 运行打印版本
- 符号判版本：有 __free_hook/__malloc_hook → ≤2.33；有 tcache → ≥2.26；safe-linking → ≥2.32
- 只给二进制：泄露任意 libc 地址取低 12 bit 到 libc.rip 搜索，命中后再核对第二个符号确认
- 本地能通远程不通：先怀疑 libc/ld 版本不匹配，再怀疑利用链本身

## 常见漏洞
- 栈：ret2win / ret2shellcode / ret2libc / ROP / SROP / ret2csu / ret2dlresolve / 栈迁移
- 格式化字符串：`%p` 泄露栈、`%n` 任意写、GOT 覆写、按偏移批量写（fmtstr_payload）
- 堆：UAF、double free、off-by-one/off-by-null、tcache poisoning、fastbin attack、largebin attack
- 整数溢出/符号错误、数组越界、C++ 对象 UAF 劫持虚表
- seccomp 沙箱：`seccomp-tools dump` 看规则；禁 execve → ORW（open/read/write，或 sendfile 一次带出）

## tcache safe-linking（glibc 2.32+ 必背）
- fd 加密公式：fd = (存放位置地址 >> 12) ^ 目标指针（PROTECT_PTR 取 &e->next 的高位异或）
- 反解泄露 fd：next = fd ^ (该 chunk 地址 >> 12)；tcache 首 chunk 的 fd 明文为 0，泄露即得堆基址片段
- tcache poisoning：UAF 写 fd = (chunk_addr >> 12) ^ target；target 必须 16 字节对齐（否则 unaligned tcache chunk）
- 2.31 及以下直接写裸指针 fd；老 payload 迁移到 2.32+ 忘加异或项是最常见失败原因

## glibc 2.34+ 无 hook 替代链（必背）
- 背景：2.34 起 __free_hook/__malloc_hook 被移除，写入不再生效，别再浪费时间打 hook
- FSOP：伪造 _IO_FILE 结构体并让 _IO_list_all 指过去，exit/fflush 触发；vtable 必须过 _IO_vtable_check 白名单
- house of apple2：改 stdout 的 _wide_data，vtable 设 _IO_wfile_jumps，走 _IO_wfile_overflow→_IO_wdoallocbuf 任意函数调用（rdi=FILE，首 8 字节放 "/bin/sh"）
- house of cat：伪造完整 FILE 走 _IO_wfile_jumps 的 close/fsync 路径，常配 setcontext+61 控制全部寄存器
- house of botcake：tcache 满 + double free 合并出重叠 chunk，2.31/2.34 无 largebin 依赖的通用首选
- house of emma：2.35+ 用 _IO_2_1_stderr_ + wide_data + xor magic vtable；高版本 FSOP 主力之一
- house of force 已死：2.29+ top chunk size 有校验，别再怀旧
- exit handlers 劫持：__exit_funcs 链表函数指针经 PTR_MANGLE（xor fs:0x30 后 ROL 17），需先泄露 TLS pointer guard；或打 _dl_fini/tls_dtor_list
- 备选：__environ 泄露栈地址转 SROP/ROP；ld.so 的 _rtld_global/_dl_rtld_lock_recursive（部分版本可用）

## largebin attack
- 前提：unsorted bin chunk 被取出插入 largebin 触发整理，且该 largebin 中已有 chunk
- 篡改已有 chunk 的 bk / bk_nextsize，整理时向任意地址写入"新 chunk 的堆地址"
- 常打目标：_IO_list_all（配 house of apple2）、mp_.tcache_bins（伪造 tcache 扩容）、exit handler 链表项

## 保护与绕过
- NX→ROP/shellcode 放堆上；PIE→泄露或 partial write；Canary→先泄露后原样回填
- Partial RELRO→GOT 覆写；Full RELRO→改走 FSOP / exit handlers / ld.so 数据区

## 模板/资产路由
- 遇到基础栈溢出/ret2libc → templates/pwn_ret2libc.py（改 HOST/PORT 即用）
- 遇到 tcache/UAF/double free → templates/pwn_tcache_poison.py（改 HOST/PORT 即用）
- 遇到 payload 长度受限或无输出函数 → templates/pwn_srop.py（改 HOST/PORT 即用）
- 遇到 seccomp 禁 execve → templates/pwn_orw.py（改 HOST/PORT 即用）
- 遇到格式化字符串任意读写 → templates/pwn_fmtstr.py（改 HOST/PORT 即用）
- 遇到 gadget 不足需控 rdx 等寄存器 → templates/pwn_ret2csu_stack.py（改 HOST/PORT 即用）
- 遇到 glibc 2.34+ 堆题打 FSOP → templates/pwn_fsop_apple2.py（改 HOST/PORT 即用）
- 遇到菜单堆题(add/del/edit/show) → templates/pwn_heap_menu.py（改 HOST/PORT 即用）

## 常见思路
1. file + checksec → 跑一遍看交互 → 定位漏洞函数（gets/read/scanf、free 不置 NULL、格式串 %s）
2. 有 libc：按版本选链，≤2.33 优先 hook/GOT，≥2.34 优先 FSOP / exit handlers
3. 泄露 libc 基址：unsorted bin fd、puts(puts@plt)、_IO_2_1_stdout_ 残留指针
4. one_gadget 逐个试（注意 rsp+0x40==NULL 等约束），失败转 system("/bin/sh")
5. 拿不到 shell：大概率 seccomp 禁了 execve，直接转 ORW 读 /flag
6. 远程不通且版本已核对：检查 16 字节对齐、setcontext 偏移（+53/+61 因版本而异）

## 常用脚本结构
```python
from pwn import *
elf, libc = ELF('./chall'), ELF('./libc.so.6')
io = process('./chall')   # 或 remote(HOST, PORT)
# leak → libc.address = leak - offset → 构造 payload → io.sendlineafter(...) → getshell
io.interactive()
```

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`；无 shell 时用 ORW 直接读 /flag
