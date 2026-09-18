# Bazhuayu SmartProxy linux-x64 限制与替代方案

## 问题

`bazhuayu detect` 默认使用 SmartProxy 保护检测器，但 Linux x64 上缺少原生模块：

```
Protected Smart requires a native @octopus/octopus-protect binding for
linux-x64, but it is missing from this installation.
```

## 根因

`@octopus/octopus-protect` 包（v1.0.0）只包含三个平台的预编译 `.node` 文件：

| 文件 | 平台 |
|------|------|
| `octopus-protect.darwin-arm64.node` | macOS Apple Silicon |
| `octopus-protect.darwin-x64.node` | macOS Intel |
| `octopus-protect.win32-x64-msvc.node` | Windows x64 |

**没有 `octopus-protect.linux-x64.node`**。这不是安装损坏或 npm bug 4828 导致的 — 该包本身未提供 Linux 二进制文件。重装 npm 无法解决。

## 替代方案

### 方案 A：使用 legacy 检测器

```bash
# 自动模式（无登录要求时）
bazhuayu detect <URL> --legacy-detector --auto --output task.json

# 手动模式（需要登录；需在浏览器中点击数据组）
bazhuayu detect <URL> --legacy-detector --manual --save-session --session-name <name> --output task.json
```

**注意：** `--legacy-detector --manual` 模式下，浏览器打开后，**必须点击一个高亮的数据组**（搜索结果卡片），然后按 Enter。单纯 sleep+echo 管道发送 Enter 不够，因为旧检测器先等待点击选择。

### 方案 B：复制已有云端任务

不需要 `detect`，直接基于已有任务创建新任务：

```bash
# 1. 复制任务（自动保存到云端）
bazhuayu task copy <existingTaskId> --json

# 2. 重命名
bazhuayu task rename <newTaskId> --name "新名称" --yes

# 3. 验证
bazhuayu task list --keyword "新名称" --json
```

### 方案 C：本地任务文件运行

如果已有任务 `.json` 文件，跳过云端直接运行：

```bash
bazhuayu run <taskId> --task-file <任务文件.json> --max-rows N
```

## 验证环境

```bash
# 检查 SmartProxy 状态
bazhuayu doctor 2>&1 | grep protect

# 检查可用原生模块
ls /home/xujuan/Projects/bazhuayuCLI/lib/node_modules/bazhuayu-cli/node_modules/@octopus/octopus-protect/*.node
```