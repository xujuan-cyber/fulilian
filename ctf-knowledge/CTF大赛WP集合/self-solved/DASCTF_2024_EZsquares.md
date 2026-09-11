# EZsquares（DASCTF, 2024）— RSA 只给 p²+q²

赛事：DASCTF 系列（据 flag 前缀推断，附件 mtime 2024-08）；分类：crypto；难度：medium
Flag：DASCTF{4028d59bb18028e2df8d5d51b376908c}

## 题目本质

RSA 加密 c = m^e mod n，n = p·q（p,q 均 512bit），但不给 n，只给 n0 = p² + q²。要解密必须先从 n0 恢复 n 或 p,q。

## 核心数学

关键恒等式（u = (p+q)/2, v = (p−q)/2）：

- n0/2 = u² + v²（因为 (p²+q²)/2 = ((p+q)/2)² + ((p−q)/2)²）
- n = p·q = u² − v² = (u+v)(u−v)

所以只要找到 n0/2 的任一平方和表示 u²+v²，就立即得到 n = u²−v²。本题 n0/2 ≡ 1 (mod 4)，n0 的所有奇素因子都 ≡ 1 (mod 4)，每个这样的素因子 r 在高斯整数里裂成共轭对 π·π̄（r = a²+b²，用 Cornacchia 求 a,b）。

求表示的正确路线：分解 n0/2（本例 FactorDB 直接秒出：n0 = 2 × 37 × 2843693 × 37573771429 × P456），对每个素因子跑 Cornacchia(1,1,r)，再在 2^k 种共轭组合（k = 素因子个数，本例 4 → 16 种）里枚举乘积 (x+iy) = ∏π_i 或 π̄_i，检查 p=|x±y|、q=|x∓y| 是否都是 512bit 素数且 p²+q² = n0。

## 踩坑记录

- 先试了 Fermat 式向下搜索（p≈q 时 u 接近 isqrt(n0/2)）：本题 p、q 差异大，1e6 步内无解。别在无 p≈q 证据时赌平方和的 Fermat 搜索。
- sympy 的 cornacchia 返回 set of tuples，取 sorted(sols)[0] 再解包，直接下标会报 TypeError。
- 知识库里绿城杯那篇是变体（同时给了 p²+q² 和 q²·q²，直接开平方差），最小信息版（只有 n0）必须走高斯整数路线。

## 关键脚本（完整可跑）

```python
from itertools import product
from sympy import isprime
from sympy.solvers.diophantine.diophantine import cornacchia
from Crypto.Util.number import long_to_bytes

n0 = <p*p+q*q 的值>; c = <密文>; e = 65537
facs = [/* n0 的奇素因子列表，FactorDB 查询 http://factordb.com/api?query=<n0> */]

greps = []
for r in facs:
    s = sorted(cornacchia(1, 1, r))[0]   # r = s[0]^2 + s[1]^2
    greps.append((s[0], s[1]))

found = None
for conj in product([1, -1], repeat=len(greps)):  # 每个素因子取 π 或共轭
    x, y = 1, 0
    for (a, b), sg in zip(greps, conj):
        x, y = x*a - y*sg*b, x*sg*b + y*a
    for u, v in ((x, y), (y, x)):
        for vv in (v, -v):
            p, q = abs(u + vv), abs(u - vv)
            if p*p + q*q == n0 and isprime(p) and isprime(q):
                found = (p, q); break
        if found: break
    if found: break

p, q = found
n = p * q
d = pow(e, -1, (p-1)*(q-1))
print(long_to_bytes(pow(c, d, n)))
```

注意 u,v 交换与 v 取负都要试：(u+iv) 与 (iu+v) 交换 u/y 位置、v 正负对应 p−q 的符号与共轭差异，枚举全部四种形态最稳。

## 复盘教训

1. 见到 "RSA 只给 p²+q²"：先查 n0/2 mod 4 和小素因子，然后直接 FactorDB + Cornacchia + 共轭枚举，不要手写平方和搜索。
2. n0/2 的每个平方和表示都给出合法 n（对同一场 p+q、p−q 配对），但只有一组使 p,q 都是 512bit 素数——用 isprime + bit_length 过滤。
3. FactorDB API（http://factordb.com/api?query=N）是 CTF 整数分解的第一站，status FF 表示已完全分解。
