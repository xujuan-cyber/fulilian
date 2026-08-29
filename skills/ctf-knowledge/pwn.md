# Pwn 知识卡

## 常用工具
- pwntools, gdb + pwndbg/gef, one_gadget, ropper, ROPgadget, seccomp-tools, checksec
- patchelf, ld-linux 加载器, libc-database（libc-database / libc.blukat.me）

## 常见漏洞
- **栈溢出**: ret2win, ret2libc, ret2shellcode, ROP, SROP, BROP
- **堆溢出**: fastbin attack, tcache poison, unsorted bin attack, house of *系列
- **格式化字符串**: 任意读写（`%p`, `%n`, `%s`），GOT 覆写，栈地址泄露
- **整数溢出**: 绕过大小检查、数组越界
- **沙箱逃逸**: seccomp 规则绕过（only open/read/write → ORW shellcode）
- **FSOP**: File Stream Oriented Programming, _IO_FILE 结构体伪造

## 保护检查
- `checksec`: NX（栈不可执行）、PIE（地址随机化）、RELRO（GOT 保护）、
  Canary（栈保护）、FORTIFY
- 常见绕过：PIE → 泄露地址、Canary → 泄露+保持、RELRO partial → GOT 覆写

## 常见思路
1. 信息收集：`file <binary>`, `checksec`, `strings`, 运行看交互
2. 寻找漏洞点：输入长度、格式、堆管理操作
3. 泄露 libc 基址 → 查 libc-database → 定位 system/one_gadget
4. 构造 ROP chain / 利用堆原语
5. 如果沙箱限制 execve → 用 ORW shellcode 读 flag

## 常用脚本结构
```python
from pwn import *
elf = ELF('./chall')
libc = ELF('./libc.so.6')
io = process('./chall')  # 或 remote(host, port)
# 泄露地址 → 计算基址 → 覆盖返回地址/GOT → 触发
io.interactive()
```

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`