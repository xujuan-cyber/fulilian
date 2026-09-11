"""
# 已知 n、c，q = next_prime(p)（费马分解），m 前半含随机后缀 求 m

## 特征
- n = p*q 且 q = next_prime(p)（p、q 极近）→ 费马分解，步数 ~|p-q|/2，秒出
- flag 被切成两半：
  - 前半 m1 = bytes_to_long(flag[:len//2] + os.urandom(8)) → RSA 加密得 c1
  - 后半 m2 = flag[len//2:] → 逐字符 md5 写入 out.txt（单字符哈希直接查表）
- 还原：RSA 解 m1 去掉尾部 8 字节随机后缀 + md5 查表拼后半

## 关键点
- math.isqrt 足够，无需 gmpy2（ctf venv 不一定有 gmpy2）
- 费马起点 a = ceil(isqrt(n))，逐个 +1 直到 a^2-n 为完全平方数
- 单字符 md5 用 32~126 可打印字符建反查表
- 回验：m1 去随机字节后重加密 == c1；逐字符重哈希 == 原哈希列表

## 用法
把 out.txt（首行 n、次行 c1、随后每行一个字符 md5）与本脚本放同一目录运行。
"""

from Crypto.Util.number import long_to_bytes, inverse, bytes_to_long
from hashlib import md5
import math
import sys


def fermat_factor(n, max_iter=1 << 20):
    a = math.isqrt(n)
    if a * a < n:
        a += 1
    for _ in range(max_iter):
        b2 = a * a - n
        b = math.isqrt(b2)
        if b * b == b2:
            return a - b, a + b
        a += 1
    raise ValueError('Fermat failed: p, q 可能不够接近')


def main():
    lines = open('out.txt').read().split('\n')
    n, c1 = int(lines[0]), int(lines[1])
    hashes = [l.strip() for l in lines[2:] if l.strip()]

    # 后半：单字符 md5 查表
    md5map = {md5(chr(i).encode()).hexdigest(): chr(i) for i in range(32, 127)}
    m2 = ''.join(md5map.get(h, '?') for h in hashes)

    # 前半：费马分解 + RSA
    p, q = fermat_factor(n)
    assert p * q == n
    e = 65537
    d = inverse(e, (p - 1) * (q - 1))
    raw = long_to_bytes(pow(c1, d, n))
    first_half = raw[:-8].decode()  # 去掉 os.urandom(8) 后缀

    flag = first_half + m2

    # 回验
    reenc = pow(bytes_to_long(first_half.encode() + raw[len(first_half.encode()):]), e, n)
    assert reenc == c1, 'm1 回验失败'
    assert all(md5(ch.encode()).hexdigest() == h for ch, h in zip(m2, hashes)), 'm2 回验失败'

    print('p =', p)
    print('q =', q)
    print('FLAG:', flag)


if __name__ == '__main__':
    sys.exit(main())
