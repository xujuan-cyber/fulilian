# Forensics 知识卡

> 2024-2026 考点补充：USB 流量键鼠分离、NTFS ADS、压缩包伪加密、零宽字符。

## 常用工具
- 流量：wireshark/tshark, tcpdump, NetworkMiner, PcapFex
- 文件：binwalk, foremost, 010 Editor, exiftool, file
- 隐写：zsteg, stegsolve, steghide, stegseek, outguess, wbstego
- 内存/磁盘：volatility3, Sleuth Kit (mmls/fls/icat), Autopsy, FTK Imager, R-Studio
- 命令手册 PDF（统一库内）：`~/.fulilian/ctf-knowledge/工具使用/内存取证秒杀所有命令.pdf`

## 流量分析
- HTTP：Export Objects 导出文件；追踪 TCP 流；`http.request.uri contains "flag"`
- USB 键盘：过滤 `usb.capdata`/`usbhid.data`；8 字节报告第 3 字节是键码 → 按键映射表还原字符串
- USB 鼠标：第 1 字节按键状态、第 2/3 字节相对位移 → 累加坐标 matplotlib 画图出 flag
- 蓝牙 HID：同样按键盘报告格式解析键码；Wi-Fi：aircrack-ng 跑握手包
- 明文协议：FTP/SMTP 凭据、ICMP/DNS 隐写（数据藏 payload 或 query 域名）、RTP 语音（rtpdump+频谱图）
- TLS 流量：找 sslkeys.log 或 RSA 私钥注入 wireshark 解密；拿不到就看 SNI/DNS 情报
- 隐藏信道：端口号序列、ICMP seq/id 字段携带数据、低 4 位 IP id 隐写
- multipart/POST 大对象：`tcp.stream eq N` 追流后手工 dump
- 命令行追流：`tshark -r x.pcap -q -z follow,tcp,ascii,N` 直接 dump 第 N 条 TCP 流，不用开 GUI
- USB 多设备：`usb.device_address` 先分流，确认接口类型（键盘 0x01/鼠标 0x02）再解析

## 图片隐写
- PNG：pngcheck -v 查结构异常（IDAT 顺序/缺失）、宽高 CRC 爆破还原、LSB（zsteg -a / StegSolve 通道分离）
- JPG：steghide extract -sf（先试空密码，再 stegseek 跑字典）、exiftool 元数据、尾部附加数据（binwalk）
- GIF：帧分离（ffmpeg/convert）、帧时间间隔隐写
- 盲水印：频域盲水印需原图；LSB 盲水印（BlindWaterMark）
- StegSolve：Data Extract 逐通道/逐位面扫一遍再决定上工具
- 修复：文件头尾补齐、GIF/PNG 块结构修复、损坏图片拼图
- PNG 多余 IDAT：pngcheck -v 报"应并入上一块的短 IDAT"即异常，剔除 length/type/CRC 后 `zlib.decompress()` 解出隐藏数据
- JPG 隐写算法预判：`stegdetect -q -t jopi x.jpg` 判 jsteg/outguess/jphide/invisible secrets 再选工具（stegdetect 判不了 F5），避免盲试
- JPG F5：F5 无现成检测器，直接上 F5-steganography：`java Extract x.jpg -p 密码`（无密码先 -p ''）；JPHS 用 `jpseek -P 密码 in.jpg out.bin`
- GIF 帧间隔：`identify -format "%s %T \n" x.gif` 两种间隔值当 0/1 拼二进制转 ASCII；`identify -format "%c" x.gif` 看注释区

## 音频隐写
- DTMF：`multimon-ng -t wav -a DTMF x.wav` 直接出按键序列
- 倒放：`sox in.wav out.wav reverse`；MP3Stego：`decode -X -P pass x.mp3`
- SSTV：QSSTV + pavucontrol 把播放路由为输入，或手机 Robot36 对扬声器播
- WAV 尾部：data chunk 声明长度之后还有剩余字节即藏数据，binwalk -e 或脚本比对 data size 与实际大小

## PCAP 字段级取证（实测 playbook）
- 证据闭环规则：FTP 认证须同一流内服务端 `230` 响应确认，仅见 PASS 不算成功；扫描判定需同源同目标短时多端口且 `SYN=1,ACK=0`；答案字段必须来自同一请求-响应对，不跨流拼接
- DNS query 名是 hex 时 `dns.qry.name` 原值 `xxd -r -p` 解码（末尾根域点不算失败）；自定义 HTTP 响应头无 tshark 字段，用上面的 follow 命令看完整响应头
- ICMP 隐蔽通道：`tshark -Y 'icmp.type==8' -V -x` 定位 `Data:` 后 hex，只解 Data 载荷、不混入 IP/ICMP 头；表单 `%xx` 是编码值，unquote 只剥一层
- WSL/Git-Bash 检材陷阱：Git-Bash 调 wsl.exe 时裸 `/home/...` 被 MSYS 转译成 Windows 路径，路径要写进 `wsl.exe -- bash -c '...'` 内层；外接盘不可见时管道复制并前后 sha256 保全
- Redis 流量：Redis 协议明文，在 `$` bulk string 里直接找 `SET`/`config set` 命令与写入内容
- 内存取证双版本：老赛题环境常是 volatility2（`--profile=Win7SP1x64` 命令风格），vol3 插件名 windows.* 前缀，别混用

## 压缩包
- 伪加密：ZIP 改通用标志位第 0 位（本地文件头+中央目录两处都要改）；RAR 4.x 改 HEAD_FLAGS 加密位(0x04)
- CRC32 爆破：内容短（<6 字节）时用已知 CRC 反推原文
- 明文攻击：ZIP 用 pkcrack/bkcrack（已知部分明文）；口令爆破 zip2john/rar2john + john/hashcat
- 修复：`zip -FF`；嵌套压缩逐层解；注释/隐藏文件/时间戳藏信息；`unzip -z x.zip` 看注释（可能是摩斯/反色图/tab+空格摩斯）
- 伪加密修复：目录区与数据区标志位不一致是真伪加密；`java -jar ZipCenOp.jar r x.zip` 一键修复；binwalk -e 可无视伪加密直接解
- 口令爆破：`fcrackzip -u -D -p rockyou.txt x.zip`；掩码攻击 ARCHPR 用 `???love` 定长占位，中文密码勾选 OEM 编码
- RAR5 结构不同：伪加密少见，优先考虑真爆破

## 内存/磁盘取证
- volatility3：pslist → filescan → dumpfiles 三板斧；cmdline/consoles 看历史命令；hashdump
- 可疑进程优先：notepad/mspaint/cmd 的 dumpfiles，或直接搜 "flag" 文件名
- 磁盘：mmls 看分区 → fls/icat 提取删除文件
- NTFS ADS：`dir /r` 列出流，`more < file.txt:stream` 提取；$MFT 解析、USN Journal、回收站
- 事件日志：python-evtx/chainsaw 快筛关键 ID（4625 爆破、4688 进程创建）
- vol3 进阶：windows.psxview 找隐藏进程、windows.malfind、windows.registry.printkey
- 磁盘镜像（E01/raw）：7z/mount 解包，先 `fsstat` 判文件系统
- 加密卷：TrueCrypt/VeraCrypt 先在内存中找 keyfile/密码（volatility 对应插件）

## 常见思路
1. file 识别全部附件 → strings + grep -i flag 先来一轮；内存 dump 也先 strings 一发
2. 文件头速记：PNG 89504E47、JPG FFD8FF、ZIP 504B0304、RAR 52617221、7Z 377ABCAF
3. 流量包先看协议分布：`tshark -r x.pcap -q -z io,phs`，再挑可疑协议深入
4. 多层文件：binwalk -Me 递归提取后逐层 file
5. 图片：先元数据/尾部 → 再 LSB/通道 → 再宽高修复 → 最后盲水印
6. 内存镜像：pslist 找可疑进程 → filescan 搜 flag 相关名 → dumpfiles 导出
7. 数据库文件（sqlite/mdf）：直接 strings 或 sqlite3 打开翻表
8. USB 流量：先判设备类型（键盘/鼠标/触摸/hidraw），再选对应解析脚本
9. 音频：Audacity 频谱图 + 摩斯/DTMF/倒放；WAV 的 LSB 用 stegolsb

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`
