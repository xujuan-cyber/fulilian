# Misc 知识卡

> 2024-2026 考点补充：零宽字符隐写、OSINT 常规套路精简版。

## 常用工具
- Python（标准库+pycryptodome）, CyberChef, 010 Editor, foremost/binwalk, zsteg
- 命令行替代：base64/base32 -d、xxd -r -p、iconv、chardet（编码探测）
- 浏览器控制台；图片反搜：Google Lens / Yandex / Bing / 百度识图

## 编码与文本隐写
- Base 族速判：Base64([A-Za-z0-9+/=]) / Base32([A-Z2-7=]) / Base58(无0OIl) / Base85、Hex、摩斯、HTML 实体
- 零宽字符隐写：U+200B/200C/200D/U+FEFF/U+2060 混在正常文本里 → `python3 -c "print(open('f').read().encode())"` 看 e2 80 8b 等序列 → 按位解码（zwsp 脚本/stegcloak）
- 其他文本隐写：SNOW（空格/tab）、Emoji 编码、同形字（不同 Unicode 码位）、字体隐写
- 图形类密码：猪圈/跳舞小人/银河字母/敲击码/电话九键/与佛论禅——特征图案对照识别
- 摩斯变体：分隔符可能是 / 空格或大小写混合，先归一化再解码
- CyberChef Magic 配方可一键猜编码；多层编码从内往外剥
- Base64 变体：URL-safe(-_)、自定义字母表——对不上就试换表
- 进制陷阱：hex 转 str 用 bytes.fromhex；int(s, 2) 与 binascii 别混用
- 古典密码速判：培根(AAAAA/AAABA 5位一组)、栅栏(重排)、维吉尼亚(密钥循环)、rot47(ASCII 33-126)——CyberChef 对应模块逐个试
- Esoteric 语言：Brainfuck 特征 `+-><[].,` 共 8 字符；Ook! 变体（. ? ! 组合）；Piet 用色块变化编码指令（npiet 解码），一般给的就是图本身
- RGB 像素串转图：文本是逗号分隔像素值时按 Image.new+putpixel 重建（先 len/3 再配 x*y），常出二维码
- pyc 恢复：头 4 字节是 magic+版本（py3.7 是 42 0D 0D 0A、py3.8 是 55 0D 0D 0A），按版本对照表补全；uncompyle6/decompyle3/pycdc 反编译

## OSINT 常规套路
- 图片：EXIF（exiftool 看 GPS）→ 反搜（Yandex 最强）→ 街景/地图对地标、招牌、山形定位
- 人物：昵称全平台搜索（namechk/whatsmyname）、邮箱 holehe/HIBP、用户名+数字组合变体
- 网站：web.archive.org 历史快照、WHOIS、crt.sh 证书透明度找子域
- 电话/车牌/学号 → 归属地与格式规则；经纬度坐标直接地图搜
- 题面关键词原样丢搜索引擎（中文题目先百度再 Google）
- EXIF 无 GPS 时：从拍摄时间/设备型号/建筑阴影反推地点时间
- 历史资料：wayback 看被删页面；GitHub 搜用户名/id 找提交记录
- 社媒搜索语法：site:、from:、since: 组合（Twitter/Telegram/Reddit）
- 照片定时间：太阳方位/阴影长度配 suncalc 推拍摄时刻

## 编程与脑洞
- 编程题：读清输入输出格式与边界 → Python 一把梭（大数/字符串/模拟）
- 交互题：pwntools remote 按轮次交互；限时限次题写自动循环
- 大数/精度：Python int 任意精度；浮点比较用 epsilon；负数取模注意语言差异
- 限时脚本先测边界：空输入/超长输入/重复元素，再提交
- 正则题：注意贪婪 vs 非贪婪；大文本流式处理防卡死
- 二维码：缺损先补定位角、反色、缩放后再扫；qrazybox 可深度修复
- PDF：qpdf --qdf 解压对象流、pdfimages 抽图、未显示文本层
- Office：docx/xlsx 本质是 zip → 解压看 document.xml、隐藏批注/修订记录
- 冷门：TTL 隐写（取低 2 位拼字节）、时间戳转换（毫秒记得除 1000）、文件时间戳篡改检测
- 区块链：eth 交易 input data 解码、合约 bytecode 反编译（dedaub）；IoT：binwalk 固件、MQTT/串口明文
- 系统痕迹：~/.bash_history、Windows Prefetch/NTUSER.DAT、浏览器历史 sqlite
- 网页题通用：开场套路归 Web 知识卡（robots/.git/.env/源码注释优先）
- 附件多小文件：先 cat 全部文本找公共模式，再逐个深挖
- 音视频：倒放/慢放/抽帧（ffmpeg -vf select=...）、频谱图
- 抽帧后 OCR（tesseract）或逐帧 diff 找差异帧
- .eml 邮件：看 header 原始字段 + 附件 base64 解码
- 自定义协议题：对照抓包逐字节分析字段含义

## 常见思路
1. 先读题面/描述关键词 → 判断编码/隐写/编程/OSINT 哪一类
2. 文本类：先 CyberChef Magic 一键猜；字符集频率判断 Base 变体
3. 文件类：file/010 看头尾 → binwalk → strings → 隐写工具逐个试
4. 有服务器交互：按返回内容逐轮调试脚本，别手撸数据
5. 键鼠/网络流量题：转到 Forensics 知识卡对应小节
6. 时间紧张先跑三板斧：strings / exiftool / base64 -d 覆盖大半 misc 题
7. 卡 2 轮无进展：看 hint / 检索历史 WP（knowledge_retriever）再回来

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`
