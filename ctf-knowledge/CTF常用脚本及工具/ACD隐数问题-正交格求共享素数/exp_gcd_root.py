"""1337th roots mod Q via pure group theory (v7(Q-1)=2 path), no sympy"""
from Crypto.Util.number import long_to_bytes
import time

P = 8475751295865335034925394592760419247986527875671629878727167186701425140981793707985425024055132199826439868047385642931090550239766413089832011638673209
N = 68770027076980723946939075792572969610228738501865973895618044035550466673326811210718966610231582633896160130057212343512606374318082678735227998163020559923237005947682357783487924911009663067842443440348588088325506801639924926097944176357432282915587075930988972621730524537492705984723766652062305363027
e = 30899846873
c = 46935517038224473812546067305866276864169387205589347201858550096671613860700878462369638807831295923952343159795466895818221029692119135003812788250010552362110290387383510093277209478665971066986914981717774698233220968427990066291572377851164878122374241804989577737820368814455456808941766309324614067608
Q = N // P
g = 1337
e1 = e // g
d1 = pow(e1, -1, (P - 1) * (Q - 1))
c1 = pow(c, d1, N)                      # c1 = m^1337 mod N
assert pow(c1, e1, N) == c
t0 = time.time()

import random
random.seed(1337)

def elem_of_order(pp, k, tries=10000):
    """element of exact order k (k | pp-1, k prime power), via rho^((pp-1)/k)"""
    t = (pp - 1) // k
    for _ in range(tries):
        rho = random.randrange(2, pp)
        z = pow(rho, t, pp)
        if z == 1:
            continue
        # check exact order k: z^(k/f) != 1 for prime f | k
        if k == 49 and pow(z, 7, pp) == 1:
            continue
        if k == 7 and z == 1:
            continue
        return z
    raise RuntimeError('no element found')

# ---------- mod P (v7=1, v191=0): 7 roots, x = y^(191^-1) where y^7=cp ----------
pp, t = P, P - 1
cp = c1 % pp
s = t // 7
assert pow(cp, s, pp) == 1
y0 = pow(cp, pow(7, -1, s), pp)
z7 = elem_of_order(pp, 7)
roots_mp = set()
for j in range(7):
    y = y0 * pow(z7, j, pp) % pp
    inv191 = pow(191, -1, t)
    x = pow(y, inv191, pp)
    assert pow(x, g, pp) == cp
    roots_mp.add(x)
print(f'[+] mod P: {len(roots_mp)} roots ({time.time()-t0:.1f}s), bits:',
      sorted(x.bit_length() for x in roots_mp))

# ---------- mod Q (v7=2, v191=1) ----------
qq, tq = Q, Q - 1
cq = c1 % qq
assert pow(cq, tq // 7, qq) == 1, 'cq not a 7th power mod Q'
m49 = tq // 49                          # 7-free part
k = pow(7, -1, m49)
y0 = pow(cq, k, qq)
w = y0 * y0 % qq * y0 % qq  # placeholder
w = pow(y0, 7, qq) * pow(cq, -1, qq) % qq          # y0^7 = cq * w, w in mu_7
assert pow(w, 7, qq) == 1                     # w is a 7th root of unity
zeta49 = elem_of_order(qq, 49)
mu7 = {}
cur = 1
for d in range(7):
    mu7[cur] = d
    cur = cur * pow(zeta49, 7, qq) % qq
assert w in mu7, 'w not in generated mu_7'
dcor = mu7[w]
# y = y0 * zeta49^i with 7i == -7dcor (mod 49) -> i == -dcor (mod 7)
i0 = (-dcor) % 7
ys = []
for j in range(7):
    i = i0 + 7 * j
    y = y0 * pow(zeta49, i, qq) % qq
    assert pow(y, 7, qq) == cq % qq
    ys.append(y)
print(f'[+] mod Q: 7 y-roots ({time.time()-t0:.1f}s)')

# x^191 = y: y is a 191st residue (y^((q-1)/191) = m^(q-1) = 1)
H = tq // 191
inv191H = pow(191, -1, H)
h191 = elem_of_order(qq, 191)
roots_mq = set()
for y in ys:
    x2 = pow(y, inv191H, qq)            # x2^191 = y (y has trivial 191-part)
    for j in range(191):
        x = x2 * pow(h191, j, qq) % qq
        assert pow(x, 191, qq) == y % qq
        roots_mq.add(x)
assert len(roots_mq) == 1337
print(f'[+] mod Q: {len(roots_mq)} roots ({time.time()-t0:.1f}s)')

# ---------- CRT + final filter: all 9359 combos are valid roots; keep readable ones ----------
Pinv = pow(P, -1, Q)
hits = []
for mq_ in roots_mq:
    for mp_ in roots_mp:
        m = (mp_ + P * ((mq_ - mp_) % Q * Pinv % Q)) % N
        if pow(m, e, N) == c:
            b = long_to_bytes(m)
            hits.append(b)
print(f'[+] {len(hits)} valid roots total')
flag = None
for b in hits:
    printable = sum(1 for x in b if 32 <= x < 127)
    if printable >= len(b) * 0.95 or b'flag' in b or b'ctf' in b.lower():
        print('[+] readable root:', b)
        flag = b
print('[+] FLAG:', flag)
print(f'[+] total {time.time()-t0:.1f}s')
