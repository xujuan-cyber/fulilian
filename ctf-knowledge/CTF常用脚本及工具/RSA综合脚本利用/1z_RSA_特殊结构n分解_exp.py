from math import isqrt, gcd
from sympy import nextprime, isprime
from Crypto.Util.number import long_to_bytes, inverse

n = 18339446336492672809908730785358232636383625709800392830207979464962269419140428722248172110017576390002616004691759163126532392634394976712779777822451878822759056304050545622761060245812934467784888422790178920804822224673755691
M = 36208281423355218604990190624029584747447986456188203264389519699277658026754156377638444926063784368328407938562964768329134840563331354924365667733322
l = 56911058350450672322326236658556745353275014753768458552003425206272938093282425278193278997347671093622024933189270932102361261551908054703317369295189
c = 720286366572443009268610917990845759123049408295363966717060100862857351750759651979922104897091176824666482923148635058966589592286465060161271579501861264957611980854954664798904862706450723639237791023808177615189976108231923

print("n bits:", n.bit_length(), "| l bits:", l.bit_length(), "| M bits:", M.bit_length())

PQ = QP = p = q = None
for a in (39, 40):      # digits(p)
    for b in (39, 40):  # digits(q)
        D = 2**240 * 10**(a+b) + 1
        mod = 10 ** min(a, b)
        t = (n * inverse(D % mod, mod)) % mod   # pq mod 10^min(a,b)
        E = n // D
        K = 1 << 14
        for s in range(max((E - K - t) // mod - 1, 0), (E + K - t) // mod + 2):
            pq = t + s * mod
            R = n - pq * D
            if R <= 0 or R % (2**120):
                continue
            S = R >> 120
            disc = S*S - 4 * 10**(a+b) * pq * pq
            if disc < 0:
                continue
            r = isqrt(disc)
            if r*r != disc:
                continue
            for sign in (1, -1):
                num = S + sign * r
                if num % (2 * 10**b):
                    continue
                w = num // (2 * 10**b)
                rt = isqrt(w)
                if rt*rt != w:
                    continue
                pp, qq = rt, pq // rt
                if pp * qq != pq:
                    continue
                PQc = int(str(pp << 120) + str(qq))
                QPc = int(str(qq << 120) + str(pp))
                if PQc * QPc == n and isprime(PQc) and isprime(QPc):
                    PQ, QP, p, q = PQc, QPc, pp, qq
                    break
            if PQ: break
        if PQ: break
    if PQ: break

assert PQ, "factoring failed"
print("p =", p); print("q =", q)
print("PQ*QP==n:", PQ*QP == n)

PP = nextprime((PQ >> 190) * (QP & (2**190 - 1)))
QQ = nextprime((QP >> 190) * (PQ & (2**190 - 1)))
N = PP * QQ
print("N bits:", N.bit_length())

phi = (PP-1)*(QQ-1)
g = gcd(3, phi)
print("gcd(3,phi) =", g)

def cbrt_roots(ct, pr):
    from sympy.ntheory.residue_ntheory import nthroot_mod
    if (pr - 1) % 3:
        return [pow(ct, inverse(3, pr-1), pr)]
    r = nthroot_mod(ct % pr, 3, pr, all_roots=True)
    return r if isinstance(r, list) else [r]

if g == 1:
    m = pow(c, inverse(3, phi), N)
    print("direct d works; m%%l==M:", m % l == M)
else:
    cands = []
    for x in cbrt_roots(c % PP, PP):
        for y in cbrt_roots(c % QQ, QQ):
            mm = (x * QQ * inverse(QQ, PP) + y * PP * inverse(PP, QQ)) % N
            if mm % l == M:
                cands.append(mm)
    print("M-filtered candidates:", len(cands))
    m = cands[0]

data = long_to_bytes(m)
print("pt len:", len(data), "head:", data[:32])
print("FLAG:", data[:29].decode())
