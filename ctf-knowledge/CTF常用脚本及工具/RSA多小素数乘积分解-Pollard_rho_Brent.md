# RSA 多小素数乘积分解（Pollard rho Brent）

## 技术标签
`crypto` `rsa` `多素数` `pollard-rho` `brent` `分解` `multiprime`

## 适用场景
n 由多个小素数（如 15 个 32-bit）乘积构成的多素数 RSA。源码特征：

```python
def gen_prime(n):
    res = 1
    for i in range(15):
        res *= getPrime(n)
    return res
```

## 关键点
- sympy.factorint 对多因子乘积极慢（180s+ 超时），不要用。
- 直接对 n 递归跑 Pollard's rho（Brent 变体，批量乘积 gcd 优化），15 个 32-bit 素数秒级拆完。
- 拆出全部素数 p_i 后 phi = prod(p_i - 1)，标准 RSA 解密。
- 回验：prod(factors) == n 且每个因子 bit_length() == 32。

## 实战验证
NSSCTF [SWPU 2019]（n=1729006607...482261）：秒级分解出 15 个素数，
flag{us4_s1ge_t0_cal_phI}。脚本见同名 .py。
