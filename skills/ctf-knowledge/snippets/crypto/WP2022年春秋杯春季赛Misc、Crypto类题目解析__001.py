# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/【WP】2022年春秋杯春季赛Misc、Crypto类题目解析.md
# TITLE: 【WP】2022年春秋杯春季赛Misc、Crypto类题目解析
# CATEGORY: crypto

data = open('alien.png','rb').read()
flag = ''
pos = data.index(b'IDAT')
data = data[pos+5:]
while 1:
    try:
        pos = data.index(b'IDAT')
        flag += str(hex(data[pos-5])[2:].zfill(2))
        data = data[pos+5:]
    
except:
        f1 = open('out.rar','w')
        f1.write(flag)
        exit(1)
f = open('out.txt','r').readlines()
f1 = open('secret.txt','w+')
for i in range(len(f)):
    if(len(f[i]) == 1):
        f1.write('00')
    else:
        tmp = str(hex(int(f[i]))[2:].zfill(2))
        f1.write(tmp)
f = open('ip.txt','r').readlines()
for i in range(len(f)):
    if('14.215.177.38' in f[i]):
        print('0',end='')
    else:
        print('1',end='')
flag{efaaf34db0bad8e1888e8f671f3cb7ab}
from PIL import Image
import os
from tqdm import tqdm
pic = Image.new('RGB',(4000,4000),(255,255,255))
pt = os.listdir('./img')

for i in tqdm(range(len(pt))):
    f = open(f'./img/{pt[i]}','rb').read()
    w,h = f[6],f[8]
    img = Image.open(f'./img/{pt[i]}')
    pic.paste(img,(32*w,18*h))
pic.show()
(iX)%)E!9Q)!rd0)98j4599$99!!9CE,EKYR$)@IUpeef8d$&0lh94*([RCQ0#1TlPKf-5LLaTF%J4I13YRNAI3%m`Jjhb&TSi!'QJ[rRq3jKq6rqjZMAijqII2E(crp2%ql$r1dHCbRpI%mGHIcY0h2dmh$BIbQfkGj'Xm1YbIc0-LUHkr(GTlqqh1HfZi`XN#IYPUmZT2*S1YLRKSpYmhKRl9qX4f,ePrdjA[XbIe9(mpXfLcM(MYfipSXBNIXVpmIPJqaX@l(Yq'A9Hb%jGM&+LG`(h&d*iIEUh"816DAq[3Zc(MqU!$(Ib0Il3S%*+E8qp&r5chK6[EA#R6e93DCc1Ccl!%DUkr1PBJ`(jSA&"S&BaMP"F$i2*lp(kcG"kGhSiZ!b%1Sm`SIE-EPPFGkl5rMD@3'm0bhLQbiF,",B4''1'bI!pYHB@--hZ4*V+4&)+63+*KKF0,fT%hi[0`(NH&8d'%l[V9GSG$Y)JB5X)Vdr*GS"fR3`Q@KES+5+(b3--L@mPL,28L$EK"TPlHklH(j8i5iHG3V!DbN4E46Ca8Q)%a#BfIaSJK3)CMYNer""l(hZRFXE#JK`98r4TSi!RPJfqk0CKE'+"f"1*BZ!8A1EZ1TF6+HD2V#XKMHH4%3%!9EpLIH$Me#$PQfqX6#EQIC5S!N6#E%")hJYU5Fi,ZX&6XD)R0ML'fUY1cJT*61-i'![6@TH`Y1pQ4!TB$*qYL!8Je@V--PABJ&%%1Gi#R"V(BN!3%NK%[#eQ)qfG1pEkdK2B)%JD*0B)bD0eLY2RAR[J8NhES,D9XL$'l$bJ@(5P#4e%-f"'NF[8UNiA9eTb3-D[,#aZ$"5P,EI2CAe!+%kbmQJU!)%#C!5EA1TKD,h2J601S#D+Y6`$SN"%pa*1Ze"B5a(ZGEU9ML93KJVHkQ25$Cr6,hF)F6QHk(fFB-J6#Nk&aJJZ9MN)#CfbUTbV4DU3P9BXehJ%#S9@N3dJI9m+%8!CkYffI(jQb8#Dr`a$C%5XC!CeNKRGDB16(2%3V"1lL`Sj$TL3+A2bZJ#8#P2YI4)Jh#UiAjk0$B$3YB0hcjchZJ0G`!+G%"BGZq`)'C@$Hp6dk1jLPAa6!SX'CSSZ%MT%m[KRT,6'6U1NMTN6fIiCGQCA6dRL)%$IqlfPmRC$8jc`H'U0&"38B(C[APljAeQMhFc6L(Ea9j"DbXD)(IE)Ji+$XUh-fHiP3!e)`(R%#&'kY#`P-ASVTee5b40Y`HXbT43eCN65Y2IlS4MIFe6qZ4@1Qa0-iKDNcG$Bpq,3KCiL(([6LVKLKcU("*bV4'JV6K2UPG5"KBJ%N0apCeEY!QQY3%lL1&rR0qel`JF+T&Ci+D`,#1'j0kDRj*cE-lk`ZAEL8j-d'NHPFdU(J[%R0#5R+'$m,N5Uc82(@EX"G5VMD,DZ!FjI#Fr4DHB#0VSATZ&L5[@1M6!BU1fH3'U)L`eUXB)TP-Z[$dS2&+L+T,bX%S1mp3N+JN3%$6l-F#d%Y!BaY03Pd"5@42mk"h,iqL*VQJJkiP4h83p'6+iJ&JTjqJaN(%B9FpH8"G4Y9b,+afbb@6kJI%kjL4)C,)RNI39hh)3PZBE-5I[FcR4*P88H#YZV8kDE8"Rd5Bl8V8H1C8pM60Z5#ic5`0**'#"84)fHUi*'M*+0RcS9LJ@9a*1d123e`1CbXfFI!Kc!h"Lr2mBdibC[F1$EGX)8L*G*eD&L6[M#!9ai6Jj-$C)k8)(,iNK*bk0L@H2'!fPh%1jl6bl1N+@6N#30iR%[R&Yh'L3G"qK9peD6E$MU1ecpXHeDk6l"(`5(+iV*1k6R,NAL00b2,SjZZMlQ*r@1ar!)XfL'$B$!!!
ROTATION_9:??????☺??✅?????☂???????❓❓??????????????????⏩??☀??????????✖??????????☀??☺?☺?☀?????????❓?????⌨?????????⏩????⏩?????⏩⏩??????☀??⏩☂????????????☺????❓❓⏩???☺????????????????????????????✉????✉⌨☀✖☀?????✅????✅?????????????☂?☺???????⏩???❓?☺????☂??????✖?✉???????????????????????????????☀?☀?☂???????❓❓??????❓??❓????????☺??☺??✅????????????✖✅?❓?☂✉?❓?????✉???✖?????✅???????????????????✖☃?☃☂???????????????❓?????????☂⏩????☀??☺??☃???????????✖????☃???⌨?⌨??✅???⌨????☀?????????????❓???✉?☺??✖????☀??☺??⌨?????????????????????☂☃??????⏩☂????????⌨☺☂????????????✅☀????✅????☺?????☀???????❓???????????✖?????☂?????✖????✅???☺?????☀?????⌨???????????????❓⏩?✅??☺☺???⌨????????☀???⌨????⌨????☂????✖????????✉???☂????✉????☀?☺?????⌨??✅??❓??????????✖????✉???????????????✅?????????????☀???????????⌨?????☃?☂??⌨?????☺???????❓?⌨???????✅?????????????????☺??????⏩??✖✖???????????????☂??☺????????⌨???⌨??⏩ℹℹ
佛又曰：楞迦羯伊醯埵娑娑伽度呼吉娑尼嚧楞耶夜舍嚧咩菩墀穆提烁皤皤醯菩唵无阇无无遮孕伽利孕卢阇怛罚怛唵提卢墀陀怛数谨墀输数婆穆罚阇菩楞栗楞陀栗钵他悉他罚墀咩俱蒙菩伽醯南驮穆俱度摩钵数沙阿俱舍数佛佛无室写俱佛嚧他南皤罚羯嚧烁提孕遮地驮苏写栗谨地数萨曳豆摩阇豆蒙他喝卢耶写参栗咩那耶帝哆数参驮伊曳南婆伽穆沙卢钵菩怛豆那蒙陀摩呼度参提嚧咩输沙度遮菩南谨钵提尼参迦夜无吉娑埵钵萨埵钵嚧咩哆耶墀怛穆烁利曳咩俱驮无呼啰钵墀写蒙阿埵漫漫
0.0.17.0.7.618206855040.0.16300.102.118.1973825.91361.115.110.12.19.7146.50.92.5701.3140589212.110.70.110.2785.6936.13.55.38.8674.54.14758.5
0011000791feffffff0000ff2c6676f8bc4185c961736e0c13b76a325cac458bd9c6ad1c6e466e9561b6180d3726c36236f32605
flag{adaf9c0b-5281-416c-983d-e06148cd016f}
dlp_dct = {sub_gen^i:F(i) for i in range(order)}

A = Matrix(F, m, n)
v = vector(F, m)

for i in range(m):
    for j in range(n):
        A[i, j] = dlp_dct[power_mod(cipher[i][0][j], t, q)]
    v[i] = dlp_dct[power_mod(cipher[i][1], t, q)]

x = A.solve_right(v)
prime =  2141
def add(msg1,msg2):
    return [(x+y)%prime for x,y in zip(msg1,msg2)]

def multi(msg1,msg2):
    out = []
    for l in msg1:
        s = 0
        for x,y in zip(l,msg2):
            s += (x*y)%prime
            s %= prime
        out.append(s)
    return out
def genkey(leng):
    l = [[] for i in range(row)]
    for x in range(row):
        for i in range(leng):
            l[x].append(random.randint(0,511))
    return l

key = genkey(len(flag1))
print key

cipher1 = multi(key,flag1)

cipher2 = multi(key,flag2)
noise = [random.randint(0,6) for i in range(row)]
print add(noise,cipher2)
ma = ...
res0 =[1702, 795, 740, 373, 535, 1308, 1050, 502, 40, 672, 1354, 1843, 515, 231, 774, 65, 978, 1340, 455, 2137, 733, 307, 1604, 723, 1023, 1253, 275, 1817, 404, 2035, 267, 1475, 14, 2127, 15, 487, 317, 757, 290, 541, 100, 951, 2049, 1042, 1404, 1676, 655, 1460, 1532, 273, 916, 1454, 1690, 1628, 1751, 1656, 139, 156, 2102, 264, 243, 455, 1564, 2072]
row = 64 
prime = 2141 
column= 21 
R = IntegerModRing(prime)
M = Matrix(R, ma)
cc0 = vector(R,res0)

ingredients = M.solve_right(cc0)
print("Ingredients: {}".format(ingredients))
m1=''
for i in range(len(ingredients)):
    m1+=chr(ingredients[i])
print m1
ma = ...
res = [884, 1584, 681, 1713, 1916, 609, 1840, 177, 1723, 1049, 254, 864, 1671, 121, 2021, 1353, 1290, 1891, 556, 1786, 1553, 1548, 727, 1967, 1800, 422, 1559, 1290, 642, 1406, 441, 1928, 395, 279, 1125, 1273, 99, 1131, 395, 76, 733, 416, 924, 571, 506, 822, 877, 887, 860, 1755, 1385, 1861, 1754, 1851, 1046, 1724, 1866, 1427, 378, 351, 146, 1367, 756, 505]
from sage.modules.free_module_integer import IntegerLattice
row = 64 
prime = 2141 
column= 21 
W=matrix(ZZ,ma)
W = W.T
cc= vector(ZZ,res)

# Babai's Nearest Plane algorithm
def Babai_closest_vector(M, G, target):
    small = target
    for _ in xrange(5 ):
        for i in reversed(range(M.nrows())):
            c = ((small * G[i]) / (G[i] * G[i])).round()
            small -=  M[i] * c
    return target - small

A1=matrix.identity(21 )
Ap=matrix.identity(row)*prime 
B=block_matrix([[Ap],[W]])  
lattice = IntegerLattice(B, lll_reduce=True)
print("LLL done")
gram = lattice.reduced_basis.gram_schmidt()[0]
target = vector(ZZ, res)
re = Babai_closest_vector(lattice.reduced_basis, gram, target)
print("Closest Vector: {}".format(re))

R = IntegerModRing(prime)
M = Matrix(R, ma)

ingredients = M.solve_right(re)
print("Ingredients: {}".format(ingredients))

m2=''
for i in range(len(ingredients)):
    m2+=chr(ingredients[i])
print m2
def pow1():
    io.recvuntil("XXXX+")
    suffix = io.recv(16).decode("utf8")
    io.recvuntil("== ")
    cipher = io.recvline().strip().decode("utf8")
    proof = mbruteforce(lambda x: sha256((x + suffix).encode()).hexdigest() ==
                        cipher, table, length=4, method='fixed')
    io.sendlineafter("XXXX :", proof) 
    return cipher
from sage.all import *
from hashlib import sha256
import string
from pwnlib.util.iters import mbruteforce
table = string.ascii_letters+string.digits

n0 = 30798082519452208630254982405300548841337042015746308462162479889627080155514391987610153873334549377764946092629701
g = 64146569863628228208271069055817252751116365290967978172021890038925428672043

def TrainHash(msg):
    n = n0
    msg = map(ord,msg)
    for i in msg :
        n = g * (n+i)
        n = n & (1<<383)
    return n - 0xf5e33dabb114514

def pow1():
    io.recvuntil("XXXX+")
    suffix = io.recv(16).decode("utf8")
    io.recvuntil("== ")
    cipher = io.recvline().strip().decode("utf8")
    proof = mbruteforce(lambda x: sha256((x + suffix).encode()).hexdigest() ==
                        cipher, table, length=4, method='fixed')
    io.sendlineafter("XXXX :", proof) 
    return cipher

N = 250
K = 2**200
modd = 2**384

Mat = Matrix(ZZ, N + 1, N + 2)
for i in range(N+1):
    ge = ZZ(pow(g, N - i, modd))
    Mat[i, i] = 1
    Mat[i, N + 1] = ZZ(ge * K)
Mat[i, N + 1] = ZZ(K * modd)

Mat = Matrix(ZZ,Mat)
ml = Mat.LLL()[0]# change

if ml[-1] != 0: #检验是否成功
    print("Error Zero not reached,increse the K")
    exit()

change = [ml[i] for i in range(len(ml))]
print('The change is:n' + str(change))

base_str = 'a' * N
base = list(map(ord,base_str))
print("The base is:n" + str(base))

new = [base[i] - change[i] for i in range(N)]
for i in new:
    if i>384 or i<0:
        print("Need More Bytes!")
        exit()

new_str = ''.join(map(chr,new))
print("My new_str is:n" + str(new_str))

print(TrainHash(base_str))
print(TrainHash(new_str)) 
from pwn import*

io = remote("192.168.3.88" , 10012)
pow1()
print(io.recv())
io.sendline(base_str.encode())
io.sendline(new_str.encode())
io.interactive()
def pow1():
    io.recvuntil("XXXX+")
    suffix = io.recv(16).decode("utf8")
    io.recvuntil("== ")
    cipher = io.recvline().strip().decode("utf8")
    proof = mbruteforce(lambda x: sha256((x + suffix).encode()).hexdigest() ==
                        cipher, table, length=4, method='fixed')
    io.sendlineafter("XXXX :", proof) 
    return cipher
def Md00Plus(message: bytes):
    h0 = 0x114514ab
    h1 = 0x1919810a
    h2 = 0xa0189191
    h3 = 0xba415411

    R = (7, 12, 17, 22) * 4 + (5, 9, 14, 20) * 4 + (4, 11, 16, 23) * 4 + (6, 10, 15, 21) * 4
    K = (0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee,
         0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501, 0x698098d8,
         0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
         0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51,
         0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
         0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905,
         0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681,
         0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60,
         0xbebfbc70, 0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05,
         0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
         0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92,
         0xffeff47d, 0x85845dd1, 0x6fa87e4f, 0xfe2ce6e0, 0xa3014314,
         0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391)

    F = lambda x, y, z: ((x & y) | ((~x) & z))
    G = lambda x, y, z: ((x & z) | (y & (~z)))
    H = lambda x, y, z: (x ^ y ^ z)
    I = lambda x, y, z: (y ^ (x | (~z)))

    L = lambda x, n: ((x << n) | (x >> (32 - n))) & 0xffffffff
    W = lambda i4, i3, i2, i1: (i1 << 24) | (i2 << 16) | (i3 << 8) | i4
    reverse = lambda x: (x << 24) & 0xff000000 | (x << 8) & 0x00ff0000 | 
                        (x >> 8) & 0x0000ff00 | (x >> 24) & 0x000000ff

    ascii_list = list(map(lambda x: x, message))
    msg_length = len(ascii_list) * 8
    ascii_list.append(128)

    while (len(ascii_list) * 8 + 64) % 512 != 0:
        ascii_list.append(1)

    for i in range(8):
        ascii_list.append((msg_length >> (8 * i)) & 0xff)

    for i in range(len(ascii_list) // 64):
        a, b, c, d = h0, h1, h2, h3
        for j in range(64):
            if 0 <= j <= 15:
                f = F(b, c, d) & 0xffffffff
                g = j
            elif 16 <= j <= 31:
                f = G(b, c, d) & 0xffffffff
                g = ((5 * j) + 1) % 16
            elif 32 <= j <= 47:
                f = H(b, c, d) & 0xffffffff
                g = ((3 * j) + 5) % 16
            else:
                f = I(b, c, d) & 0xffffffff
                g = (7 * j) % 16
            aa, dd, cc = d, c, b
            s = i * 64 + g * 4
            w = W(ascii_list[s], ascii_list[s + 1], ascii_list[s + 2], ascii_list[s + 3])
            bb = (L((a + f + K[j] + w) & 0xffffffff, R[j]) + b) & 0xffffffff
            a, b, c, d = aa, bb, cc, dd
        h0 = (h0 + a) & 0xffffffff
        h1 = (h1 + b) & 0xffffffff
        h2 = (h2 + c) & 0xffffffff
        h3 = (h3 + d) & 0xffffffff
    h0, h1, h2, h3 = reverse(h0), reverse(h1), reverse(h2), reverse(h3)
    digest = (h0 << 96) | (h1 << 64) | (h2 << 32) | h3
    return hex(digest)[2:].rjust(32, '0'),ascii_list 

def md5ex(hash,message: bytes):
    reverse = lambda x: (x << 24) & 0xff000000 | (x << 8) & 0x00ff0000 | 
                        (x >> 8) & 0x0000ff00 | (x >> 24) & 0x000000ff
    hash = int(hash,16)
    h3 = reverse(hash&0xffffffff)
    hash >>= 32
    h2 = reverse(hash&0xffffffff)
    hash >>= 32
    h1 = reverse(hash&0xffffffff)
    hash >>= 32
    h0 = reverse(hash&0xffffffff)

    R = (7, 12, 17, 22) * 4 + (5, 9, 14, 20) * 4 + (4, 11, 16, 23) * 4 + (6, 10, 15, 21) * 4
    K = (0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee,
         0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501, 0x698098d8,
         0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
         0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51,
         0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
         0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905,
         0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681,
         0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60,
         0xbebfbc70, 0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05,
         0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
         0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92,
         0xffeff47d, 0x85845dd1, 0x6fa87e4f, 0xfe2ce6e0, 0xa3014314,
         0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391)

    F = lambda x, y, z: ((x & y) | ((~x) & z))
    G = lambda x, y, z: ((x & z) | (y & (~z)))
    H = lambda x, y, z: (x ^ y ^ z)
    I = lambda x, y, z: (y ^ (x | (~z)))

    L = lambda x, n: ((x << n) | (x >> (32 - n))) & 0xffffffff
    W = lambda i4, i3, i2, i1: (i1 << 24) | (i2 << 16) | (i3 << 8) | i4

    ascii_list = list(map(lambda x: x, message))
    msg_length = len(ascii_list) * 8 + 512
    ascii_list.append(128)

    while (len(ascii_list) * 8 + 64) % 512 != 0:
        ascii_list.append(1)

    for i in range(8):
        ascii_list.append((msg_length >> (8 * i)) & 0xff)

    for i in range(len(ascii_list) // 64):
        a, b, c, d = h0, h1, h2, h3
        for j in range(64):
            if 0 <= j <= 15:
                f = F(b, c, d) & 0xffffffff
                g = j
            elif 16 <= j <= 31:
                f = G(b, c, d) & 0xffffffff
                g = ((5 * j) + 1) % 16
            elif 32 <= j <= 47:
                f = H(b, c, d) & 0xffffffff
                g = ((3 * j) + 5) % 16
            else:
                f = I(b, c, d) & 0xffffffff
                g = (7 * j) % 16
            aa, dd, cc = d, c, b
            s = i * 64 + g * 4
            w = W(ascii_list[s], ascii_list[s + 1], ascii_list[s + 2], ascii_list[s + 3])
            bb = (L((a + f + K[j] + w) & 0xffffffff, R[j]) + b) & 0xffffffff
            a, b, c, d = aa, bb, cc, dd
        h0 = (h0 + a) & 0xffffffff
        h1 = (h1 + b) & 0xffffffff
        h2 = (h2 + c) & 0xffffffff
        h3 = (h3 + d) & 0xffffffff
    h0, h1, h2, h3 = reverse(h0), reverse(h1), reverse(h2), reverse(h3)
    digest = (h0 << 96) | (h1 << 64) | (h2 << 32) | h3
    return hex(digest)[2:].rjust(32, '0'),ascii_list 

from pwn import*
import string
from pwnlib.util.iters import mbruteforce
from hashlib import*
table = string.ascii_letters+string.digits

io = remote("127.0.0.1",10114)

def pow1():
    io.recvuntil(b'XXXX+')
    suffix = io.recv(16).decode("utf8")
    io.recvuntil(b'== ')
    cipher = io.recvline().strip().decode("utf8")
    proof = mbruteforce(lambda x: sha256((x + suffix).encode()).hexdigest() ==
                        cipher, table, length=4, method='fixed')
    io.sendlineafter(b'XXXX :', proof.encode())
    return cipher
pow1()

io.recvuntil(b'Thing:')
GreatThing = io.recv(16)

from Crypto.Util.number import*
io.recvuntil(b'REATTHING:')
Md00 = io.recv(32)
H = md5ex(Md00.decode(),GreatThing)[0].encode()
for i in range(1,26):
    Pad = Md00Plus(i*b'a')[1][i:]
    MSG = bytes(Pad) + GreatThing
    s = hex(bytes_to_long(MSG))[2:].encode()+b','+ hex(bytes_to_long(H))[2:].encode()
    io.sendline(s)
    print(i,io.recv())
    msg = io.recv()
    if b'flag' in msg:
        print(msg)
        break
io.interactive()
