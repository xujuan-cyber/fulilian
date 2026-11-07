# 阶段 5 · 进程层（`ProcessReaper`）实现笔记

改动面：`agent/orchestration/reaper.py`（新）、`agent/orchestration/launcher.py`、`tests/orchestration/test_reaper.py`（新）、`tests/orchestration/test_launcher.py`（+2 例）。
未碰 `worker.py` / `store.py` / `schema.py` / `contracts.py` / `state_machine.py` /
`control.py` / `dispatcher.py` / `supervisor.py` / `redispatch.py` / `config.yaml` / `tools/`。未引第三方依赖（R7）。

## 1 · 签名（`inspect.signature` 原文）

```
ProcessReaper.__init__ (self, *, grace: 'float' = 0.0) -> 'None'
ProcessReaper.attach (self, process: 'multiprocessing.process.BaseProcess') -> 'None'
ProcessReaper.kill_tree (self, process: 'multiprocessing.process.BaseProcess') -> 'bool'
ProcessReaper.reap (self, process: 'multiprocessing.process.BaseProcess', *, timeout: 'float' = 5.0) -> 'bool'
ProcessReaper.close (self) -> 'None'
isolation_enabled () -> 'bool'
LaunchHandle fields ['tier', 'worker_id', 'thread', 'process', 'reaper']
```

与决议 §三逐字一致。唯一新增：`LaunchHandle.reaper`（默认 `None`）——否则开关打开后回收器实例无人可达，Windows Job 句柄会泄漏。`isolation_enabled()` 是 R5 的开关读取，决议只规定了环境变量名、没规定函数名。

## 2 · `kill_tree` 完整实现

```python
    def kill_tree(self, process):
        entry = self._entry_for(process)          # 未 attach 或 id 复用 → ReaperError
        if _WINDOWS:
            return self._kill_tree_win32(entry)
        return self._kill_tree_posix(entry)

    def _kill_tree_posix(self, entry: _Entry) -> bool:
        process = entry.process
        pid = process.pid
        if pid is None:
            return False
        if process.exitcode is not None:
            # 已被回收：pid 可能已被内核复用，按 pid 反查进程组会打到无关进程组。
            # 返回 False 而不是抛错——进程确实已经死了（验收 ②）。
            return False
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return False
        except PermissionError:
            raise
        except OSError as exc:
            raise ReaperError(f"取进程组失败：pid={pid}: {exc}") from exc
        if pgid == os.getpgid(0):
            # 子进程没 setsid，和本进程同组：killpg 会先杀掉自己。
            raise ReaperError(
                f"拒绝杀掉自身进程组（pgid={pgid}）：子进程没有执行 os.setsid()"
            )
        if self.grace > 0 and self._signal_group(pgid, signal.SIGTERM):
            deadline = time.monotonic() + self.grace
            while time.monotonic() < deadline:
                if not self._group_exists(pgid):
                    return True
                time.sleep(_POLL_INTERVAL)
        return self._signal_group(pgid, signal.SIGKILL)

    def _signal_group(self, pgid: int, sig: int) -> bool:
        """向进程组发信号。R2：错误必须分类，不能一律吞。"""
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return False   # 组已经空了：不是错误，只是没发出信号
        except PermissionError:
            raise          # 杀不动 = 真实故障。吞掉它，孤儿从此无人回收
        except OSError as exc:
            raise ReaperError(f"killpg 失败：pgid={pgid} sig={sig}: {exc}") from exc
        return True
```

`_entry_for`（锚点 `def _entry_for(`）除查表外还做 `entry.process is not process`：登记表按 `id()` 做键，对象回收后 `id` 会复用，不校验就可能拿错进程（Windows 上等于拿错 Job）。
`pgid == os.getpgid(0)` 那道自保检查不是决议要求的，是补充：若子进程没 `setsid`（例如 R1 被误删），`killpg` 的目标就是**本进程自己的组**，会把回收器连同宿主一起杀掉；它把"静默自杀"变成一条可读的 `ReaperError`。

## 3 · Windows 分支未验证的具体点

reaper 里的 `if _WINDOWS:` 块与 `_kill_tree_win32` **一次都没有在本机执行过**（全部测试跑在 WSL/kali/Linux）。首次在 Windows 使用前必须逐条手工验证：

1. **`AssignProcessToJobObject` 的权限要求**：用 `OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE)`。子进程同用户 spawn，预期拿得到；但宿主若已被外层 Job（Windows Terminal / CI runner / 容器）收编，Win8 之前的非嵌套 Job 语义会直接 `ERROR_ACCESS_DENIED`。
2. **assign 的时机与窗口**：`attach()` 在 `start()` 之前（那时没有 pid），真正 assign 要等第一次 `kill_tree`。**在此之前**子进程自己 `Popen` 出来的孙进程不在 job 里，`TerminateJobObject` 带不走。这是已知缺口，不是"已验证可用"；正解（子进程入口把自己塞进 job）本阶段没做。
3. **`KILL_ON_JOB_CLOSE` 的生效时机**：假设"父崩溃 → 内核关最后一个 job 句柄 → 整棵树被杀"。句柄是否只有一个、spawn 子进程是否持有可继承副本（那会把"最后一个句柄"推迟到子进程也死掉），都没验证。本实现没给 `CreateJobObjectW` 传 `SECURITY_ATTRIBUTES`（默认不可继承），但 spawn 仍可能从别的路径继承——未验证。
4. **结构体布局**：`Affinity` 用 `c_size_t` 代 `ULONG_PTR`、`LARGE_INTEGER` 用 `wintypes.LARGE_INTEGER`，`sizeof` 在 32/64 位上是否与 API 期望一致，未验证。
5. **`_k32()` 的 argtypes/restype 声明**从未被真实调用过：`HANDLE` 是否仍被截断、`use_last_error` 与 `WinError(get_last_error())` 配对是否准确，未验证。
6. **`grace` 在 Windows 上被忽略**（`TerminateJobObject` 即时，没有"SIGTERM 后等待"的中间态）；`TerminateJobObject` 之后 `process.exitcode` 是否立即非 `None`，也未验证。

测试侧：四个进程树用例都挂 `@_posix_only`（锚点 `_posix_only = pytest.mark.skipif`，**在 `tests/orchestration/test_reaper.py`**），win32 上跳过，**没有**假装它们通过。数量从三个变四个，是因为监督员指出 `grace > 0` 的 SIGTERM→SIGKILL 升级分支零覆盖后补了 `test_kill_tree_grace_escalates_to_sigkill`——那恰恰是回收器唯一会真正杀人的路径。

另（监督员查出、已修）：`_process_main` 的 `setsid` 现在有平台判断（锚点 `if sys.platform != "win32":`）。此前无条件调用，而 `os.setsid` 在 Windows 上不存在——DAEMON 档一进子进程就 `AttributeError`，reaper 的 win32 分支因此**永远不可达**。Windows 的树回收靠 Job，本就不需要进程组，所以这个分叉是设计正确的。

## 4 · R1–R5 定位（锚点，不写行号）

行号是易失引用（本项目的行号表已漂过三次：阶段 2a / 3b / 4，加本次）。下表只给**能 `grep -n` 唯一命中**的锚点串，代码怎么挪都不失效。

| 决议 | 位置 | 锚点 |
|---|---|---|
| R1 | `_process_main` 首句 | `if sys.platform != "win32":` |
| R1 | 窗口记录 | `极短窗口：start() 返回` / `返回到子进程执行` |
| R1 | 自保检查 | `拒绝杀掉自身进程组` |
| R2 | `_signal_group` 三类错误 | `def _signal_group(self, pgid: int, sig: int)` / `killpg 失败` |
| R3 | docstring 未测试声明 | `Windows 分支未经本机测试` |
| R3 | win32 实现 | `def _kill_tree_win32` / 行首锚点 `^if _WINDOWS:`（裸串 `if _WINDOWS:` 有 3 处命中，必须带 `^`；用 `grep -n '^if _WINDOWS:'`，**不要用 `grep -F`**） |
| R4 | 守卫定义 / 调用点 | `def _ensure_spawn(` / `_ensure_spawn(context)` |
| R5 | 开关名 / 读取函数 | `ISOLATION_ENV = "FULILIAN_ORCH_PROCESS_ISOLATION"` / `def isolation_enabled()` |
| R5 | launcher 接入 | `reaper = ProcessReaper() if isolation_enabled() else None` / `reaper.attach(process)` |

## 5 · 测试输出（原文）

```
$ ./venv/bin/python -m pytest tests/orchestration/test_reaper.py tests/orchestration/test_launcher.py -q
..........                                                               [100%]
11 passed in 5.43s
```

11 例 = `test_reaper.py` 5 例 + `test_launcher.py` 6 例（原 4 + 新 2）。venv 没装 `ruff`（`No module named ruff`），故未跑 lint。

**`grace > 0` 分支的状态（监督员复核项）**：生产里没有调用方——launcher 用默认 `grace=0.0`（锚点 `reaper = ProcessReaper() if isolation_enabled() else None`），`ProcessReaper(grace=...)` 只有测试在传。所以 `grace > 0` 那条 if 分支与 `_group_exists`（锚点 `def _group_exists(`）曾经是零覆盖的必然不可达路径。现已补 `test_kill_tree_grace_escalates_to_sigkill`：子进程 `SIG_IGN` 掉 SIGTERM，`grace=0.3`，断言最终 `exitcode == -SIGKILL` 且耗时 ≥0.2s（若 grace 被忽略会立刻 SIGKILL、耗时断言先红）。它覆盖升级路径与 `_group_exists` 轮询，但**仍然没有生产调用方**——能力存在、已被测试钉住，不代表当前有人用。

## 6 · "能失败"验证

把 `_process_main` 里的 `if sys.platform != "win32":` 分支临时改成 `if False:`（不能只注释 `os.setsid()`，那会留一个空 `if` 体变成 IndentationError）后：

```
$ ./venv/bin/python -m pytest tests/orchestration/test_reaper.py::test_kill_tree_reaps_grandchild -q
>           assert os.getpgid(process.pid) != os.getpgid(0), (
                "子进程与测试进程同组：_process_main 的 os.setsid() 没执行"
            )
E           AssertionError: 子进程与测试进程同组：_process_main 的 os.setsid() 没执行
E           assert 24559 != 24559
1 failed in 0.68s
```

变红在同组那句而非"孙进程仍存活"那句——同组时 `killpg` 会杀掉 pytest 自己，必须先拦。补一条探针给另一半证据（setsid 缺席时只杀子进程 pid，孙进程确实活着）：

```
child pid=22156 pgid=22099 / self pid=22099 pgid=22099 / same group: True
grandchild pid=22157 alive_after_killing_child_only=True / PROBE OK
```

即"孙进程也不在"这条断言不是空转：setsid 缺位时它必然不成立。验证后已改回 `if sys.platform != "win32": os.setsid()`（读回 `_process_main` 确认）；Linux 上该分支确实执行——本用例通过即证明子进程拿到了自己的进程组。
