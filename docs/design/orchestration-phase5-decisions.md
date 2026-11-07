# 阶段 5 冻结决议 · 进程隔离（`ProcessReaper` + 强制 spawn + 灰度开关）

> 主控裁定，实现者不得自行改动。
> 上游：`orchestration-implementation-plan.md` §阶段 5。风险"中高：平台差异 + fork/线程陷阱"。
> **前置说明**：计划明确要求"必须先文档化'不提供安全隔离'"——见 §一。

---

## 一、这不是安全沙箱（必须先说清楚）

本阶段的进程隔离解决的是**故障隔离与资源回收**，不是安全边界：

| 它解决 | 它**不**解决 |
|---|---|
| 子进程崩溃不拖垮父进程 | 恶意代码逃逸 |
| 杀掉进程树不留孤儿 | 文件系统权限隔离 |
| 租约被抢时旧 worker 的产物作废 | 网络访问控制 |

子进程与父进程**同用户、同文件系统、同网络命名空间**，能读到对方的一切。任何把它当沙箱用的设计都是错的。

这句话必须出现在 `reaper.py` 的模块 docstring 里，不能只写在设计文档里——写文档里没人看，写代码里下一个人改之前会看见。

---

## 二、模块边界

| 文件 | 职责 | 不做什么 |
|---|---|---|
| `reaper.py` | 建进程组、杀进程树、回收 | 不创建进程、不碰任务状态 |
| `launcher.py` | 创建进程时挂上 reaper（**主控改**） | 不决定何时杀 |
| `worker.py` | fencing 时作废产物（`artifact-core` 改） | 不管进程组 |

---

## 三、公开 API（冻结）

```python
# ---- reaper.py ----
class ReaperError(Exception): ...


class ProcessReaper:
    """按进程组回收子进程树。Linux 用 ``killpg``，Windows 用 Job Object。"""

    def __init__(self, *, grace: float = 0.0) -> None: ...

    def attach(self, process: "multiprocessing.process.BaseProcess") -> None:
        """把进程登记进来。必须在 ``start()`` **之前**调用（要拿到 pid 前的句柄）。"""

    def kill_tree(self, process: "multiprocessing.process.BaseProcess") -> bool:
        """杀掉该进程及其所有后代。返回是否确实发出过信号。"""

    def reap(self, process: "multiprocessing.process.BaseProcess",
             *, timeout: float = 5.0) -> bool:
        """``kill_tree`` + ``join(timeout)``。返回进程是否已死。"""

    def close(self) -> None:
        """释放 Windows Job Object 句柄。Linux 上是 no-op。"""
```

---

## 四、七条实现决议

### R1 · Linux：`setsid` 必须在子进程入口第一句

`multiprocessing.Process` **没有** `start_new_session` 参数（那是 `subprocess.Popen` 的）。所以：

```python
def _process_main(...):
    os.setsid()          # 第一句，先于任何其它逻辑
    ...
```

`setsid()` 让子进程成为新会话 + 新进程组的 leader，此后 `os.killpg(os.getpgid(pid), SIGKILL)` 能一次带走整棵树（包括它自己再 `Popen` 出来的孙进程）。

**不能事后补**：`setsid()` 在已有子进程之后再调，孙进程已经继承了父的进程组，杀不到。

窗口说明：从 `Process.start()` 返回到子进程执行 `setsid()` 之间有一个极短窗口，此间若父进程崩溃，子进程会留在父的进程组里。这个窗口无法消除（除非改用 `subprocess.Popen(start_new_session=True)` 并以模块方式启动），本阶段**接受**并记录。

### R2 · `killpg` 的错误必须分类，不能一律吞

| 情况 | 处理 |
|---|---|
| `ProcessLookupError` | 进程已死 → 返回 `False`（不是错误） |
| `PermissionError` | **必须抛出** —— 说明杀不动，是真实故障 |
| 其它 `OSError` | 包装成 `ReaperError` 抛出 |

`except OSError: pass` 会让"杀失败"看起来像"杀成功"，孤儿进程从此无人回收。

### R3 · Windows：Job Object，且**明确标注未经测试**

Windows 用 `CreateJobObject` + `SetInformationJobObject(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)` + `AssignProcessToJobObject`。`KILL_ON_JOB_CLOSE` 保证即使父进程崩溃，句柄关闭时内核也会带走整棵树——这是 Windows 上唯一可靠的方式（没有进程组概念）。

**本项目所有测试跑在 WSL/Linux，Windows 分支无法在本机验证。** 要求：

1. 代码用 `if sys.platform == "win32"` 分支，Linux 上**不导入** ctypes.wintypes；
2. 模块 docstring 明确写"Windows 分支未经本机测试，首次在 Windows 使用前必须手工验证"；
3. 交付笔记里单独列一节说明"未验证的具体点"。

把未测试的东西写成已测试，比不写更危险。

### R4 · 强制 `spawn`，且加守卫

`launcher.py` 已用 `get_context("spawn")`（W9）。本阶段加一个守卫：

```python
if context.get_start_method() == "fork":
    raise ReaperError("禁止 fork：会复制父进程的 sqlite 句柄与线程状态")
```

理由：fork 会把父进程已打开的 sqlite 连接复制进子进程，两个进程操作同一个文件句柄；且父进程若有线程持锁，fork 出的子进程可能永久死锁。这两个故障都极难定位。

### R5 · 灰度开关用环境变量，不进 `config.yaml`

`FULILIAN_ORCH_PROCESS_ISOLATION`，默认 `"0"`（关）。

**不进 `config.yaml` 的理由**：那份配置有 `_config_version: 39` 和配套 schema，加一个新段要同步改 schema + 迁移，属于另一个变更集。阶段 5 不碰它。

开关语义：

| 值 | 行为 |
|---|---|
| `0` / 未设 | 仍 `setsid`（R1 无条件需要），但**不登记 reaper**，`kill_tree` 不被调用 |
| `1` | 完整隔离：登记 reaper，`reap()` 可用 |

`setsid` 无条件做的理由：它无副作用且是 R1 的前提；关掉它只会让"杀整组"这个能力彻底不存在，而不是"更安全"。

### R6 · fencing 时产物必须作废（`artifact-core`）

`worker._land` 已经处理了 DB 层：`FencedOutError` 时放弃写回。但**磁盘上的产物文件还在 `output_path`**，任何按路径读取的人都会拿到一个"没被承认"的结果。

裁定：fencing 时把产物**改名**为 `{output_path}.fenced-{epoch}`。

- **不删**：文件可能是唯一证据，删了无法追查；
- **改名**：canonical 路径消失，任何人按约定路径都读不到，不需要额外检查标记文件；
- 改名失败（权限/文件不存在）→ 记日志继续，**绝不因此让 worker 崩溃**。

### R7 · 不得引入新依赖

只用标准库（`os`、`signal`、`sys`、`ctypes`、`multiprocessing`）。Windows Job Object 用 `ctypes` 直接调 Win32 API，不引 `pywin32`。

---

## 五、验收

| # | 指标 | 判定 |
|---|---|---|
| ① | 杀掉进程树无孤儿 | 子进程再 spawn 一个孙进程，`kill_tree` 后孙进程也不在 |
| ② | 进程已死时返回 False 不抛 | `kill_tree` 一个已结束的进程 |
| ③ | `PermissionError` 必须冒泡 | 注入 mock 验证不被吞 |
| ④ | 强制 spawn 守卫 | 伪造 fork context 时抛 `ReaperError` |
| ⑤ | 灰度开关默认关 | 未设环境变量时 `isolation_enabled() is False` |
| ⑥ | fenced 产物改名 | 模拟 fencing，断言 `output_path` 不存在、`.fenced-{epoch}` 存在 |
| ⑦ | 改名失败不让 worker 崩 | 产物路径不可写时，worker 仍正常返回 |

### 必须新增的测试（函数名固定）

```
test_kill_tree_reaps_grandchild
test_kill_tree_on_dead_process_returns_false
test_kill_tree_propagates_permission_error
test_spawn_guard_rejects_fork
test_isolation_flag_defaults_to_off
test_fenced_artifact_is_renamed
test_fenced_artifact_rename_failure_does_not_raise
```

---

## 六、禁止事项

1. 不得改 `store.py` / `schema.py` / `contracts.py` / `state_machine.py` / `control.py` / `dispatcher.py` / `supervisor.py` / `redispatch.py`。
2. 不得改 `config.yaml` 及其 schema。
3. 不得引入第三方依赖。
4. 不得把 Windows 分支写成"已测试"。
5. 不得吞 `PermissionError`。
6. 不得跑全量 `tests/`。

## 七、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```
Python `./venv/bin/python`。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

**落盘后必须读回关键行确认文件真的变了**——不要只看脚本打印 OK（阶段 4 踩过"脚本报 OK 但 `if not fail` 拦住没写盘"的坑）。
