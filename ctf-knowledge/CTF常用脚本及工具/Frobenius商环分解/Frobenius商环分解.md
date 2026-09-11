# Frobenius 商环分解（GeneratePrime 型 RSA）

SOURCE: CTF常用脚本及工具/Frobenius商环分解
TITLE: Frobenius 商环分解 n = p·q·r，q = 1+p+…+p^(d-1)

## 适用结构
n = p · q · r，其中 q = 1+p+p²+…+p^(d-1) 为素数（即 Φ_d(p)）。
⇒ q | p^d − 1，p 的模 q 阶整除 d。实例：DASCTF x 0psu3 2023 GeneratePrime（d=5，p=512b，q=2047b，r=2560b，n=5118b）。

## 原理
在 R = Z_n[x]/(f)（f 随机首一 d 次）中取随机 z，计算 z^n：
- 若 f mod p 为 d 次不可约（概率≈1/d），A = F_{p^d}，Frobenius z↦z^p 生成 Gal(A/F_p)，
  z^q ∈ 不动域 F_p*，即常数多项式；
- z^n = (z^q)^{pr} 仍为常数 ⇒ **所有非常数系数 ≡ 0 (mod p)**；
- gcd(z^n 的 deg-1 系数, n) = p。f mod p 非 5 次不可约时换 f 重试即可（while True）。

## 实现要点（纯 Python）
- Kronecker 替换：系数打包进大整数（limb = 2·n.bit_length()+6 bit）做乘法，拆包后按
  x^(d+j) ≡ −f_j·x^j 折减——折减目标是 acc[(k−d)+j]，不是 acc[j]；
- 4-bit 窗口平方乘：5118-bit n 单次环形乘 ~1ms，每次尝试 ~6s，期望 ~5 次；
- **gcd 只取 deg-1 系数**：全系数 gcd 会被随机常数项杀成 1（实测 40 连败的根因）；
- Sage 对应：`R=Zmod(n)['x']; Q=R.quo(R.random_element(d)); gcd(ZZ(list(Q.random_element()^n)[1]), n)`；
  注意 Sage `^` 是幂、Q.random_element() 默认 deg<d。

## 验证
p·q·r == n、isPrime(q)、isPrime(r)、pow(pow(c,d,n),e,n)==c 全通过（真实数据）。

相关：[[ctf-crypto]]、[[prng]]
