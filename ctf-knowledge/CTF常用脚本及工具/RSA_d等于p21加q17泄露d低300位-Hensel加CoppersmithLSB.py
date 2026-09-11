#!/usr/bin/env python3
"""Solver: d = p^21 + q^17, d1 = d & (2^300-1) leaked, n=pq (512-bit primes).
Route: f(x)=x^38 - d1*x^17 + n^17 == 0 (mod 2^300) has few 2-adic roots incl. p mod 2^300.
Then p = r + 2^300*y, y < 2^212 << N^(1/4): univariate Coppersmith (d=1, beta=0.5).
"""
import sys
from math import prod

def hensel_roots(d1, n, m, cap=4096):
    """all x mod 2^m with f(x)=x^38-d1*x^17+n^17 == 0 mod 2^m"""
    M = 1 << m
    n17 = pow(n, 17, M)
    def f(r, Mk):
        return (pow(r, 38, Mk) - d1 * pow(r, 17, Mk) + n17) % Mk
    roots = [1]  # f(1)=1-d1+n^17 = 1-0+1 = 0 mod 2 (d1 even)
    for k in range(1, m):
        Mk = 1 << (k + 1)
        nxt = []
        for r in roots:
            if (f(r, Mk) >> k) & 1 == 0:
                nxt.append(r)
                nxt.append(r | (1 << k))
                if len(nxt) > cap:
                    raise RuntimeError(f"root explosion at bit {k}: {len(nxt)}")
        roots = nxt
    return roots

def poly_mul(a, b):
    res = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        if ai:
            for j, bj in enumerate(b):
                res[i + j] += ai * bj
    return res

def poly_pow(f, i):
    res = [1]
    base = list(f)
    while i:
        if i & 1:
            res = poly_mul(res, base)
        base = poly_mul(base, base)
        i >>= 1
    return res

def lll(matrix):
    """fpylll LLL on integer matrix (list of rows), returns reduced rows."""
    from fpylll import IntegerMatrix, LLL
    w = len(matrix)
    B = IntegerMatrix(w, w)
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            B[i, j] = int(v)
    LLL.reduction(B)
    return [[B[i, j] for j in range(w)] for i in range(w)]

def coppersmith_lsb(r, N, shift=300, Xbits=None, m=6, t=6, verbose=True):
    """p = r + 2^shift * y, y in [2^(Xbits-1), 2^Xbits) -> y = center+y', |y'| <= 2^(Xbits-2).
    Linear monic f(y') = y' + A ≡ 0 mod p (>= N^0.5). Coppersmith with g_i = N^(m-i) f^i, h_j = y'^j f^m."""
    if Xbits is None:
        Xbits = 512 - shift
    center = 3 * (1 << (Xbits - 2))
    X = 1 << (Xbits - 2)
    inv = pow(pow(2, shift, N), -1, N)
    A = (center + r * inv) % N  # f(y')=y'+A: 2^shift*f = r + 2^shift*(center+y') = p ≡ 0 mod p
    f = [A, 1]
    polys = []
    for i in range(m + 1):
        fi = poly_pow(f, i)
        polys.append([c * (N ** (m - i)) for c in fi])
    fm = poly_pow(f, m)
    for j in range(1, t + 1):
        polys.append([0] * j + fm)
    w = len(polys)
    B = []
    for p_ in polys:
        row = [0] * w
        for k, c in enumerate(p_):
            row[k] = c * (X ** k)
        B.append(row)
    rows = lll(B)
    # exact root recovery: mpmath balanced-scale numerics + exact integer verification
    import sympy
    import mpmath
    from numroot import numeric_int_roots
    yv = sympy.symbols('y')
    found = []
    for row in rows[:4]:
        coefs = []
        ok = True
        for k in range(w):
            v = row[k]
            if v == 0:
                coefs.append(0)
                continue
            if v % (X ** k) != 0:
                ok = False
                break
            coefs.append(v // (X ** k))
        if not ok or all(c == 0 for c in coefs):
            continue
        deg = max(k for k, cc in enumerate(coefs) if cc)
        coefs = coefs[:deg + 1]
        if deg == 0:
            continue
        for cand in numeric_int_roots(coefs, X):
            p_cand = r + (1 << shift) * (center + cand)
            if p_cand > 0 and N % p_cand == 0:
                found.append(p_cand)
        if found:
            break
    return found[0] if found else None

def solve(n, c, d1, e=65537, shift=300, verbose=True):
    roots = hensel_roots(d1, n, shift)
    if verbose:
        print(f"[*] {len(roots)} roots mod 2^{shift}")
    for r in roots:
        p = coppersmith_lsb(r, n, shift=shift)
        if p:
            q = n // p
            assert p * q == n
            print(f"[+] FACTORED: p = {p}")
            print(f"[+] q = {q}")
            phi = (p - 1) * (q - 1)
            from Crypto.Util.number import long_to_bytes
            dkey = pow(e, -1, phi)
            mm = pow(c, dkey, n)
            fl = long_to_bytes(mm)
            return p, q, fl
    return None

if __name__ == "__main__":
    if sys.argv[1] == "test":
        from Crypto.Util.number import getPrime, bytes_to_long
        import os
        for trial in range(2):
            p = getPrime(512); q = getPrime(512)
            n = p * q
            d = p ** 21 + q ** 17
            d1 = d & ((1 << 300) - 1)
            msg = b"flag{test_" + os.urandom(4) + b"}" + os.urandom(60)
            c = pow(bytes_to_long(msg), 65537, n)
            import time
            t0 = time.time()
            res = solve(n, c, d1)
            print(f"trial {trial}: {'OK' if res and res[2] == msg else 'FAIL'} in {time.time()-t0:.1f}s")
            if res and res[2] != msg:
                print("  got:", res[2][:50])
    else:
        n = 89049581381915401856270440494182068395799559452947499744642830361236578373835725708887668528820916651578050248209041339369091828040992115394942524278397293747808840107939504743946806866214713225533666120894844131211241905215662457238793580469827973839976134854993162976454283311566973255659612267446150515233
        c = 16305239798028293699632813396005973660370581911030264211210444559974188415332021689054795983319112132645051076901780239982290095820283651929773925636804434706351474493000010749679965744672518110692104573489299874390925347271040454693791271882869477780584606934066152476594086178041874762147934091597942667138
        d1 = 1253867202722198232827428701701674148965306906567632781415318063046179456643047348348144258
        e = 65537
        res = solve(n, c, d1, e)
        if res:
            p, q, fl = res
            print("[+] flag bytes:", fl)
            print("[+] printable prefix:", fl.rstrip(bytes(range(0, 33))))
        else:
            print("[-] failed")
