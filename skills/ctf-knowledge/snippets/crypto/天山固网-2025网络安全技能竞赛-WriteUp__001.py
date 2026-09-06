# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/天山固网-2025网络安全技能竞赛-WriteUp.md
# TITLE: 天山固网-2025网络安全技能竞赛-WriteUp
# CATEGORY: crypto

text =""""""
# 转换大小写为 0/1
result = []
for ch in text:
    if ch.isupper():
        result.append("1")
    elif ch.islower():
        result.append("0")
    # else:
    #     result.append(ch)  # 空格或其他符号保持不变

binary_str = "".join(result)
print(binary_str)
# 转换为二维码图片
from PIL import Image
MAX = 42
pic = Image.new("RGB",(MAX, MAX))
str = ""
i=0
for y in range (0,MAX):
    for x in range (0,MAX):
        if(str[i] == '1'):
            pic.putpixel([x,y],(0, 0, 0))
        else:
            pic.putpixel([x,y],(255,255,255))
        i = i+1
pic.show()
pic.save("flag.png")
import random
from Crypto.Util.number import *
import secrets

def shuffle_secret(secret):
    random.seed(0)
    secret = list(secret)
    random.shuffle(secret)
    return''.join(secret)

def myPrime():
    whileTrue:
        if isPrime(p := random.getrandbits(64)):
            return p

def get_factors():
    factors = [myPrime() for _ in range(2000)]
    return factors

if __name__ == '__main__':
    secret = 'rCr3h0s1ry_t__s4pB_teg_yipF__dnMyFF'
    shuffle_secret_val = shuffle_secret(secret)
    print(f"{shuffle_secret_val=}")

    factors = get_factors()
    print(f"{len(factors)=}")
    print(f"{factors=}")
import gmpy2
import random
from Crypto.Util.number import *
n =
e =65537
c =
t = pow(2,1024)
k = 2
x = 
for i in range(len(x)):
    k = pow(k,x[i],n)
    if k>t:
        if i%15 ==0:
            g = gmpy2.gcd(k-1,n)
            if g!=1:
                print("因子:",g)
                break
def pq_high_xor(p="", q=""):
    lp, lq = len(p), len(q)
    tp0 = int(p + (512-lp) * "0", 2)
    tq0 = int(q + (512-lq) * "0", 2)
    tp1 = int(p + (512-lp) * "1", 2)
    tq1 = int(q + (512-lq) * "1", 2)

    if tp0 * tq0 > n or tp1 * tq1 < n:
        return
    if lp == leak_bits:
        pq.append(tp0)
        return

    if xor[lp] == "1":
        pq_high_xor(p + "0", q + "1")
        pq_high_xor(p + "1", q + "0")
    else:
        pq_high_xor(p + "0", q + "0")
        pq_high_xor(p + "1", q + "1")

def pq_low_xor(p="", q=""):
    lp, lq = len(p), len(q)
    tp = int(p, 2) if p else0
    tq = int(q, 2) if q else0

    if tp * tq % 2**lp != n % 2**lp:
        return
    if lp == leak_bits:
        pq.append(tp)
        return

    if xor[-lp-1] == "1":
        pq_low_xor("0" + p, "1" + q)
        pq_low_xor("1" + p, "0" + q)
    else:
        pq_low_xor("0" + p, "0" + q)
        pq_low_xor("1" + p, "1" + q)
    #for i in range(200,300):
leak = leak << 215
leak_bits = 512-215
xor = bin(leak)[2:].zfill(512)
pq = []

pq_high_xor()
# print(pq)

for p_high in pq:
    x = PolynomialRing(Zmod(n), 'x').gen()
    f = p_high + x
    res = f.monic().small_roots(X=2**215, beta=0.44,epsilon=1/16)
    if res:
        p = int(p_high+res[0])
        print(p)
from Crypto.Util.number import *
p=12849041580187712114287340210939396034424272221812148338878681353480052959626982507824137597050709378850940287288828758690514971324264679315212899800699649
q=12873211897459556383148381598553582828419349814854356501114717109080249055667413399225499444590500163395293435005743026518120878091777335879008061804074573
n=16540843494102499415836904244978840191029498840763686795549650936067514623
3043101006492521091959823423540542967459193522177826921732843078657511418718
2770689749905170745519843062613652139329837516178725502388350154295296315239
7382307164081785688671310884502037288325565062878881953233601744472220994437
0924877
e=65537
c = 32514400111560285767114059428272978369671794111207540192987911899965917441745193707727404259848540711110916899114259203696404123229134392494554874352785281551973075869313034289563994886386821257391009141162559968535288461313309953574507706583653092150741608080020850440840533409996254003612114636139855553078
m=pow(c,inverse(e,(p-1)*(q-1)),n)
print(long_to_bytes(m))
import idaapi
import idc

def find_pattern_and_decode(start_addr):
    pattern = [0x30, 0xE0, 0xC3]
    seg = idaapi.getseg(start_addr)
    ifnot seg:
        print("无法获取段信息")
        return
    end_addr = seg.end_ea
    print(f"搜索范围: 0x{start_addr:X} - 0x{end_addr:X}")
    current_addr = start_addr
    found_count = 0
    result_chars = []
    while current_addr < end_addr - 2:
        if (idc.get_wide_byte(current_addr) == 0x30and
            idc.get_wide_byte(current_addr + 1) == 0xE0and
            idc.get_wide_byte(current_addr + 2) == 0xC3):
            print(f"找到模式 30 E0 C3 在地址: 0x{current_addr:X}")
            found_count += 1
            # 向上搜索 0xB0
            search_addr = current_addr
            found_b0 = False

            for i in range(12):
                search_addr -= 1
                if search_addr < start_addr:
                    break
                if idc.get_wide_byte(search_addr) == 0xB0:
                    # 计算偏移
                    offset = search_addr - start_addr
                    print(f" 偏移: 0x{offset:X} ({offset})")
                    # 右移3位并 & 0xFF
                    result = (offset >> 3) & 0xFF
                    print(f" 右移3位后: 0x{result:X} ({result})")
                    if32 <= result <= 126:
                        char = chr(result)
                        print(f" 字符: '{char}'")
                        result_chars.append(char)
                    found_b0 = True
                    break
            ifnot found_b0:
                print(f" 未找到对应的 0xB0")
        current_addr += 1
    if result_chars:
        print(f"flag: {''.join(result_chars)}")
    else:
        print("未解码出任何字符")

def main():

    start_address = 0x000055555558DAC0
    print(f"起始地址: 0x{start_address:X}")
    find_pattern_and_decode(start_address)

if __name__ == "__main__":
    main()
