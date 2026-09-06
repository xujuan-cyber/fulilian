# CTF 常用脚本快照（scripts/）

本目录是知识库 `CTF常用脚本及工具/` 的**只读快照**，供 CTF agent 离线取用现成利用/解码脚本。

## 来源

- **来源绝对路径**: `/home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF常用脚本及工具/`
- **快照日期**: 2026-09-05
- **快照方式**: `cp -r` 整目录拷贝，保留全部子目录结构与原文件内容（未做任何修改）。

## 与上游不同步的声明

> **本快照不会随上游知识库自动同步。** 上游（`Des-CTF-Knowledge` 仓库）后续新增或修改的脚本
> **不会**反映到本目录。如需更新，须人工重新执行拷贝并更新本 README 的快照日期与统计。
> 使用时请以本目录内容为准，不要假设它与上游一致。

## 统计

| 项目 | 数量 |
|------|------|
| 文件总数 | 150 |
| Python 脚本 (.py) | 110 |
| 子目录数（含根） | 90 |
| 文本样本 (.txt) | 17 |
| JS 脚本 (.js) | 7（emoji/ 的 crypto-lib、lodash 等） |
| Markdown (.md) | 7（含 SCRIPTS-INDEX.md、python-note.md、快照 README.md、ROUTE.md） |
| 其他 | README、.dic 字典、.enc/.dat/.jpg 样本、PDF、.travis.yml 等 |

## 目录速览（按场景）

- **Web**: `双参数爆破脚本/`、`日志匹配/`（LFI 日志包含提取）
- **Crypto/RSA**: `RSA综合脚本利用/`（20+ 攻击场景子目录）、`DES_Python-master/`、`md5爆破/`、`维吉尼亚加密/`、`变异凯撒/`、`rot/`、`四方密码/`、`Nihilist密码/`、`toy密码/`、`26键盘密码-手机键盘密码/`、`常用反解密脚本/`
- **编码**: `Base/`（Base64 全家桶 8 个子工具）、`进制互相转换/`、`进制转化字符脚本/`、`hex倒叙/`、`hex减位/`、`十进制转字符/`、`二进制每8位倒序/`、`字符替换表/`、`字符频率统计分析/`、`文本转gbk编码/`、`谍报-替换普通话/`、`去重/`、`替换脚本/`
- **Misc/隐写/流量**: `图片爆破宽高/`、`频域盲水印/`、`CRC32校验爆破/`、`steghide爆破密码/`、`TTL隐写/`、`usb流量/`、`曼彻斯特编码/`、`字节转二维码/`、`RGB转图片/`、`批量解压压缩包+带密码/`、`遍历读取压缩包文件判断1和0/`、`流量数据提取脚本/`、`红绿灯-二进制/`、`emoji/`
- **Reverse**: `reverse/xor/`、`文件异或/`、`Python-Brainfuck-master/`
- **辅助**: `python-Picke序列化/`、`批量修改文件名后缀/`、`数学题/`、`一些比赛的脚本/`

## 脚本路由表

场景 → 脚本路径的快速索引见 [ROUTE.md](ROUTE.md)。

## 使用注意

- 各脚本多为赛时一次成型，**硬编码参数（URL、文件路径、密钥、密文）需按题目改写**后再用。
- 部分脚本依赖第三方库：`scapy`（流量提取）、`opencv-python`/`numpy`（盲水印）、`PIL/Pillow`（图像）、`pycryptodome`（RSA/DES）。
- 运行环境：`~/.fulilian/fulilian-agent/venv/bin/python`。
