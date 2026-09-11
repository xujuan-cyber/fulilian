from fpylll import IntegerMatrix, LLL
from Crypto.Util.number import long_to_bytes
from math import gcd, isqrt

vals = open('output.txt').read().split()
l = [int(x) for x in vals[:30]]
N = 68770027076980723946939075792572969610228738501865973895618044035550466673326811210718966610231582633896160130057212343512606374318082678735227998163020559923237005947682357783487924911009663067842443440348588088325506801639924926097944176357432282915587075930988972621730524537492705984723766652062305363027
e = 30899846873
c = 46935517038224473812546067305866276864169387205589347201858550096671613860700878462369638807831295923952343159795466895818221029692119135003812788250010552362110290387383510093277209478665971066986914981717774698233220968427990066291572377851164878122374241804989577737820368814455456808941766309324614067608

# ---- step 1: orthogonal lattice via LLL ----
C = 1 << 120
B = IntegerMatrix(30, 31)
for i in range(30):
    B[i, 0] = C * l[i]
    B[i, 1 + i] = 1
LLL.reduction(B)

cands = []
for i in range(30):
    row = [B[i, j] for j in range(31)]
    if row[0] == 0:
        w = row[1:31]
        cands.append((sum(x * x for x in w), w))
cands.sort(key=lambda t: t[0])
U = [w for n2, w in cands if n2 < (1 << 116)]  # |u| < 2^58 => u.q = u.r = 0
print('[+] usable u-vectors:', len(U))
assert len(U) >= 26

# ---- step 2: saturated integer kernel of U via unimodular row reduction ----
# row-reduce U^T (30 x 28) with tracked unimodular ops R: R*U^T = [H; 0]
# -> last 2 rows of R span ker_Z(U) = span_Z(q, r) exactly (saturated)
Mt = [[u[i] for u in U] for i in range(30)]  # 30 rows x 28 cols
R = [[1 if i == j else 0 for j in range(30)] for i in range(30)]

row = 0
for col in range(28):
    piv = None
    while True:
        nz = [r for r in range(row, 30) if Mt[r][col] != 0]
        if len(nz) <= 1:
            piv = nz[0] if nz else None
            break
        r1, r2 = nz[0], nz[1]
        if abs(Mt[r1][col]) > abs(Mt[r2][col]):
            r1, r2 = r2, r1
        q = Mt[r2][col] // Mt[r1][col]
        Mt[r2] = [a - q * b for a, b in zip(Mt[r2], Mt[r1])]
        R[r2] = [a - q * b for a, b in zip(R[r2], R[r1])]
        if Mt[r2][col] == 0:
            nz.remove(r2)
    if piv is not None:
        Mt[row], Mt[piv] = Mt[piv], Mt[row]
        R[row], R[piv] = R[piv], R[row]
        row += 1
print('[+] pivot rows used:', row)

w1, w2 = R[28], R[29]
assert all(v == 0 for v in [sum(u[i] * w1[i] for i in range(30)) for u in U])
assert all(v == 0 for v in [sum(u[i] * w2[i] for i in range(30)) for u in U])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def gauss_reduce(a, b):
    from fractions import Fraction
    while True:
        if dot(a, a) > dot(b, b):
            a, b = b, a
        mu = round(Fraction(dot(a, b), dot(a, a)))
        if mu == 0:
            return a, b
        b = [x - mu * y for x, y in zip(b, a)]


g1, g2 = gauss_reduce(w1, w2)
print('[+] kernel basis norm bits:', isqrt(dot(g1, g1)).bit_length(),
      isqrt(dot(g2, g2)).bit_length(), '(expect ~452 / ~1023)')

# saturated kernel, gauss-reduced => g1 = +-r exactly
P = None
for v in (g1, [-x for x in g1]):
    g = N
    for i in range(6):
        g = gcd(g, l[i] - v[i])
    if 1 < g < N and N % g == 0 and g.bit_length() == 512:
        P = g
        break
assert P is not None, 'P recovery failed'
Q = N // P
print('[+] P =', P)
print('[+] Q bits:', Q.bit_length(), '| P*Q==N:', P * Q == N)

# ---- step 3: RSA ----
phi = (P - 1) * (Q - 1)
assert gcd(e, phi) == 1
d = pow(e, -1, phi)
m = pow(c, d, N)
flag = long_to_bytes(m)
print('[+] flag2 =', flag)
assert pow(m, e, N) == c
print('[+] re-encrypt OK')
