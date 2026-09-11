# RSA d=p^21+q^17 泄露 d 低 300 位（Hensel + Coppersmith LSB）

## 技术标签
`crypto` `rsa` `coppersmith` `known-lsb` `hensel` `2-adic` `p21q17` `d泄露`

## 适用场景
源码形如：d = p^a + q^b（本题 a=21, b=17），且泄露 d 的低 300 位：
d1 = d & (2^300-1)，n = p·q（512-bit 素数），e=65537。

## 关键点
1. mod 2^300 下 q ≡ n·p^-1（n、p 均奇），代入得单变量多项式：
   f(x) = x^38 − d1·x^17 + n^17 ≡ 0 (mod 2^300)，其根含 p mod 2^300。
2. f' (mod 2) 恒 0 → 必须逐位 Hensel 枚举分支（实测根数 4~128 个，可控）。
3. p = r + 2^300·y，y < 2^212 << N^(1/4)=2^256 → 线性多项式 Coppersmith（已知 LSB）。
   - **A 的符号**：f(y') = y' + A，A = (center + r·inv2^300) mod N（因为 2^300·f = r + 2^300·(center+y') = p ≡ 0 mod p），写负号格基就解不出。
   - y ∈ [2^211, 2^512-300=2^212)（p 是 512-bit），中心取 1.5·2^211，X = 2^210。
   - 参数 m=t=6（dim 13，余量 ~149 bit）；m=t=3 时余量仅 ~18 bit，实例差时失效。
4. LLL 用 fpylll（sympy 的 .lll() 对大整数 OverflowError）。
5. 求根：sympy nroots 不收敛、Sturm intervals 太慢；用 mpmath 平衡缩放
   （coeff·X^k，精度 3200bit）+ 候选整数精确 eval 验证，秒级。

## 陷阱
- d1 是偶数（v2=1），f(1)=0 mod 2，根存在性 OK。
- 明文 = flag + os.urandom(60)，解密结果要取可打印前缀。

## 实战验证
DASCTF 题（2026-09-06），8 个 2-adic 根，数秒内分解出 p/q，
flag DASCTF{0psu3_is_the_most_Greatest_army}。脚本见同名 .py（solve + numroot 两个文件，需同目录）。
