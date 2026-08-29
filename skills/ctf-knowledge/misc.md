# Misc 知识卡

## 常用工具
- Python（标准库 + pycryptodome）, CyberChef, strings, foremost, binwalk
- 浏览器（查看页面源码/控制台/LocalStorage）

## 常见考点
- **编码/解码**: Base64/58/91/92/85, Hex, Ascii85, Quoted-printable, URL encode,
  Unicode（XXencode, UUencode）, Brainfuck, Ook!, JSFuck
- **古典密码**: 凯撒, Atbash, 维吉尼亚, 培根, 栅栏, 仿射, Playfair, 键盘密码
- **图片/音频隐写**: 同 Forensics 知识卡
- **社工/OSINT**: 搜索 ID/昵称/邮箱 → 找关联信息；图片反搜（Google/Bing）；
  WhatsApp/Telegram 群组、Twitter 搜索
- **编程题**: 算法实现、正则表达式、数据清洗、协议解析
- **脑洞/冷知识**: 十六进制转 ASCII、时间戳、坐标经纬度、进制转换、emoji 编码
- **流量分析**: 同 Forensics 知识卡
- **区块链/智能合约**: 交易分析、erc20 事件、sstore/gas 分析
- **IoT**: 固件分析（binwalk）、串口协议、MQTT/CoAP 协议

## 常见思路
1. 看题目描述和附件 → 判断是编码/密码/隐写/编程哪一类
2. 先试 Base64（`echo "..." | base64 -d`）
3. 可打印字符? 检查字符集频率，判断编码类型
4. 二进制文件 → 看文件头（`file` 命令）→ `binwalk` 分析
5. 有交互 → 写脚本自动化（Python requests 或 pwntools）
6. OpenChat 脑洞题 → 搜索类似题目 / 读题面暗示

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`