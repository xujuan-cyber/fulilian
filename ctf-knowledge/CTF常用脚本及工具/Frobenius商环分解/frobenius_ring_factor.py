#!/usr/bin/env python3
# Frobenius quotient-ring factoring (general tool)
# Structure: n = p * q * r with q = 1+p+...+p^(d-1) prime (q | p^d - 1).
# In R = Zmod(n)[x]/(f) (f random monic deg d), z^n has all non-constant
# coeffs == 0 (mod p) whenever f mod p is irreducible of degree d (~1/d of
# the time) => gcd(deg-1 coeff of z^n, n) = p. Retry with fresh f/z.
# USAGE: set n below (or import try_factor with your own n); d=5 hardcoded
#        in ring ops -- adjust ranges for other d.
# Origin: DASCTF x 0psu3 2023 GeneratePrime (verified end-to-end).
import re, random, time
from math import gcd
from Crypto.Util.number import long_to_bytes, isPrime

t = open('/tmp/ctf_zipwork2/题目附件/task.py').read()
n = int(re.search(r'n=(\d+)', t).group(1))
c_ = int(re.search(r'c=(\d+)', t).group(1))
e = 65537

L = 2 * n.bit_length() + 6          # limb bits; pre-reduction coeffs < 5*n^2
LMASK = (1 << L) - 1

def pack(a):
    v = 0
    for i in range(4, -1, -1):
        v = (v << L) | a[i]
    return v

def unpack_fold(C, n, red5):
    acc = [(C >> (L * k)) & LMASK for k in range(9)]   # degrees 0..8
    for d in range(8, 4, -1):                          # fold high->low; writes only to < d
        v = acc[d] % n
        if v:
            acc[d] = 0
            b = d - 5
            for j in range(5):
                acc[b + j] += v * red5[j]              # correct index: (d-5)+j
    return [acc[j] % n for j in range(5)]

def mul(a, b, n, red5):
    C = pack(a) * pack(b)
    return unpack_fold(C, n, red5)

def poly_pow(z, exp, n, red5):
    # 4-bit window, MSB-first
    table = [[1, 0, 0, 0, 0]]
    for i in range(1, 16):
        table.append(mul(table[i - 1], z, n, red5))
    bits = bin(exp)[2:]
    pad = (-len(bits)) % 4
    bits = '0' * pad + bits
    result = [1, 0, 0, 0, 0]
    for i in range(0, len(bits), 4):
        # square 4 times
        for _ in range(4):
            result = mul(result, result, n, red5)
        w = int(bits[i:i + 4], 2)
        if w:
            result = mul(result, table[w], n, red5)
    return result

def try_factor():
    f = [random.randrange(1, n) for _ in range(5)] + [1]
    red5 = [(-f[k]) % n for k in range(5)]
    z = [random.randrange(n) for _ in range(5)]
    zn = poly_pow(z, n, n, red5)
    g = gcd(zn[1], n)   # WP: degree-1 coeff ONLY (random const coeff kills all-coeff gcd)
    if g == n:
        return None
    return g if g > 1 else None

def reconstruct(g):
    for pp in (g, n // g):
        if pp.bit_length() != 512 or not isPrime(pp):
            continue
        qq = sum(pp ** i for i in range(5))
        if n % (pp * qq) == 0:
            rr = n // (pp * qq)
            if isPrime(rr) and pp * qq * rr == n:
                return pp, qq, rr
    return None

# timing self-test
t0 = time.time()
_a = [random.randrange(n) for _ in range(5)]
mul(_a, _a, n, [n - 1] * 5)
print(f"[*] one Kronecker mult: {(time.time()-t0)*1000:.1f} ms", flush=True)

pqr = None
t_start = time.time()
for attempt in range(1, 121):
    g = try_factor()
    if g:
        print(f"[*] attempt {attempt}: gcd {g.bit_length()} bits", flush=True)
        pqr = reconstruct(g)
        if pqr:
            print(f"[+] factored after {attempt} attempts, {time.time()-t_start:.0f}s", flush=True)
            break
if not pqr:
    raise SystemExit("[-] 120 attempts exhausted")

p, q, r = pqr
print(f"[+] p = {p}")
print(f"[+] q bits {q.bit_length()}, r bits {r.bit_length()}")
assert p * q * r == n and isPrime(p) and isPrime(q) and isPrime(r)

phi = (p - 1) * (q - 1) * (r - 1)
d = pow(e, -1, phi)
m = pow(c_, d, n)
raw = long_to_bytes(m)
print(f"[*] plaintext {len(raw)} bytes; stripping 128-byte tail")
flag = raw[:-128]
print("FLAG:", flag.decode(errors='replace'))
