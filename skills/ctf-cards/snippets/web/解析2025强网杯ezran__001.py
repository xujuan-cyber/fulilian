# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/解析2025强网杯ezran.md
# TITLE: 解析2025强网杯ezran
# CATEGORY: web

from Crypto.Util.number import *
from random import *

f = open('flag.txt', 'r')
flag = f.read().encode()

# 第一部分：生成 gift 序列
gift = b''
for i in range(3108):
    r1 = getrandbits(8)   # 生成8位随机数
    r2 = getrandbits(16)  # 生成16位随机数
    x = (pow(r1, 2*i, 257) & 0xff) ^ r2
    c = long_to_bytes(x, 2)
    gift += c

# 第二部分：对 flag 进行 shuffle 混淆
m = list(flag)
for i in range(2025):
    shuffle(m)

c = "".join(list(map(chr, m)))

# 输出结果
f = open('output.txt', 'w')
f.write(f"gift = {bytes_to_long(gift)}n")
f.write(f"c = {c}n")
for i in range(3108):
    r1 = getrandbits(8)   # 8位随机数（0-255）
    r2 = getrandbits(16)  # 16位随机数（0-65535）
    x = (pow(r1, 2*i, 257) & 0xff) ^ r2
    c = long_to_bytes(x, 2)
    gift += c
m = list(flag)
for i in range(2025):
    shuffle(m)
c = "".join(list(map(chr, m)))
x = (pow(r1, 2*i, 257) & 0xff) ^ r2
c = long_to_bytes(x, 2)  # 转换为2字节
如果 x < 256（即 x 的高8位为0），则：
  long_to_bytes(x, 2) = b'x00' + bytes([x])

如果 x >= 256（即 x 的高8位不为0），则：
  long_to_bytes(x, 2) = bytes([x >> 8]) + bytes([x & 0xff])
x = (pow(r1, 2*i, 257) & 0xff) ^ r2

设 pow(r1, 2*i, 257) & 0xff = y （y 是0-255的一个值）

则：x = y ^ r2
x = y ^ r2
  = y ^ (r2_high * 256 + r2_low)
  = (r2_high * 256) ^ (y ^ r2_low)

x 的高8位 = r2_high
x 的低8位 = y ^ r2_low
gift = long_to_bytes(gift)
g = [gift[2 * i:2 * i + 2][0] for i in range(len(gift) // 2)]
from gf2bv import LinearSystem
from gf2bv.crypto.mt import MT19937

def mt19937(bs, out):
    # 创建一个线性系统，624个32位变量
    lin = LinearSystem([32] * 624)
    mt = lin.gens()  # 获取符号变量（代表MT19937的624个状态）

    rng = MT19937(mt)  # 创建符号MT19937
    zeros = []

    for o in out:
        rng.getrandbits(8)   # 模拟调用 r1 = getrandbits(8)
        # 模拟调用 r2 = getrandbits(16)，然后右移8位
        # 右移8位相当于取高8位
        # 我们知道 r2 >> 8 的结果，与观察值 o 异或应该为某个8位值
        zeros.append(rng.getrandbits(bs) >> 8 ^ int(o))

    # 添加额外约束：MT19937状态的第一个元素的最高位必须为1
    zeros.append(mt[0] ^ int(0x80000000))

    # 求解所有可能的状态
    for sol in lin.solve_all(zeros):
        rng = MT19937(sol)
        pyrand = rng.to_python_random()
        yield pyrand
lin = LinearSystem([32] * 624)
mt = lin.gens()
for o in out:
    rng.getrandbits(8)
    zeros.append(rng.getrandbits(bs) >> 8 ^ int(o))
(r2 >> 8) ^ observed = (pow(r1, 2*i, 257) & 0xff)
(r2 >> 8) ^ observed = 某个0-255的值
zeros.append(mt[0] ^ int(0x80000000))
for sol in lin.solve_all(zeros):
def shuffle(x):
    for i in range(len(x)-1, 0, -1):
        j = randrange(i+1)
        x[i], x[j] = x[j], x[i]
def ins(s, rng, rounds=2025):
    a = list(s)
    n = len(a)
    sw = []

    # 步骤1：重新生成所有的随机数，记录所有交换操作
    for _ in range(rounds):
        for i in range(n - 1, 0, -1):
            j = rng.randrange(i + 1)
            sw.append((i, j))

    # 步骤2：逆序应用交换操作
    for i, j in reversed(sw):
        a[i], a[j] = a[j], a[i]

    if isinstance(s, (bytes, bytearray)):
        return bytes(a)
    return''.join(a)
from sage.all import *
from Crypto.Util.number import *
from gf2bv import LinearSystem
from gf2bv.crypto.mt import MT19937
from output import gift, c

def mt19937(bs, out):
    """
    使用 gf2bv 库恢复 MT19937 随机数生成器的内部状态

    参数:
    bs: 随机数位数
    out: 观测到的输出序列

    返回:
    可能的随机数生成器状态
    """
    lin = LinearSystem([32] * 624)
    mt = lin.gens()

    rng = MT19937(mt)
    zeros = []
    for o in out:
        rng.getrandbits(8)  # 跳过一个8位随机数
        zeros.append(rng.getrandbits(bs) >> 8 ^ int(o))  # 添加约束条件
    zeros.append(mt[0] ^ int(0x80000000))  # MSB 必须为1

    # 求解所有可能的状态
    for sol in lin.solve_all(zeros):
        rng = MT19937(sol)
        pyrand = rng.to_python_random()
        yield pyrand

def ins(s, rng, rounds=2025):
    """
    逆向 shuffle 操作

    参数:
    s: 被打乱的序列
    rng: 随机数生成器（需要与加密时使用的相同状态）
    rounds: shuffle 轮数

    返回:
    还原后的原始序列
    """
    a = list(s)
    n = len(a)
    sw = []

    # 记录所有的交换操作
    for _ in range(rounds):
        for i in range(n - 1, 0, -1):
            j = rng.randrange(i + 1)
            sw.append((i, j))

    # 逆序应用交换操作
    for i, j in reversed(sw):
        a[i], a[j] = a[j], a[i]

    if isinstance(s, (bytes, bytearray)):
        return bytes(a)
    return''.join(a)

# 将 gift 转换为字节
gift = long_to_bytes(gift)

# 提取每两个字节的第一个字节作为观测输出
g = [gift[2 * i:2 * i + 2][0] for i in range(len(gift) // 2)]

print("[*] 开始恢复 MT19937 随机数生成器状态...")
print(f"[*] 观测到的输出数量: {len(g)}")

# 尝试所有可能的随机数生成器状态
for rng in mt19937(16, g):
    print("[*] 找到一个可能的状态，正在验证...")

    # 重新生成 gift 序列
    gg = b''
    for i in range(3108):
        r1 = rng.getrandbits(8)
        r2 = rng.getrandbits(16)
        x = (pow(r1, 2*i, 257) & 0xff) ^ r2
        cc = long_to_bytes(x, 2)
        gg += cc

    # 验证生成的序列是否与原始 gift 匹配
    if gg == gift:
        print("[+] 状态验证成功！")
        print("[*] 正在还原 flag...")
        flag = ins(c, rng)
        print(f"n[+] Flag: {flag}n")
        break
else:
    print("[-] 未找到正确的状态")
g = [gift[2 * i:2 * i + 2][0] for i in range(len(gift) // 2)]
if gg == gift:
    flag = ins(c, rng)
for i, j in reversed(sw):
    a[i], a[j] = a[j], a[i]
