# DASCTF_2023_MathFactor

## 0x00 题目
- 附件：task.sage + output.txt（200 组 message 与 enc），flag 前缀 DASCTF
- 关键代码：
  - 素数生成 `get_Prime_leak(bits,t1)`：`(x,y)` 初值 `(0,1)`，迭代 `(x,y)=(u·x+t1·v·y, v·x−u·y)`，u,v∈randint(1,200)；当 `x.bit_length()<=bits//2` 时取 `p = x^2+t1*y^2 | 1`，素性通过即返回
  - `t1=getPrime(16)` 公开；n=pq，p>q，均 512+ bit
  - 加密 `enc_i = pow(64901, message_i ^^ flag, p)` —— **模 p 不是 n**，且 mask 是 flag 本身
- 数据：t1=39041，n（task.sage 注释给出，1034 bit）

## 0x01 结构分析：范数恒等式
迭代是虚二次域 Q(√−t1) 中乘以 (u+v√−t1)：范数满足
`(ux+t1vy)^2 + t1(vx−uy)^2 = (u^2+t1v^2)(x^2+t1y^2)`
初值范数 = t1 ⇒ norm = t1·∏(u_i^2+t1 v_i^2)。每个因子 ≤ 200²+39041·200² ≈ 1.56e9 < 2^31。
⇒ **p−1 全部素因子 ≤ 2^31，完全 2^31-smooth** ⇒ Pollard p−1 可解。

## 0x02 结构化 Pollard p−1（避免 gcd 提前=n）
p、q 由同池同构生成：把 a=2^t1 逐个乘池中 f=u²+t1v²，每步 gcd(a−1,n)。
- 随机打乱因子顺序，命中即停；gcd=n 时重洗重跑（对 n=2^1034 每步约 80µs，2~3 万步内命中）
- 实测 attempt 0 第 25522 步出因子，2.1s
- 旁证校验：p≡q≡1 (mod t1)、n≡1 (mod t1)、n 末位 ...0001（尾数大量 2/5 因子聚集）

## 0x03 p−1 完整分解（模型失配的教训）
按理论模型 (p−1)/t1 应恰好等于 ∏(池中 f)，但真实数据剥离后残差 ~2^200。
**先本地模拟生成器验证模型**（模拟中模型完美成立）⇒ 说明命题人实际生成参数与附件脚本有出入（可能是更宽的 rand 上界）。
不纠结：对残差直接 factorint —— **残差同样完全光滑**（p−1 最大素因子 105568889≈2^27，q−1 最大 20309129），sympy 秒级完整分解。u,v≤3000 的池剥离把残差从 500 bit 压到 <260 bit 是 ECM/因子机友好规模。

## 0x04 Pohlig-Hellman 求离散对数
- g=64901，先求 ord(g)（从 p−1 逐素因子除）：517 bit，因子全部 ≤2^27
- 每 DLP 只需一个未知量 e_i=m_i^flag mod ord(g) < 2^183 ≪ ord(g) ⇒ CRT 精确恢复无歧义
- BSGS 表按素因子缓存（36 个素因子），首个 DLP 0.1s
- flag = message_0 ⊕ e_0 = `DASCTF{0psu3G0d3Best_%}`
- 全量验证：200 对 pow(64901, m_i^flag, p)==enc_i 全部一致

## 0x05 复用要点
- 「迭代 (x,y)→(ux+t1vy, vx−uy)」= 虚二次域乘法，范数恒等式是识别 p−1/p+1 结构的钥匙；初值范数决定 p∓1 的固定因子
- 结构化 Pollard p−1：因子池显式构造 + 洗牌重试防 gcd=n；p≡1 mod t1 是廉价旁证
- c=g^(m⊕flag) mod p 型：模数是素因子之一 ⇒ 分解后 Pohlig-Hellman；e_i 的比特长度远小于 ord 保证 XOR 逆唯一
- 附件脚本模型与真实数据失配时：先模拟器对照定位失配，再对残差直接光滑性验证，不硬磕模型
