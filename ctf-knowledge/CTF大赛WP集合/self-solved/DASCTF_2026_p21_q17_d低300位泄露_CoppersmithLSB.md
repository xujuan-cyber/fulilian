# DASCTF d=p^21+q^17 泄露d低300位（Hensel + Coppersmith LSB）

2026-09-06 DASCTF crypto，实测耗时约 45 分钟（其中 ~35 分钟从零造求解器踩 5 坑——本文目标就是让下次检索命中后 10 分钟内做完）。

## 题目

```python
p=getPrime(512); q=getPrime(512); n=p*q
d=(p**21+q**17)
d1=d&(2**300-1)          # 泄露 d 低 300 位
flag=flag+os.urandom(60) # 明文带随机填充
# 给出 n, e=65537, c, d1
```

## 核心思路

mod 2^300 下 q ≡ n·p⁻¹（n、p 均奇），代入 d1 ≡ p²¹+q¹⁷ 得单变量多项式：

f(x) = x³⁸ − d1·x¹⁷ + n¹⁷ ≡ 0 (mod 2^300)，其根含 p mod 2^300。

f'(x) ≡ 0 (mod 2)（38、17 次项系数含 2 因子）→ 经典 Hensel 提升失效，改逐位枚举分支，实测根数 4~128 个，可控。拿到 p mod 2^300 = r 后，p = r + 2^300·y，y < 2^212 ≪ N^(1/4)=2^256，线性多项式 Coppersmith（已知 LSB）收尾。

## 关键实现与坑

1. **A 的符号（最大坑）**：f(y') = y' + A，A = (center + r·inv) mod N，inv = (2^300)⁻¹ mod N —— 因为 2^300·f(y') = r + 2^300·(center+y') = p ≡ 0 (mod p)。"约等于 p−r" 式的负号直觉在这里是反的，写反格基永远解不出。
2. **y 的区间**：p 是 512-bit，y ∈ [2^211, 2^212)，中心 = 1.5·2^211 = 3·2^210，X = 2^210（不是 2^211）。
3. **格参数**：m=t=3（dim 7）余量仅 ~18 bit，随机实例下 Howgrave-Graham 条件可能失效；m=t=6（dim 13）余量 ~150 bit，稳定。LLL 用 fpylll —— sympy `Matrix.lll()` 对大整数 OverflowError。
4. **求根**：deg12、系数 3000+ bit 的短向量多项式：sympy `nroots` 不收敛、Sturm `intervals` 分钟级超时。用 mpmath 平衡缩放（balanced 系数 c_k·X^k，prec=3200，z=y/X∈[−1,1]）秒级出全部根，候选整数回代**精确 eval 验证**（P(cand)==0），再 N % p == 0 确认。
5. **明文**：flag + os.urandom(60)，解密结果取可打印前缀。

## 流程

```
hensel_roots(f(x)=x^38−d1·x^17+n^17, m=300)   # 逐位枚举, 得 8 个根
for r in roots:                                # 含真根 p mod 2^300
    coppersmith_lsb(r, N, shift=300, m=6, t=6) # fpylll LLL dim13
    # A=(center+r*inv)%N, X=2^210; mpmath 求根 + 精确验证 → p
d = pow(e, -1, (p-1)*(q-1)); m = pow(c, d, n)  # flag 前 33 字节
```

实测：8 根中靠前根即命中，数秒分解。p·q==n 回验通过。

## 可复用判据

- d = p^a + q^b 型且泄露低位 → mod 2^k 消元 + Hensel 分支，通用套路。
- 已知素数低位 < N^0.25 时线性 Coppersmith；格基实现三件套：fpylll（LLL）+ mpmath 平衡缩放（求根）+ 精确整数 eval（验证），全程不依赖 sympy 数值稳定性。
