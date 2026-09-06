# Crypto 知识卡

> 2024-2026 考点补充：RSA 决策树（按 e/n 特征分支）、格密码 LLL 常见构造。

## 常用工具
- Python：pycryptodome, gmpy2, sympy, z3, sage（small_roots/LLL 必备）；RsaCtfTool
- 分解：factordb.com 在线 → yafu/msieve → ECM（小因子）→ cado-nfs（超大数）
- 杂项：hashcat/john（口令）、CyberChef（编码）、randcrack/untwister（随机数）

## RSA 决策树（按 e 与 n 特征分支，逐条过）
- 万能第一步：factordb 查 n；分解成功走常规 m=pow(c,d,n)
- e=3 低指数且 m^e < n：gmpy2.iroot(c, e) 直接开根
- 同 e=3 多组 (n_i, c_i)：Håstad 广播——CRT 合并后开 e 次根
- e 很大（接近 n）：Wiener 连分数（d < n^0.25）；不中再上 Boneh-Durfee（d < n^0.292，sage）
- 同 n 两组 (e1,e2) 互素：共模攻击，ext_gcd 求 s1,s2 线性组合出明文
- gcd(e, φ) = g > 1：e 与 φ 不互素——对 c 开 g 次根（g 小用 iroot；g 大用 AMM/有限域开根再枚举验证）
- 已知 p 高位或低位若干 bit：Coppersmith——sage `f.small_roots()`（f = x + 已知部分<<k，beta=0.4）
- 已知 dp：遍历 k ∈ (0,e)，p = (e*dp-1)/k + 1，n%p==0 即命中（dq 同理）
- 已知 dp+dq：m = CRT(pow(c,dp,p), pow(c,dq,q), p, q)——sympy.ntheory.modular.crt 一行出明文，别再去推 d
- 已知部分 d 低位：Coppersmith 2d 变体恢复；已知明文片段：Franklin-Reiter 相关消息攻击
- p、q 相近：Fermat 分解（sqrt(n) 附近步进）；n 是完全平方/立方：直接开方得因子
- 多组 n 两两 gcd 非平凡：公因数直接出因子
- 题目额外给关系式（p+q、p-q、p^2+q^2、ed 的余项）：sympy/z3 解方程组
- n 很大又分解不动：回头检查题目是否真要分解——多数是参数误用/侧信道题
- RsaCtfTool `--attack all` 适合开局一键试探常见攻击
- e1,e2 不互素：先 gcd 缩指数再按上面分支走；e*known_part 变形题先把已知量代入再分支
- Boneh-Durfee 脚本要点：small_roots(X=2^bitlen, beta=0.4)，m 参数 3-6 逐个试
- 大数开根：gmpy2.iroot(n, k) 返回 (root, is_exact) 元组，别只取第一个返回值

## 格密码与 LLL（sage 必备）
- 通用套路：把"未知小量的线性关系"化成格矩阵 → M.LLL() → 第一行即还原未知数（大常数 K 平衡量级是成败关键）
- 线性方程格：a1x1+...+anxn=b（系数/模数未知）→ 行向量 [I | K*a] LLL 消 K 列得 x
- NTRU：h = f^-1*g mod q → 格 [[I, H],[0, qI]]，LLL 直接出 f,g（维度 2N，一次就中）
- 背包（Merkle-Hellman 超递增）：CJLOSS 格，密度 < 0.9408 可解出明文位
- LCG 状态恢复：递推式转线性关系 → 格消未知增量；只拿到高位截断输出 → Coppersmith
- MT19937：攒够 624 个 32bit 输出即可还原状态预测后续（randcrack）
- ECDLP：阶光滑 → Pohlig-Hellman；反常曲线 t=p → Smart's attack；嵌入度小 → MOV；小阶点 → BSGS
- LFSR：Berlekamp-Massey 求极小多项式再解初态（GF(2) 上注意多项式方向）
- 高维格 LLL 不出解：换 BKZ（block_size 20-30），或增删约束列减少自由度
- 格构造口诀：目标向量 = 公开线性组合 + 小未知量；小量放单位阵 I，方程行/列乘大常数 K 平衡量级
- 通用模板：L = Matrix(ZZ, rows); L.LLL() 取 row(0)，结果带负号就整体取反再验证

## 对称/哈希/编码
- AES：ECB 逐字节/pixel 泄露、CBC 比特翻转（改前一块异或目标位）、Padding Oracle 恢复明文
- 哈希：MD5 碰撞(fastcoll)、长度扩展(hashpumpy，Secret||data 结构)、弱种子（seed=time() 可爆破）
- DH：小子群注入、共享素数 p 的阶光滑 → Pohlig-Hellman 求 a
- DES/3DES：ECB 分组重排、弱密钥（0x0101..）、已知明密对推主密钥
- 其他公钥：Paillier/GM/ElGamal 按同态性质出题——先恢复随机数 r
- 古典：维吉尼亚/仿射/栅栏/培根/Playfair/键盘密码——先频率分析再上工具
- n 结构特殊：n=p^2 直接 φ=p(p-1)；p=q 直接 φ=p(p-1) 同式；给 p±q、p^2+q^2 等关系转方程组（见决策树）

## 常见思路
1. 读附件分类：n,e,c 三元组 → RSA 决策树；.pem → openssl rsa -text -noout；server.py → 找 RNG 误用
2. 密文短+e 小 → 先开根；密文长 n 大 → 先查 factordb 再谈格
3. 有交互：盯 nonce 复用、AES-ECB 分块泄露、随机数可预测
4. 非线性约束/小空间枚举 → z3；开根/求逆 → gmpy2（注意 iroot 返回元组）
5. Coppersmith/LLL 类题没装 sage 先装 sagemath，别手写格
6. 新算法题：diff 原始标准实现，改动的那一行就是考点
7. 输出为超长数字/串：先试进制与 ASCII 转换，再当密文处理

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`, `crypto{...}`
