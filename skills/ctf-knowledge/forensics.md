# Forensics 知识卡

## 常用工具
- wireshark, tshark, tcpdump, foremost, binwalk, volatility3, autopsy
- strings, exiftool, steghide, zsteg, pngcheck, pngcrush, ffmpeg, audacity
- 010 Editor, HxD / wxHexEditor, DiskGenius, R-Studio, FTK Imager

## 常见考点
- **流量分析**: 提取 HTTP 对象、追踪 TCP 流、过滤协议（`http`, `dns`, `ftp`）
  wireshark: `File → Export Objects → HTTP`
- **图片隐写**: LSB（zsteg / StegSolve）、EXIF（exiftool）、
  图片宽高修改（pngcheck / pngcrush）、RGB 转图片、盲水印
- **音频隐写**: spectrogram（Audacity）、摩斯电码、DTMF、高低频
- **压缩包**: 伪加密、CRC32 爆破、明文攻击、APCHPR 爆破
- **内存取证**: volatility3 插件（pslist, netscan, cmdscan, filescan, dumpfiles）
- **磁盘取证**: mmls/fls/icat（Sleuth Kit）、TrueCrypt/VeraCrypt 挂载
- **文件结构**: 文件头魔数修复、文件分割合并、时钟/时间戳分析
- **PDF 隐写**: 对象隐藏、字体隐藏、未显示文本
- **NTFS 取证**: ADS（Alternate Data Stream）、$MFT 分析、回收站、事件日志

## 常见思路
1. 先 `strings` 找 flag/URL/Base64 → `exiftool` 看元数据
2. 流量包：`tshark -r capture.pcap -Y "http" -T fields -e http.request.uri`
3. 图片 LSB：`zsteg -a file.png` 或 StegSolve 逐通道看
4. 压缩包：`file archive.zip` 看真/伪加密
5. 内存：`vol -f mem.dump windows.pslist` 先看进程
6. 如果含多个文件层叠：`binwalk -Me file` 递归提取

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`