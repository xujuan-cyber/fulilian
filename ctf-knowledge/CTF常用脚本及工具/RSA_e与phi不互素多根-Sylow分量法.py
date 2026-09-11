"""RSA: gcd(e, phi) != 1 时的全部 e 次根枚举 —— Sylow 分量法（2026-09 实战验证）

适用: N = p*q, gcd(e, (p-1)(q-1)) = g > 1（如 e = 7*191*23111329, 7 | Q-1）
比 sympy nthroot_mod(all_roots=True) 快得多（后者在 512bit 素数 + 组合重数下会超时），
也不需要完整 AMM 的 t>=2 手工分支：直接对每个素数的 Sylow 子群做查表 DLP。

用法:
    rp = sylow_solutions(P, e, c % P)   # 返回 mod P 的全部 e 次根（个数 = gcd(e, P-1)）
    rq = sylow_solutions(Q, e, c % Q)
    再对 rp x rq 做 CRT 组合，long_to_bytes 过滤 flag。
要点:
    - c 必须是 g 次剩余（c^((p-1)/g) == 1），否则无解；
    - 自动处理 r^k || p-1 的任意重数（本题 Q-1 含 7^2）；
    - 根总数 = gcd(e, p-1)。

候选过滤坑（实战踩过，通用）:
    - 候选多时用「最长可打印前缀」排序取最优，别逐字节硬过滤；
    - 若按 m >> (bit_length-48) 取前几字节判可打印，隐含假设首字节>=0x80；
      首字节是 ASCII（如 'D'=0x44）时窗口错位 1bit，切出的字节含高位垃圾，
      真 flag 被误杀 —— DASCTF 开头的明文就中过招，靠前缀排序才捞出。
"""
from math import gcd
from random import randrange
from sympy import factorint


def sylow_solutions(p, e, c):
    """all x mod prime p with x^e = c, via Sylow component decomposition."""
    n = p - 1
    g = gcd(e, n)
    fg = factorint(g)
    D = 1
    for r in fg:
        k, v = 0, n
        while v % r == 0:
            v //= r
            k += 1
        D *= r ** k                      # full r-Sylow order in n
    s = n // D
    assert gcd(D, s) == 1
    assert pow(c, n // g, p) == 1, "no solution: c not a g-th residue"

    # s-component: unique solution
    Es = D * pow(D, -1, s) % n
    c_s = pow(c, Es, p)
    x_s = pow(c_s, pow(e, -1, s), p)

    # each prime r | g: solve in r-Sylow (order r^k) by table DLP
    sols = [x_s]
    for r in fg:
        k, v = 0, n
        while v % r == 0:
            v //= r
            k += 1
        Er = (n // (r ** k)) * pow(n // (r ** k), -1, r ** k) % n
        c_r = pow(c, Er, p)
        while True:
            gam = pow(randrange(2, p), n // (r ** k), p)
            if pow(gam, r ** (k - 1), p) != 1:
                break                    # gam has order exactly r^k
        tbl = {}
        pw = 1
        for j in range(r ** k):
            tbl[pw] = j
            pw = pw * gam % p
        if c_r == 1:
            new = []
            for z in sols:
                for j in range(r ** k):
                    new.append(z * pow(gam, j, p) % p)
            sols = new
        else:
            a = tbl[c_r]                 # c_r = gam^a
            em = e % (r ** k)
            gg2 = gcd(em, r ** k)
            assert a % gg2 == 0, "no solution in r-Sylow"
            m2 = (r ** k) // gg2
            b0 = (a // gg2) * pow(em // gg2, -1, m2) % m2
            new = []
            for z in sols:
                for kk in range(gg2):
                    xr = pow(gam, b0 + kk * m2, p)
                    new.append(z * xr % p)
            sols = new
    return [x for x in set(sols) if pow(x, e, p) == c % p]
