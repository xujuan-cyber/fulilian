#!/usr/bin/env python3
# 多小素数 RSA 分解模板：n = 15 个 32-bit 素数乘积（NSSCTF RSA 类常见套路）
# sympy.factorint 对 15 因子乘积极慢（>180s），直接用 Pollard's rho (Brent) 递归拆分，秒级完成。
# 验证于 NSSCTF [SWPU 2019]（n 1729006607059497957...482261, c 1432203843376165...363595）
# 用法：替换下方 n / c（e 固定 65537），python3 运行即出 flag。

from math import gcd, prod
from Crypto.Util.number import long_to_bytes

n = 17290066070594979571009663381214201320459569851358502368651245514213538229969915658064992558167323586895088933922835353804055772638980251328261
c = 14322038433761655404678393568158537849783589481463521075694802654611048898878605144663750410655734675423328256213114422929994037240752995363595
e = 65537


def brent(n: int) -> int:
    """返回 n 的一个非平凡因子，失败返回 None。"""
    if n % 2 == 0:
        return 2
    for c_ in range(1, 1000):
        x0, y, r, q, g, m = 2, 2, 1, 1, 1, 128
        while g == 1:
            x = y
            for _ in range(r):
                y = (y * y + c_) % n
            k = 0
            while k < r and g == 1:
                ys = y
                for _ in range(min(m, r - k)):
                    y = (y * y + c_) % n
                    q = q * abs(x - y) % n
                g = gcd(q, n)
                k += m
            r <<= 1
        if g == n:  # 回退逐步 gcd
            g = 1
            while g == 1:
                ys = (ys * ys + c_) % n
                g = gcd(abs(x - ys), n)
        if g != n:
            return g
    return None


def factor(n: int, out: list):
    if n == 1:
        return
    if n.bit_length() <= 40:
        out.append(n)
        return
    d = brent(n)
    if d is None:
        out.append(n)
        return
    factor(d, out)
    factor(n // d, out)


factors = []
factor(n, factors)
assert prod(factors) == n, "分解失败"
print("factors:", factors)
print("all 32-bit primes:", all(f.bit_length() == 32 for f in factors))

phi = prod(p - 1 for p in factors)
d = pow(e, -1, phi)
print(long_to_bytes(pow(c, d, n)))
