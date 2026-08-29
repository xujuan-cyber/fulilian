# Crypto 知识卡

## 常用工具
- Python（pycryptodome, gmpy2, sage, z3）, openssl, CyberChef, RsaCtfTool, hashcat, john

## 常见漏洞 / 考点
- **RSA**: p/q 分解（Fermat, yafu, factordb）、共模攻击、低指数、Wiener、
  Boneh-Durfee、Coppersmith、dp/dq 泄露、广播攻击
- **AES/DES**: ECB 字节翻转、CBC 比特翻转、Padding Oracle
- **哈希**: MD5 碰撞、长度扩展、弱签名验证
- **古典密码**: 凯撒、维吉尼亚、Atbash、培根、栅栏、Playfair
- **编码**: Base64、Hex、Base58、Base91、UUencode、变种编码
- **ECC**: 离散对数、Pohlig-Hellman、Smart Attack、MOV
- **LCG**: 线性同余参数恢复、截断状态恢复
- **LFSR**: Berlekamp-Massey 算法、流密码恢复

## 常见思路
1. 识别加密类型（密文长度/字符集/已知明文格式）
2. RSA 题优先试 factordb 和 yafu 分解
3. AES 块加密题：检查 ECB/CBC 模式漏洞
4. 古典密码题：先做频率分析，判断替换/换位
5. 编码题：识别 Base64 特征（`=` 填充、A-Za-z0-9+/）

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`