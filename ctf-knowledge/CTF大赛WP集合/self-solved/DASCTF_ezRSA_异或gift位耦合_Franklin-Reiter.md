# DASCTF ezRSA — gift=P^(Q>>16) 位耦合分支定界分解 N + Franklin-Reiter 恢复 secret

## 题目

- 附件：ezRSA.py（e=11，512bit 素数 p,q 与 P,Q 两组）
- 输出五数：`N=P*Q`，`gift = P ^ (Q>>16)`，`pow(n, e, N)`（n=p*q，不出现在输出里），`c1=secret^11 mod n`，`c2=flag^11 mod n`
- 关系：`flag = b"dasctf{" + secret + b"}"`
- Flag（平台提交）：`flag{C0pper_Sm1th_Mak3s_T1ng5_Bet4er}`
- Flag（源码 assert/密文实际明文）：`dasctf{C0pper_Sm1th_Mak3s_T1ng5_Bet4er}`（pow(flag,11,n)==c2 端到端回验）

## 核心链条（三段）

### 1. gift 位耦合 → 分支定界分解 N

`gift = P ^ (Q>>16)` 把 P 的第 i 位与 Q 的第 i+16 位绑定：`P[i] = gift[i] ^ Q[i+16]`。

- P 的**高 16 位直接等于 gift 的高 16 位**（Q 右移后 P 高位无耦合对象）。
- 从最高位往低位逐位搜索，状态 = `(P>>i, Q>>(i+16))`，即已知两个被除数的高位。
- 每个 gift 位只产生 P/Q 两个互补选择，共 2 路分支；用缩放区间剪枝：

```
Ms = N >> (2i+16)          # 注意与状态同尺度！
保留分支当且仅当  P2*Q2 <= Ms < (P2+1)*(Q2+1)
```

P∈[P2·2^i,(P2+1)·2^i)，Q∈[Q2·2^(i+16),(Q2+1)·2^(i+16))，因此 P·Q 落在 [P2·Q2·2^(2i+16), (P2+1)(Q2+1)·2^(2i+16))，与 N 比较即可——整体右移 2i+16 位后区间缩成单点宽度 1，剪枝极强（实测全程单候选）。
- Q 的低 16 位不出现在 gift 里，由 `N mod 2^16 = (P mod 2^16)(Q mod 2^16) mod 2^16` 隐式固定，无需枚举。
- 终点校验：`N % P == 0` 且重算 `P ^ (Q>>16) == gift`。

### 2. 由 pow(n,11,N) 恢复 n

`gcd(11, phi(N))==1`，`r = pow(cN, 11^{-1} mod phi(N), N)` 得到的是 `n mod N`。
关键坑：n=p·q ∈ (2^1022, 2^1024)，而 N 只有 1023 bit，**n 可能大于 N**，候选集 = {r, r+N}，按 bit_length ∈ [1022,1024) 过滤。

### 3. Franklin-Reiter 相关消息攻击（e=11 小指数）

m1 = secret，m2 = 完整 flag。二者满足仿射关系：

```
m2 = m1 * 2^(8k) + B,  k = len(secret)+1?  —— 精确式：
B = bytes_to_long(b"dasctf{") << (8*(L+1)) | ord('}')   # L = len(secret)
```

对 L=0..120 枚举，在 mod n 上求：

```
gcd( x^e - c1 ,  (2^8·x + B)^e - c2 )  ≡  x - m1  (mod n)
```

多项式 gcd 用 Python 手写 pdivmod/pgcd（模素性未知，遇不可逆首项系数跳过）。得到一次式后 `m1 = -g0/g1`，用 `pow(m1,11,n)==c1` 验证。
注：secret 本身与 c1 之间没有已知前缀结构（secret 前面不是定长头），必须用"完整 flag 已知头 dasctf{ + 尾 }"这一对做相关消息，secret 由 gcd 根反解。

## 坑位记录

1. 剪枝区间必须右移到与搜索状态相同的尺度（N>>(2i+16)），直接拿 N 与 P2·Q2·2^(2i+16) 混比会第一轮全灭。
2. gift 的位配对是 `gift[i] = P[i] ^ Q[i+16]`（不是 P[i]^Q[i-16]），方向搞反 B&B 立即死。
3. n 恢复要试 r 和 r+N 两个候选。
4. e-th root 快速通道：本题 secret/flag 均非全零填充，plain root 不命中，属备选不属主线。

## 复现

通用脚本：`CTF常用脚本及工具/RSA_gift异或位耦合分解N_Franklin-Reiter.py`
（输入 N, gift, cN, c1, c2 五数，自动走完三段链输出 flag）
