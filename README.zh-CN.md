<p align="center">
  <img src="assets/banner.png" alt="FuLiLian" width="100%">
</p>

# FuLiLian ☤

<p align="center">
  <a href="https://github.com/xujuan-cyber/fulilian"><img src="https://img.shields.io/badge/CTF%20%26%20取证-Agent%20CLI-339AF0?style=for-the-badge" alt="CTF & Forensics Agent CLI"></a>
  <a href="https://github.com/xujuan-cyber/fulilian/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-English-lightgrey?style=for-the-badge" alt="English"></a>
</p>

**FuLiLian — 一个专注 CTF（夺旗赛）与数字取证的智能体 CLI。** 面向安全竞赛、取证分析与渗透测试工作流做了深度定制。

内置调度引擎、校验门与知识系统，FuLiLian 能自动完成重复性的 CTF 任务、持续追踪已发现的工件，让你专注于解题本身。

<table>
<tr><td><b>CTF 题目自动化</b></td><td>自动提取 Flag、搭建题目环境、管理工具链，并生成附带证据的结构化 Writeup。</td></tr>
<tr><td><b>取证分析</b></td><td>磁盘镜像分析、内存取证、日志分析、文件雕刻与时间线重建 —— 全部通过自然语言指令完成。</td></tr>
<tr><td><b>调度引擎</b></td><td>内置 cron 调度器，支持周期性侦察、自动化扫描与无人值守监控。</td></tr>
<tr><td><b>校验门</b></td><td>对潜在破坏性操作执行多步审批工作流，也可安全用于生产环境。</td></tr>
<tr><td><b>知识系统</b></td><td>跨会话持久记忆，自动记录发现的 Flag、已利用的漏洞与取证工件，随时回查。</td></tr>
<tr><td><b>多平台</b></td><td>Telegram、Discord、Slack、WhatsApp 与 CLI —— 单个网关进程全部搞定，手机上也能跟进解题进度。</td></tr>
<tr><td><b>随处运行</b></td><td>本地、Docker、SSH 或云 VPS，智能体环境跨会话持久保存。</td></tr>
</table>

## 本 Fork 的增强

在核心智能体框架的基础上，FuLiLian 增加了一层面向 CTF 的能力：

- **多智能体解题** —— racer/relay 编排，六类题型专家（crypto / pwn / reverse / web / forensics / misc）并行攻坚，配套时间盒与止损控制。
- **校验门** —— Flag 形状校验与依据检查，答案被接受前先过一道关。
- **CTF 知识卡** —— 按题型整理的考点卡（`skills/ctf-knowledge/`），附策略手册（playbook）、可复用片段，以及从历史 Writeup 提炼知识卡的工具。
- **上下文压缩调优** —— 锚点索引保留、分段压缩与 prune 重臂锁定，长会话、重工具的 CTF 场景下依然稳定。
- **CLI 体验** —— `/workspace` 目录切换、`/attach` 文件附加、渐变横幅与浅色模式配色适配。

## 快速开始

### 从源码安装（Linux / macOS / WSL）

```bash
git clone https://github.com/xujuan-cyber/fulilian.git
cd fulilian

# 一键安装脚本：创建 venv、安装依赖、把内置 skills 同步到 ~/.fulilian/skills/、
# 并将 `fulilian` / `fll` 命令软链到 PATH
bash setup-fulilian.sh

# 交互式配置向导：选择提供商与模型、写入 API key、生成
# ~/.fulilian/config.yaml 与 ~/.fulilian/.env
fulilian setup

# 启动会话
fulilian chat
```

### 配置文件在哪里？

`git clone` 只会得到**代码本身**——运行时数据目录是首次运行时才创建的，clone 不会自动生成：

| 路径 | 由谁创建 | 内容 |
|------|---------|------|
| `~/.fulilian/` | 首次运行（自动 mkdir：`config.py::ensure_fulilian_home()`） | 数据目录根 |
| `~/.fulilian/config.yaml` | `fulilian setup` 向导（或 `fulilian model`） | 模型提供商、显示、功能设置 |
| `~/.fulilian/.env` | `fulilian setup` / 安装脚本 | 仅 API 密钥（权限 600） |
| `~/.fulilian/skills/` | `setup-fulilian.sh`（从仓库 `skills/` 同步） | 内置技能 |
| `~/.fulilian/{sessions,memories,logs,cron,...}/` | 首次运行（自动） | 运行时状态 |

设置 `FULILIAN_HOME` 环境变量可迁移数据目录；原生 Windows 下默认在 `%LOCALAPPDATA%\fulilian`。删除代码仓库（卸载）不会影响 `~/.fulilian/`。

### 其他安装方式

```bash
# 一行远程安装（安装到 ~/.fulilian/fulilian-agent）
curl -fsSL https://raw.githubusercontent.com/xujuan-cyber/fulilian/FuLilian/scripts/install.sh | bash

# 验证安装
fulilian status
fulilian doctor
```

### Windows 原生安装

习惯用 Windows CMD 终端？FuLiLian 在 Windows 上是**原生**安装的，不经过 WSL，并把 `fll`、`fulilian` 放进 PATH。在 CMD 里：

```bat
curl -fsSL https://raw.githubusercontent.com/xujuan-cyber/fulilian/FuLilian/scripts/install.cmd -o install.cmd && install.cmd && del install.cmd
```

在 PowerShell 里可以直接跑安装器：

```powershell
iex (irm https://raw.githubusercontent.com/xujuan-cyber/fulilian/FuLilian/scripts/install.ps1)
```

装完开一个新的 CMD 窗口，用 `fll --version` 验证。

## 文档

- [GitHub Wiki](https://github.com/xujuan-cyber/fulilian/wiki) — 安装指南、CTF 工作流与 API 参考
- [Issues](https://github.com/xujuan-cyber/fulilian/issues) — 缺陷反馈与功能建议

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
