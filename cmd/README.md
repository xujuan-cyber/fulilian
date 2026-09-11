# FuLiLian 的 Windows CMD 前端

让 Windows CMD（及 PowerShell）把 `fll` 当作原生命令使用。**实际执行仍在 WSL 里的完整 FuLiLian 上**——配置、会话、skill、日志与在 WSL 内直接运行完全一致。这里是前端，不是另一份实现。

## 先选路：你要装哪个？

本仓库有**两个 `install.cmd`，用途完全不同**，选错会白折腾：

| 你想要的效果 | 用哪个 | 装的是什么 |
|---|---|---|
| **在 CMD 里敲 `fll`，实际跑 WSL 里那份 fulilian** | `cmd\install.cmd`（本目录） | 四个启动器 → `%USERPROFILE%\bin`，不装 fulilian 本体；前提是 WSL 里已经装好 fulilian |
| **在 Windows 上原生跑 fulilian，不经过 WSL** | [`scripts\install.cmd`](../scripts/install.cmd) | 原生 Windows 版 fulilian 本体（uv / Python / Node / PortableGit） |

两者可以共存：`cmd\install.cmd` 装的 `fll` 只负责把你送进 WSL，不碰原生安装。**本目录这套的唯一目的就是委派 WSL**，它不会、也不该替你决定走原生还是 WSL。

## 组成

| 文件 | 作用 |
|---|---|
| `fll.bat` | CMD 入口：切 UTF-8 代码页（退出前恢复）、委派给 `fll.ps1`；无 PowerShell 时走降级分支 |
| `fll.cmd` | `fll.bat` 的别名，给 PATHEXT 不含 `.BAT` 的宿主 |
| `fll.ps1` | **真正的逻辑**：探测 WSL 与 `fll` 路径、Windows 路径改写为 `/mnt/...`、参数转发 |
| `fll.completion.ps1` | PowerShell Tab 补全；`-Install` / `-Uninstall` 写读 `$PROFILE` |
| `install.cmd` | 安装器：装入 `%USERPROFILE%\bin`、USER PATH 幂等追加、自检；支持 `/check`、`/uninstall`、`/no-profile` |

## 为什么真正的逻辑在 `fll.ps1` 而不是 `fll.bat`

cmd.exe **无法忠实转发参数**。`%*` 是文本替换且不会被重新分词，所以 `wsl.exe --exec <bin> %*` 会把任何含空格的带引号参数拆开（`"C:\Program Files\x"` 会变成三个参数、引号还留着），中文参数也会糊掉。Windows PowerShell 的解析器会正确重新分词，因此探测、路径改写、参数转发全部放在 `fll.ps1`，`fll.bat` 只负责把参数文本交给它。

`fll.bat` 里的 `:no_powershell` 分支是无 PowerShell 的宿主上的降级路径：交互式使用和简单参数没问题，含空格/引号/中文的参数可能被拆或乱码——这正是 `fll.ps1` 存在的理由。

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

`install.cmd /check` 只自检不改动；`/no-profile` 跳过 `$PROFILE` 写入；`/uninstall` 反向清理（含补全与 PATH）。

## 使用

```bat
fll                        :: 交互会话
fll --version
fll solve C:\ctf\chall     :: Windows 路径会自动改写成 /mnt/c/ctf/chall
fll <任意 fll 参数...>       :: 其余子命令/参数原样透传
```

### 裸跑 `fll` 起来的是 TUI 还是经典 REPL

界面由 fulilian 自己按终端能力判定，不由本前端指定（见 `fulilian_cli/main.py` 的 `_resolve_use_tui`）：

- **Ink TUI**：要求 stdin 与 stdout **同时**是终端；满足就进 TUI。
- **经典 REPL**：任一不是终端时自动回退，不会卡住。
- 强制指定：`fll --cli` 永远走经典 REPL；`fll --tui` 强制 TUI，终端能力不足时给一句明确提示后退出。

管道不算终端，所以 `fll > log`、`fll | more` 这类用法会走经典 REPL。这是刻意设计——TUI 在非终端下只会打印 `no TTY` 就退出，脚本化调用会拿到空结果。

想确认自己这台机器上实际是哪种：在 CMD 里裸跑 `fll`，出现全屏边框（TUI）还是行式的 `╭─…╮` 横幅（经典 REPL）。

PowerShell 侧：

```powershell
fll                        :: 装完后 PATH 里直接可用
.\fll.ps1 -z "解题提示词"   :: 或显式用 ps1（复杂引号场景更稳）
```

**Tab 补全**（PowerShell）：`install.cmd` 会调 `fll.completion.ps1 -Install` 写进 `$PROFILE`。补全词表是**静态的**——真实解析器在 WSL 里，每次按 Tab 去问要付一次 WSL 往返加解释器启动（约 1 秒）。CLI 新增子命令时需要同步更新 `fll.completion.ps1` 里的列表，那是该文件唯一会过期的部分。原始 cmd.exe 没有补全钩子，那边要用 clink，不在本目录范围内。

## 配置（可选环境变量）

| 变量 | 含义 | 默认 |
|---|---|---|
| `FLL_DISTRO` | 指定 WSL 发行版 | 自动（不传 `-d`，由 wsl.exe 用自己的默认发行版） |
| `FLL_BIN` | 指定 WSL 内 fll 路径 | 依次探测 `~/.local/bin/fll`、`/usr/local/bin/fll` |
| `FLL_QUIET` | `1` = 隐藏 `[fll] distro: ...` 提示行 | 未设 |
| `FLL_DEBUG` | 任意值 = 打印退出码与解析结果 | 未设 |
| `FLL_NO_PATH_TRANSLATE` | `1` = 不改写 Windows 路径为 `/mnt/...` | 未设 |

示例：

```bat
setx FLL_DISTRO Ubuntu-24.04
setx FLL_BIN /home/me/.local/bin/fll
```

## 设计说明

- **为什么走 WSL**：FuLiLian 的完整能力（CTF 工具链、插件、`~/.fulilian/` 配置）都在 WSL 内；CMD 前端保证两端行为一致，而不是另造一套。
- **退出码透传**：以 `wsl.exe --exec` 启动并回传退出码，脚本化调用可靠。
- **代码页处理**：启动切到 UTF-8（65001）保证 WSL 输出的框线/中文不乱码，退出前恢复原代码页。
- **PATH 幂等**：`install.cmd` 只在 `%USERPROFILE%\bin` 缺失时追加，重复安装无副作用；`setx` 超过 1024 字符会截断，自检会提示。
- **UNC 提示**：若 CMD 当前目录在 `\\wsl.localhost\...` 下，CMD 自身会打一行 UNC 警告后回退到 Windows 目录，来自 CMD 而非本工具，无害。

## 前置条件

- Windows 10/11 + WSL2，至少一个发行版（如 kali-linux、Ubuntu）
- WSL 内已安装 FuLiLian（见仓库根 `README.md`）
