# RSA 特殊结构 n 分解（DASCTF 1z_RSA, e=3）

## 结构
p,q 均 130bit 素数，n = PQ*QP，其中
PQ = int(str(p<<120)+str(q))，QP = int(str(q<<120)+str(p))
即 n = pq·D + 2^120·S，D = 2^240·10^(a+b)+1，S = p²·10^b + q²·10^a（a=digits(p), b=digits(q)，各 39 或 40，4 种组合枚举）

## 解法步骤
1. pq mod 10^min(a,b)：D 对小模数可逆，n·D⁻¹ mod 10^min(a,b) = pq mod 10^min(a,b)
2. n//D ≈ pq（误差仅 2^12 量级），K=2^14 暴力扫 s 补偿误差
3. S = (n − pq·D) >> 120，w=p² 满足 w²·10^b − S·w + pq²·10^a = 0，二次方程整数开方解出 p,q
4. PQ、QP 验证 PQ*QP==n 且均为素数
5. PP=nextprime((PQ>>190)*(QP&2^190−1))，QQ 同理，N=PP*QQ（可自算，无需给出）
6. gcd(3,φ)=3 时 CRT 枚举 9 个立方根，用 M = m mod l 过滤唯一真根
7. m = flag(29B)+os.urandom(64)，long_to_bytes 后取前 29 字节

## 关键点
- 低位先知：拼接结构 mod 10^k 泄露 pq 低位，高位用 n//D 近似
- 多解过滤：e 与 φ 不互质时立方根多解，题目附赠 M=m mod l 就是过滤器
