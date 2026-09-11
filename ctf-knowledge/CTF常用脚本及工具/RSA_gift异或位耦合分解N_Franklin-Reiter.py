#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSA gift=P^(Q>>16) 位耦合分支定界分解 N + Franklin-Reiter 恢复明文

场景: 已知 N=P*Q(P,Q 各512bit), gift=P^(Q>>16), cN=pow(n,11,N)(n=p*q 未知),
      c1=secret^11 mod n, c2=flag^11 mod n, flag=b"prefix"+secret+b"suffix"。
用法: 把输出里五个大整数按顺序填进下面的常量, python3 运行即可。
      也适用于任何 gift=P^(Q>>s) 形式(改 SHIFT/NP_BITS), 任意小指数 e。
"""
from math import comb, gcd
from Crypto.Util.number import bytes_to_long, long_to_bytes

# ===================== 题目数据(按题替换) =====================
N    = 75000029602085996700582008490482326525611947919932949726582734167668021800854674616074297109962078048435714672088452939300776268788888016125632084529419230038436738761550906906671010312930801751000022200360857089338231002088730471277277319253053479367509575754258003761447489654232217266317081318035524086377
GIFT = 8006730615575401350470175601463518481685396114003290299131469001242636369747855817476589805833427855228149768949773065563676033514362512835553274555294034
CN   = 14183763184495367653522884147951054630177015952745593358354098952173965560488104213517563098676028516541915855754066719475487503348914181674929072472238449853082118064823835322313680705889432313419976738694317594843046001448855575986413338142129464525633835911168202553914150009081557835620953018542067857943
C1   = 69307306970629523181683439240748426263979206546157895088924929426911355406769672385984829784804673821643976780928024209092360092670457978154309402591145689825571209515868435608753923870043647892816574684663993415796465074027369407799009929334083395577490711236614662941070610575313972839165233651342137645009
C2   = 46997465834324781573963709865566777091686340553483507705539161842460528999282057880362259416654012854237739527277448599755805614622531827257136959664035098209206110290879482726083191005164961200125296999449598766201435057091624225218351537278712880859703730566080874333989361396420522357001928540408351500991
E        = 11
NP_BITS  = 512          # P 的比特数
SHIFT    = 16           # gift = P ^ (Q >> SHIFT)
PREFIX   = b"dasctf{"   # flag 已知前缀(flag = PREFIX + secret + SUFFIX)
SUFFIX   = b"}"
MAX_LEN  = 120          # secret 长度枚举上限

# ============ 1. gift 位耦合分支定界分解 N ============
def xor_gift_factor(N, gift, np_bits=512, shift=16):
    """返回 (P, Q)。gift[i] = P[i] ^ Q[i+shift] 的逐位耦合 + 区间剪枝。"""
    gt = [(gift >> i) & 1 for i in range(np_bits)]
    # 状态: (P >> i, Q >> (i+shift)); P 高 shift 位 = gift 高 shift 位
    cands = [(gift >> (np_bits - shift), 0)]
    for i in range(np_bits - shift - 1, -1, -1):
        Ms = N >> (2 * i + shift)        # 必须与状态同尺度!
        gb = gt[i]
        nxt = []
        for Ph, Qh in cands:
            for b in (0, 1):
                P2 = (Ph << 1) | b
                Q2 = (Qh << 1) | (gb ^ b)
                if P2 * Q2 <= Ms < (P2 + 1) * (Q2 + 1):
                    nxt.append((P2, Q2))
        if not nxt:
            raise ValueError("branch&bound dead at bit %d (gift/N 不匹配?)" % i)
        cands = nxt
    for Ph, _ in cands:
        if N % Ph == 0:
            P, Q = Ph, N // Ph
            if (P ^ (Q >> shift)) == gift:
                return P, Q
    raise ValueError("no valid factorization")

# ============ 2. 由 cN = n^e mod N 恢复 n(候选 r / r+N) ============
def recover_n(cN, e, N, P, Q, p_bits=512):
    phi = (P - 1) * (Q - 1)
    assert gcd(e, phi) == 1, "e 与 phi(N) 不互素, 本脚本不适用"
    r = pow(cN, pow(e, -1, phi), N)          # r = n mod N
    lo, hi = 1 << (2 * p_bits - 2), 1 << (2 * p_bits)
    return [c for c in (r, r + N) if lo <= c < hi]

# ============ 3. Franklin-Reiter(多项式 gcd, 纯 Python) ============
def _trim(a):
    while a and a[-1] == 0:
        a.pop()
    return a

def _pdivmod(a, b, n):
    a, inv = a[:], pow(b[-1], -1, n)
    b = [x * inv % n for x in b]
    db = len(b) - 1
    q = [0] * max(len(a) - db, 0)
    for k in range(len(a) - 1, db - 1, -1):
        c = a[k]
        if c:
            q[k - db] = c
            for j in range(db + 1):
                a[k - db + j] = (a[k - db + j] - c * b[j]) % n
    return _trim(q), _trim(a)

def _pgcd(a, b, n):
    """返回 a mod n 与 b mod n 的最大公因式(系数列表, 首项系数 1)。"""
    a, b = _trim(a), _trim(b)
    while b:
        _, r = _pdivmod(a, b, n)
        a, b = b, r
    if a:
        a = [x * pow(a[-1], -1, n) % n for x in a]
    return a

def franklin_reiter(c1, c2, e, n, prefix, suffix=b"}", max_len=120):
    """m2 = m1*2^(8*(L+1)) + B, B=prefix<<...|suffix; gcd(x^e-c1, (2^8 x+B)^e-c2)"""
    A = bytes_to_long(prefix)
    sc = ord(suffix)
    for L in range(max_len + 1):
        B = (A << (8 * (L + 1))) + sc
        h2 = [comb(e, k) * (1 << (8 * k)) % n * pow(B, e - k, n) % n for k in range(e + 1)]
        h2[0] = (h2[0] - c2) % n
        h1 = [(-c1) % n] + [0] * (e - 1) + [1]
        try:
            g = _pgcd(h1, h2, n)
        except ValueError:
            continue
        if len(g) == 2:                  # 一次式 x - m1
            m = (-g[0] * pow(g[1], -1, n)) % n
            if pow(m, e, n) == c1:
                return m
    return None

def iroot(x, k):
    hi = 1 << (x.bit_length() // k + 2); lo = 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if mid ** k <= x else (lo, mid - 1)
    return lo

# ============================ main ============================
if __name__ == "__main__":
    # 0) 快速通道: 若 secret/flag 无随机填充, 直接开 e 次方根
    for name, c in (("c1", C1), ("c2", C2)):
        r = iroot(c, E)
        if r ** E == c:
            print("[!] plain %d-th root: %r" % (E, long_to_bytes(r)))
    P, Q = xor_gift_factor(N, GIFT, NP_BITS, SHIFT)
    print("[+] P =", P); print("[+] Q =", Q)
    for nc in recover_n(CN, E, N, P, Q, NP_BITS):
        m = franklin_reiter(C1, C2, E, nc, PREFIX, SUFFIX, MAX_LEN)
        if m is None:
            continue
        secret = long_to_bytes(m)
        flag = PREFIX + secret + SUFFIX
        assert pow(bytes_to_long(flag), E, nc) == C2, "flag 回验失败"
        print("[+] n bits =", nc.bit_length())
        print("[+] flag:", flag.decode())
        break
    else:
        raise SystemExit("[-] Franklin-Reiter 未命中: 前后缀假设或长度上限需调整")
