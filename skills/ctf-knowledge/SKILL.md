---
name: ctf-knowledge
description: "CTF 解题知识卡与配套资产：web/crypto/reverse/pwn/forensics/misc 六分类知识卡、通用解题 playbook、按场景路由的现成脚本（scripts/ROUTE.md）与 web 模板（templates/）。分析 CTF 题目、选攻击思路、找 payload 模板或转换脚本时使用。"
category: "ctf"
version: 1.0.0
author: fulilian
---

# CTF 知识卡（6 分类）

> FuLiLian 内置 CTF 解题知识卡。solver 启动时根据题目分类自动注入对应知识卡
> （`fulilian_ctf.knowledge.inject_ctf_context`），作为系统提示的一部分。
>
> 分类：web / crypto / reverse / pwn / forensics / misc

## 知识卡文件

| 分类 | 文件 | 适用场景 |
|------|------|---------|
| Web | [web.md](web.md) | 端口扫描、注入、XSS、SSTI、文件包含、上传、SSRF |
| Crypto | [crypto.md](crypto.md) | RSA、AES、哈希、古典密码、格密码、编码 |
| Reverse | [reverse.md](reverse.md) | ELF/PE/APK 逆向、脱壳、魔改算法识别、算法还原 |
| Pwn | [pwn.md](pwn.md) | 栈溢出、堆利用（含 glibc 2.32+/2.34+）、格式化字符串、沙箱逃逸 |
| Forensics | [forensics.md](forensics.md) | 流量分析、磁盘镜像、隐写、内存取证 |
| Misc | [misc.md](misc.md) | 编码、社工、OSINT、编程、脑洞题 |

## 配套资产目录

| 资产 | 内容 | 说明 |
|------|------|------|
| [playbook.md](playbook.md) | 常驻流程卡 | 每题无条件注入：时间盒、信息收集动作、换题/检索纪律 |
| [templates/](templates/README.md) | 16 个 exp 模板 | pwn 8 + web 8，改顶部 TODO 参数即用 |
| [scripts/](scripts/README.md) | 110 个实战脚本快照 | 场景→脚本路由表见 [ROUTE.md](scripts/ROUTE.md) |
| [snippets/](snippets/README.md) | 225 个 WP 提取片段 | FTS5 索引，`search_snippets()` 检索 |

## 使用方式

1. **自动注入**：`fulilian solve <id>` 时，`inject_ctf_context` 统一注入
   playbook → 分类知识卡 → 历史失败教训（avoid_list）→ 相似历史 WP 参考（top-3）。
2. **手动检索**：`fulilian knowledge list` 列出全部知识卡；
   `fulilian knowledge query <词>` 检索统一知识库（Des-CTF-Knowledge + hermes-vault 本人实战复盘，2675+ 篇）；
   `fulilian knowledge cards-sync` 把高频成功技巧沉淀回知识卡。
3. **资产优先级**（specialist 提示词已内置）：模板 → snippets 片段参考 → scripts/ 现成工具 → 现场写。

## 维护约定

- 知识卡内容保持精简（每条一行），只收录高频可复用考点；新套路经 cards-sync 确认后回填。
- 详细 WP / Payload 速查请检索统一知识库 `~/.fulilian/ctf-knowledge/`
  （`fulilian knowledge query`）；用户本人验证过的复盘在 `hermes-vault/` 子目录，优先参考。
- snippets/ 由 `tools/extract_exp_snippets.py` 从知识库 WP 自动提取，可重跑刷新。
