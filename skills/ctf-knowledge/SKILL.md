# CTF 知识卡（6 分类）

> FuLiLian 内置 CTF 解题知识卡。solver 启动时根据题目分类自动注入对应知识卡
> （`fulilian_ctf.knowledge.inject_knowledge_card`），作为系统提示的一部分。
>
> 分类：web / crypto / reverse / pwn / forensics / misc

## 知识卡文件

| 分类 | 文件 | 适用场景 |
|------|------|---------|
| Web | [web.md](web.md) | 端口扫描、注入、XSS、SSTI、文件包含、上传、SSRF |
| Crypto | [crypto.md](crypto.md) | RSA、AES、哈希、古典密码、编码 |
| Reverse | [reverse.md](reverse.md) | ELF/PE/APK 逆向、脱壳、算法还原 |
| Pwn | [pwn.md](pwn.md) | 栈溢出、堆利用、格式化字符串、沙箱逃逸 |
| Forensics | [forensics.md](forensics.md) | 流量分析、磁盘镜像、隐写、内存取证 |
| Misc | [misc.md](misc.md) | 编码、社工、OSINT、编程、脑洞题 |

## 使用方式

1. **自动注入**：`fulilian solve <id>` 时，solver 根据挑战的 `category` 字段
   自动把对应知识卡追加到系统提示。
2. **手动检索**：`fulilian knowledge list` 列出全部知识卡；
   `fulilian knowledge query <词>` 检索 Des-CTF-Knowledge 历史 WP。

## 维护约定

- 知识卡内容保持精简（每条一行），只收录高频可复用考点。
- 详细 WP / Payload 速查请检索 Des-CTF-Knowledge 知识库（`fulilian knowledge query`）。
