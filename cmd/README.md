# FuLiLian CMD Edition

FuLiLian 的 **CMD 终端版**前端。让 Windows CMD（及 PowerShell）把 `fll` 当作原生命令使用——实际执行仍在 WSL 里的完整 FuLiLian 安装上，配置、会话、skill、日志与 WSL 内运行完全一致。

## 组成

| 文件 | 作用 |
|---|---|
| `fll.bat` | CMD 启动器：UTF-8 代码页自动切换/恢复、WSL 发行版与 fll 探测、参数原样透传、退出码透传 |
| `fll.ps1` | PowerShell 启动器：参数含引号/括号/中文时优先用这个 |
| `install.cmd` | 安装器：复制启动器到 `%USERPROFILE%\bin`、USER PATH 安全追加（幂等）、自检；支持 `/check`、`/uninstall` |

## 安装（CMD 中执行）

```bat
git clone https://github.com/xujuan-cyber/fulilian.git
cd fulilian\cmd
install.cmd
```

装完**开一个新的 CMD 窗口**，任意目录验证：

```bat
fll --version
```

## 使用

```bat
fll                        :: 交互会话
fll --tui                  :: TUI 模式
fll solve <...>            :: 其余子命令/参数原样透传
fll --version
```

PowerShell 侧：

```powershell
fll                        :: 装完后 PATH 里直接可用
.\fll.ps1 -z "解题提示词"   :: 或显式用 ps1（复杂引号场景更稳）
```

## 配置（可选环境变量）

| 变量 | 含义 | 默认 |
|---|---|---|
| `FLL_DISTRO` | 指定 WSL 发行版 | 自动探测（优先 Running 中的默认发行版） |
| `FLL_BIN` | 指定 WSL 内 fll 路径 | 依次探测 `~/.local/bin/fll`、`/usr/local/bin/fll` |
| `FLL_QUIET` | `1` = 隐藏 `[fll] distro: ...` 提示行 | 未设 |
| `FLL_DEBUG` | 任意值 = 打印退出码与解析结果 | 未设 |

示例：

```bat
setx FLL_DISTRO Ubuntu-24.04
setx FLL_BIN /home/me/.local/bin/fll
```

## 设计说明

- **为什么走 WSL**：FuLiLian 的完整能力（CTF 工具链、插件、配置 `~/.fulilian/`）都在 WSL 内；CMD 版是前端而非重实现，保证两端行为一致。
- **退出码透传**：`fll.bat` 以 `wsl --exec` 启动并回传退出码，脚本化调用可靠。
- **代码页处理**：启动时切到 UTF-8（65001）保证 WSL 输出的框线/中文不乱码，退出前恢复原代码页。
- **PATH 幂等**：`install.cmd` 只在 `%USERPROFILE%\bin` 缺失时追加到 USER PATH，重复安装无副作用；`setx` 超长 PATH（>1024 字符）会截断，安装器自检会提示。
- **UNC 提示**：若 CMD 当前目录在 `\\wsl.localhost\...` 下，CMD 自身会打一行 UNC 警告后回退到 Windows 目录，来自 CMD 而非本工具，无害。

## 前置条件

- Windows 10/11 + WSL2，至少一个发行版（如 kali-linux、Ubuntu）
- WSL 内已安装 FuLiLian（见仓库根 `README.md`）
