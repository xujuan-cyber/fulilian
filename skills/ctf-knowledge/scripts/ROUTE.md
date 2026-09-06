# 脚本路由表（场景 → 脚本路径）
提炼自 [SCRIPTS-INDEX.md](SCRIPTS-INDEX.md)，只收高频实用项；路径均相对本目录，用法与关键参数见 INDEX 对应小节。
## Web
- 双参数组合爆破（邀请码+ID 等） → `双参数爆破脚本/brust.py`
- LFI 日志包含：从 URL 编码日志提取被包含文件输出 → `日志匹配/1.py`
## Crypto / RSA（按已知条件选目录）
- RSA 已知 e、n、c（分解 n 求 d） → `RSA综合脚本利用/已知 e、n、密文 c，求明文 m/`
- RSA e=3 小明文 / Stereotyped 攻击 → `RSA综合脚本利用/e=3 (小公钥指数攻击) (小明文攻击) (tereotyped messages攻击)/`
- RSA e 极大求 d（Wiener 攻击） → `RSA综合脚本利用/已知 e、n，求 d (e极大) (Wiener’s Attack)/`
- RSA 共模攻击（同 m 不同 e） → `RSA综合脚本利用/已知 e1、e2、n (共模攻击) (模不互质)/`
- RSA dp 泄露 → `RSA综合脚本利用/已知 n、e、dp、c，求m (dp 泄露)/`
- RSA dp/dq 泄露 → `RSA综合脚本利用/已知 p、q、dp、dq、c 求明文 m (dp、dq 泄露)/`
- RSA 已知 p、q 求明文/求 d → `RSA综合脚本利用/已知e、p、q、密文c，求明文m/`、`RSA综合脚本利用/已知 e、p、q，求 d/`
- RSA 多组 n、c（中国剩余定理 CRT） → `RSA综合脚本利用/已知多个 n、c (中国剩余定理)/`
- RSA 同 q 攻击 → `RSA综合脚本利用/已知 c1、c2、n1、n2、e的范围 (同公钥（e，n）加密的密文、具有同 q 的公钥加密的密文)/`
- RSA 已知私钥 d 解密 → `RSA综合脚本利用/已知 e、d、c ,求 m/`
- RSA 公钥文件解析（public.pem 提取 n,e） → `RSA综合脚本利用/已知 public key、密文 c，求明文 m (公钥提取)/`
- RSA p、q 接近分解 → `RSA综合脚本利用/已知 e、m1、m2、n、pq 接近 ,求原 m/`
- DES 加解密 → `DES_Python-master/des.py`
- MD5 已知部分明文（? 占位）爆破 → `md5爆破/md5-brust.py`
- 维吉尼亚加解密 → `维吉尼亚加密/exp.py`
- 变异凯撒（逐字符递变偏移） → `变异凯撒/variant_caesar.py`
- ROT13 / ROT47 → `rot/rot.py`
- 四方密码 → `四方密码/sifang.py`
- Nihilist 密码 → `Nihilist密码/nihilist.py`
- 手机键盘 / T9 / 26 键盘密码 → `26键盘密码-手机键盘密码/jianpan.py`
- 通用 XOR+偏移解密模板 → `常用反解密脚本/cryp-1.py`
## 编码 / 解码
- Base64→32→16 链式解码 → `Base/B64-B32-B16解密/`
- Base16/32/64/85 互转 → `Base/b16-b32-b64-b85/`
- Base64 变体（换表/填充变异） → `Base/Base64扩展/`、`字符替换表/zifu_replac.py`
- Base64 隐写（填充位藏信息） → `Base/base64隐写加密与解密/`
- 递归 Base64 直到不可解 → `Base/base64连续解码/`
- 二进制高位补齐 8 的倍数 → `进制互相转换/`
- 穷举 ROT-N（1~128）找可读文本 → `进制转化字符脚本/循环遍历减去1-128数的ASCII码.py`
- hex 倒序 / hex 减位 / 十进制转字符 → `hex倒叙/1.py`、`hex减位/1.py`、`十进制转字符/1.py`
- 二进制每 8 位组内反转 → `二进制每8位倒序/1.py`
- 字符频率统计（替换密码分析） → `字符频率统计分析/test.py`
- 同义词替换密码（谍报） → `谍报-替换普通话/tihuan.py`
- 文本行去重 / 文本转 GBK → `去重/quchong.py`、`文本转gbk编码/1.py`
- 长短行转 0/1 编码 → `替换脚本/space.py`
## Misc / 隐写 / 流量
- PNG IHDR 宽高 CRC 爆破修复 → `图片爆破宽高/1.py`
- 频域盲水印提取（OpenCV） → `频域盲水印/pinyubwm.py`
- CRC32 爆破 1~5 字节（ZIP 小文件/图片头） → `CRC32校验爆破/crc-3byte.py`（按字节数选 `CRC32校验爆破/crc-1byte.py`~`CRC32校验爆破/crc-5byte.py`）
- steghide 密码字典爆破 → `steghide爆破密码/steghide-brute.py`
- TTL 值隐写解码 → `TTL隐写/TTL-stego.py`
- USB HID 键盘流量还原按键 → `usb流量/usbtxt.py`
- pcap 协议数据提取（scapy/ICMP payload） → `流量数据提取脚本/1.py`
- 曼彻斯特 / 差分曼彻斯特解码 → `曼彻斯特编码/decode_man.py`
- 0/1 矩阵转二维码图片 → `字节转二维码/200-erweima.py`
- RGB 三元组文本转图片 → `RGB转图片/rgb.py`
- 多层 ZIP 套娃（密码=文件名） → `批量解压压缩包+带密码/zip.py`
- 压缩包内文件大小判 0/1 → `遍历读取压缩包文件判断1和0/批量图片二进制.py`
- 图片序列按颜色判 0/1 → `红绿灯-二进制/traffic.py`
## Reverse / 辅助
- 相邻字符递推异或解密 → `reverse/xor/xor.py`
- 文件级 XOR（hex 每位异或） → `文件异或/yihuo.py`
- Brainfuck 解释器 → `Python-Brainfuck-master/brainfuck.py`
- Python Pickle 反序列化利用 → `python-Picke序列化/1.py`
