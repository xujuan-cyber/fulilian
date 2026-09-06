# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/Y老师的密码学_·_第一篇.md
# TITLE: Y老师的密码学 · 第一篇
# CATEGORY: crypto

#!/usr/local/bin/python
from Crypto.Util.number import *
from os import urandom

flag = open("flag.txt", "rb").read()
flag = bytes_to_long(urandom(16) + flag + urandom(16))

p = getPrime(512)
q = getPrime(512)
n = p * q
e = 0x10001
d = pow(e, -1, (p-1)*(q-1))
assert flag < n
ct = pow(flag, e, n)

print(f"{n = }")
print(f"{e = }")
print(f"{ct = }")

whileTrue:
    ct = int(input("> "))
    pt = pow(ct, d, n)
    out = ""
    if pt == flag:
        exit(-1)
    if pt % 3 == 0:
        out += "Fizz"
    if pt % 5 == 0:
        out += "Buzz"
    ifnot out:
        out = pt
    print(out)
from Crypto.Util.number import *
from pwn import *
# a=remote("be.ax",31100)
# l=a.recv().split(b'=')
# print(l)
# while True:
#     X = getPrime(10)
#     c = int(l[3][:-2])
#     n = int(l[1][:-2])
#     Y = (c * (X ** 65537)) % n
#     a.sendline(str(Y).encode())
#     print(X)
#     print(Y)
#     print(a.recvline())
n=10923590886634228827134658466234332962160546970259806875947299955117094723
2996590557964241534101853321789427925631360625471407190264507981047481840604
5770295033165358752485494005614706506946041594393587695948197211669743677637
1201851439874292252155611926493174569162636187926889061627634316983399923186
1189833
c=54154300348903111005066683187322110240325256042602814495907789220256344603
9329651492217054936857491785316431371347695833366523065193277532980043371316
2219549684070989291489469384068884401333991713653240631955340521542862833755
5863105880457193242611315359206147315741465280238895273742546724024586290588
394695
w=907
y=26641182241400186140764833732531788410188640530460941989584702007887972922
0893088977366572306324954901383970069683822351533581707241548687145888017505
0739702872878490121501943582580854230668238851423909090028374384975663116055
0184102438364341973285800800919002105937122573558829974207210810107339187277
577768
ct=1617872921486161438959529626097492037660629295223293116750255222467849722125817349217082369174984216697864465452996697846569528891027592080706141175012700498085383500035413467709314885420625836615662777908956038879208002465859460678671983566645413919704836898065353721740490145081034
flag=ct*inverse(w,n)%n
print(long_to_bytes(flag))
    #corctf{h4ng_0n_th15_1s_3v3n_34s13r_th4n_4n_LSB_0r4cl3...4nyw4y_1snt_f1zzbuzz_s0_fun}
from Crypto.Util.number import bytes_to_long, getPrime

# my NEW and IMPROVED secret sharing scheme!! (now with multivariate quadratics)

with open('flag.txt', 'rb') as f:
    flag = f.read()

s = bytes_to_long(flag)
p = getPrime(len(bin(s)))
print(p)
F = GF(p)
N = 1024

conv = lambda n: matrix(F, N, 1, [int(i) for i in list(bin(n)[2:][::-1].ljust(N, '0'))])

A = random_matrix(F, N, N)

for i in range(0, N):
    for j in range(0, i):
        A[i, j] = 0
B = random_matrix(F, N, 1)
C = matrix(F, [F(s)])

fn = lambda x: (x.T * A * x + B.T * x + C)[0][0]

L = []
for i in range(7):
    L.append(fn(conv(i + 1)))

print(L)
from Crypto.Util.number import *
p=1873089703968291141600166892623234932796169766648225659075834963115683566265697596115468506218441065194050127470898727249982614285036691594726454694776985338487833409983284911305295748861807972501521427415609
L=[676465814304447223312460173335785175339355609820794166139539526721603814168727462048669021831468838980965201045011875121145342768742089543742283566458551844396184709048082643767027680757582782665648386615861, 1472349801957960100239689272370938102886275962984822725248081998254467608384820156734807260120564701715826694945455282899948399224421878450502219353392390325275413701941852603483746312758400819570786735148132, 202899433056324646894243296394578497549806047448163960638380135868871336000334692955799247243847240605199996942959637958157086977051654225700427599193002536157848015527462060033852150223217790081847181896018, 1065982806799890615990995824412253076607488063240855100580513221962298598002468338823225586171107539104635808108356492123167315175110515086192932230998426512947581115358738651206273178867911944034690138825583, 1676559204037482856674710667663849447914859348633288513196735253002541076530170853584406282605482862202276451646974549657672382936948091649764874334064431407644457518190694888175499630744741620199798070517691, 13296702617103868305327606065418801283865859601297413732594674163308176836719888973529318346255955107009306239107173490429718438658382402463122134690438425351000654335078321056270428073071958155536800755626, 1049859675181292817835885218912868452922769382959555558223657616187915018968273717037070599055754118224873924325840103339766227919051395742409319557746066672267640510787473574362058147262440814677327567134194]
F = GF(p)
N = 1024
conv = lambda n: matrix(F, N, 1, [int(i) for i in list(bin(n)[2:][::-1].ljust(N, '0'))])
c=(L[6]-(L[2]+L[4]+L[5]-2*(L[0]+L[1]+L[3]))-(L[0]+L[1]+L[3]))%p
print(long_to_bytes(c))
    #corctf{mind your ones and zeroes because zero squared is zero and one squared is one}
import random

def random_alphastring(size):
    return"".join(random.choices(alphabet, k=size))

def add_key(key, block):
    ct_idxs = [(k_a + pt_a) % len(alphabet) for k_a, pt_a in zip([alphabet.index(k) for k in key], [alphabet.index(pt) for pt in block])]
    return"".join([alphabet[idx] for idx in ct_idxs])

def cbc(key, plaintext):
    klen = len(key)
    plaintext = pad(klen, plaintext)
    iv = random_alphastring(klen)
    blocks = [plaintext[i:i+klen] for i in range(0, len(plaintext), klen)]
    prev_block = iv
    ciphertext = ""
    for block in blocks:
        block = add_key(prev_block, block)
        prev_block = add_key(key, block)
        ciphertext += prev_block
    return iv, ciphertext
    
def pad(block_size, plaintext):
    plaintext += "X" * (-len(plaintext) % block_size)
    return plaintext

alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
bs = 16

message = open("message.txt").read().upper()
message = "".join([char for char in message if char in alphabet])
flag = open("flag.txt").read()
flag = flag.lstrip("corctf{").rstrip("}")
message += flag
assert all([char in alphabet for char in message])

key = random_alphastring(bs)
iv, ct = cbc(key, pad(bs, message))
print(f"{iv = }")
print(f"{ct = }")
iv = 'RLNZXWHLULXRLTNP'
ct = 'ZQTJIHLVWMPBYIFRQBUBUESOOVCJHXXLXDKPBQCUXWGJDHJPQTHXFQIQMBXNVOIPJBRHJQOMBMNJSYCRAHQBPBSMMJWJKTPRAUYZVZTHKTPUAPGAIJPMZZZDZYGDTKFLWAQTSKASXNDRRQQDJVBREUXFULWGNSIINOYULFXLDNMGWWVSCEIORQESVPFNMWZKPIYMYVFHTSRDJWQBTWHCURSBPUKKPWIGXERMPXCHSZKYMFLPIAHKTXOROOJHUCSGINWYEILFIZUSNRVRBHVCJPVPSEGUSYOAMXKSUKSWSOJTYYCMEHEUNPJAYXXJWESEWNSCXBPCCIZNGOVFRTGKYHVSZYFNRDOVPNWEDDJYITHJUBVMWDNNNZCLIPOSFLNDDWYXMYVCEOHZSNDUXPIBKUJIJEYOETXWOJNFQAHQOVTRRXDCGHSYNDYMYWVGKCCYOBDTZZEQQEFGSPJJIAAWVDXFGPJKQJCZMTPMFZDVRMEGMPUEMOUVGJXXBRFCCCRVTUXYTTORMSQBLZUEHLYRNJAAIVCRFSHLLPOANFKGRWBYVSOBLCTDAUDVMMHYSYCDZTBXTDARWRTAFTCVSDRVEENLHOHWBOPYLMSDVOZRLENWEKGAWWCNLOKMKFWWAZJJPFDSVUJFCODFYIMZNZTMAFJHNLNMRMLQRTJJXJCLMQZMOFOGFPXBUTOBXUCWMORVUIIXELTVIYBLPEKKOXYUBNQONZLPMGWMGRZXNNJBUWBEFNVXUIAEGYKQSLYSDTGWODRMDBHKCJVWBNJFTNHEWGOZFEZMTRBLHCMHIFLDLORMVMOOHGXJQIIYHZFMROGUUOMXBTFMKERCTYXFIHVNFWWIUFTGLCKPJRFDRWDXIKLJJLNTWNQIOFWSIUQXMFFVIIUCDEDFEJNLKLQBALRKEYWSHESUJJXSHYWNRNPXCFUEFRJKSIGXHFTKNJXSYVITDOGYIKGJIOOHUFILWYRBTCQPRPNOKFKROTFZNOCZXZEYUNWJZDPJDGIZLWBBDGZJNRQRPFFGOTGFBACCRKLAPFLOGVYFXVIIJMBBMXWJGLPOQQHMNBCINRGZRBVSMLKOAFGYRUDOPCCULRBE'

alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
bs = 16

import random

def random_alphastring(size):
    return"".join(random.choices(alphabet, k=size))

def add_key(key, block):
    ct_idxs = [(k_a + pt_a) % len(alphabet) for k_a, pt_a in
               zip([alphabet.index(k) for k in key], [alphabet.index(pt) for pt in block])]
    return"".join([alphabet[idx] for idx in ct_idxs])

def sub_key(key, block):
    ct_idxs = [(pt_a - k_a) % len(alphabet) for k_a, pt_a in
               zip([alphabet.index(k) for k in key], [alphabet.index(pt) for pt in block])]
    return"".join([alphabet[idx] for idx in ct_idxs])

def cbc(key, plaintext):
    klen = len(key)
    plaintext = pad(klen, plaintext)
    iv = random_alphastring(klen)
    blocks = [plaintext[i:i + klen] for i in range(0, len(plaintext), klen)]
    prev_block = iv
    ciphertext = ""
    for block in blocks:
        block = add_key(prev_block, block)
        prev_block = add_key(key, block)
        ciphertext += prev_block
    return iv, ciphertext

def decode(key, ciphertext):
    klen = len(key)
    blocks = [ciphertext[i:i + klen] for i in range(0, len(ciphertext), klen)]
    plaintext = ""
    for block in blocks:
        block = sub_key(key, block)
        plaintext += block
    return plaintext

def pad(block_size, plaintext):
    plaintext += "X" * (-len(plaintext) % block_size)
    return plaintext

blocks = [ct[i:i + bs] for i in range(0, len(ct), bs)]
ct_noiv = ""
prev_block = iv
for block in blocks:
    sblock = sub_key(prev_block, block)
    ct_noiv += sblock
    prev_block = block

print(ct_noiv)
#IDJUSTLIKETOINTERJECTFORAMOMENTWHATYOUREREFERINGTOASLINUXISINFACTGNULINUXORASIVERECENTLYTAKENTOCALLINGITGNUPLUSLINUXLINUXISNOTANOPERATINGSYSTEMUNTOITSELFBUTRATHERANOTHERFREECOMPONENTOFAFULLYFUNCTIONINGGNUSYSTEMMADEUSEFULBYTHEGNUCORELIBSSHELLUTILITIESANDVITALSYSTEMCOMPONENTSCOMPRISINGAFULLOSASDEFINEDBYPOSIXMANYCOMPUTERUSERSRUNAMODIFIEDVERSIONOFTHEGNUSYSTEMEVERYDAYWITHOUTREALIZINGITTHROUGHAPECULIARTURNOFEVENTSTHEVERSIONOFGNUWHICHISWIDELYUSEDTODAYISOFTENCALLEDLINUXANDMANYOFITSUSERSARENOTAWARETHATITISBASICALLYTHEGNUSYSTEMDEVELOPEDBYTHEGNUPROJECTTHEREREALLYISALINUXANDTHESEPEOPLEAREUSINGITBUTITISJUSTAPARTOFTHESYSTEMTHEYUSELINUXISTHEKERNELTHEPROGRAMINTHESYSTEMTHATALLOCATESTHEMACHINESRESOURCESTOTHEOTHERPROGRAMSTHATYOURUNTHEKERNELISANESSENTIALPARTOFANOPERATINGSYSTEMBUTUSELESSBYITSELFITCANONLYFUNCTIONINTHECONTEXTOFACOMPLETEOPERATINGSYSTEMLINUXISNORMALLYUSEDINCOMBINATIONWITHTHEGNUOPERATINGSYSTEMTHEWHOLESYSTEMISBASICALLYGNUWITHLINUXADDEDORGNULINUXALLTHESOCALLEDLINUXDISTRIBUTIONSAREREALLYDISTRIBUTIONSOFGNULINUXANYWAYHERECOMESTHEFLAGITSEVERYTHINGAFTERTHISATLEASTITSNOTAGENERICROTTHIRTEENCHALLENGEIGUESS
#!/usr/local/bin/python
from Crypto.Util.number import *
from os import urandom

flag = open("flag.txt", "rb").read()
flag = bytes_to_long(urandom(16) + flag + urandom(16))

p = getPrime(512)
q = getPrime(512)
n = p * q
e = 0x10001
d = pow(e, -1, (p-1)*(q-1))
assert flag < n
ct = pow(flag, e, n)

print(f"{n = }")
print(f"{e = }")
print(f"{ct = }")

whileTrue:
    ct = int(input("> "))
    pt = pow(ct, d, n)
    out = ""
    if pt == flag:
        exit(-1)
    if pt % 3 == 0:
        out += "Fizz"
    if pt % 5 == 0:
        out += "Buzz"
    ifnot out:
        out = "101"
    print(out)
from Crypto.Util.number import *
from pwn import *
def oracle(x):
    io.sendlineafter(b'> ', str(pow(x, e, n) * ct % n).encode())
    returnb'Buzz'notin io.recvline()

def binary_search(left, right, reverse=False):
    while left < right - 1:
        mid = (left + right) // 2
        if oracle(mid) ^ reverse:
            right = mid
        else:
            left = mid
    return left, right

whileTrue:
    io = remote("be.ax",31101)
    io.recvuntil(b'n = ')
    n = int(io.recvline().decode())
    io.recvuntil(b'e = ')
    e = int(io.recvline().decode())
    io.recvuntil(b'ct = ')
    ct = int(io.recvline().decode())
    ifnot oracle(2):
        k = 1
        whileTrue:
            k *= 2
            if oracle(k):
                break
        left, right = binary_search(k // 2, k)
        prog = io.progress('Flag')

        for i in range(1, 1000):
            left, right = binary_search(5 * left, 5 * right, reverse=True)
            print(left,right)
            prog.status(str(long_to_bytes(5 ** i * n // right)[16:-16]))
        break

    io.close()
    #corctf{''.join(fizz_buzz(x) for x in range(99, 102)) == "FizzBuzz101" == cool_username}
