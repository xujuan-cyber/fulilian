# 阶段 5 验收记录 · 进程隔离

> 验收人：team-lead｜时点：2026-11-01 12:5x｜依据：`orchestration-phase5-decisions.md` §五
> 方式：主控独立重跑 + 两次独立变异 + 监督员三轮审计。

## 结论：通过（含 3 处真缺陷，其中 1 处是决议设计错误）

全量 **297 passed / 2 skipped / 1 xfailed**（阶段 4.5 结束时 285）。

| 文件 | 测试数 |
|---|---|
| `test_reaper.py` | 5 |
| `test_launcher.py` | 6 |
| `test_worker.py` | 11（+3 条 fenced 产物用例） |

| 决议 | 落地 |
|---|---|
| R1 setsid 在子进程入口第一句 | 通过（`if sys.platform != "win32":` 分支） |
| R2 killpg 异常分类 | 通过（9 处 except 逐个核过，`PermissionError` 不被吞） |
| R3 Windows Job Object | 代码就位，**未经本机测试**（见 §四） |
| R4 强制 spawn 守卫 | 通过（保留但注明当前恒真） |
| R5 灰度开关 | 通过（实测未设变量时为关） |
| R6 fencing 产物作废 | 通过（判据经一次重做，见 §二） |
| R7 无新依赖 | 通过（仅标准库） |

---

## 一、缺陷一：`setsid()` 缺平台判断（Windows 必然崩）

`launcher.py` 曾无条件调 `os.setsid()`，而它只在 POSIX 存在。Windows 上 DAEMON 档一进 `_process_main` 就 `AttributeError`。

**后果比"未测试"严重**：reaper 的 win32 分支在 launcher 流程里**永远不可达**。这不是"Windows 没验证过"，是"Windows 根本走不到"。

已加 `if sys.platform != "win32"`。Windows 靠 Job Object 回收进程树，本就不需要进程组——这是设计上正确的分叉。

**教训**：未测试的分支不只是没验证，它可能根本不可达。文档里写"未验证"会让人以为"验证了就没事"，但没人验证过的路径往往连结构都是错的。

## 二、缺陷二：R6 的竞态（决议设计错误）

R6 原文只要求"fencing 时把产物改名"。实现后发现：**同一任务的重试复用同一个 `card.output_path`**。

1. W1 持 epoch 1，写 `output_path`
2. 租约过期，W2 领 epoch 2，**在 W1 返回前就写了同一个路径**
3. W1 的 `complete()` 抛 `FencedOutError`，然后 W1 把 `output_path` 改名作废

**W1 把 W2 的有效产物抹掉了**——被系统承认的结果消失。

### 修法一（错）：文件身份比对

第一版让 worker 在 `_land` 入口取 `(st_dev, st_ino, st_mtime_ns)`，fencing 后比对。

**这个判据从原理上无效**：`_land` 能走到 `complete()` 抛 Fenced，**恰恰说明租约已经不在**。取样时拿到的可能已经是 W2 的文件，比对必然相同。

监督员用独立脚本复现：`canonical exists: False`、`leftovers: ['t.md.fenced-1']`——W2 的产物照样被作废。

### 更隐蔽的问题：测试模拟了错误的时序

第一版的测试 mock 了 `complete()` **在取样之后**才改写文件，所以它绿。而现实里改写发生在取样**之前**。

**测试通过，但模拟的交错不会发生。** 这是"假测试"最隐蔽的形态：它断言了正确的性质，构造的现场却不是真实那个。

### 修法二（对）：查数据库归属，不问文件

文件身份证明不了归属，但数据库知道谁持有：

| 条件 | 处置 |
|---|---|
| `state == 'SUCCEEDED'` | 绝不碰（已被承认） |
| `claimed_by` 非空且不是自己 | 不碰（可能是它写的） |
| 行不存在 | 孤儿文件，作废 |
| QUEUED / BLOCKED / FAILED / CANCELLED | 无人持有，作废 |

**刻意保留的代价**：`claimed_by` 非空时旧产物会留在 canonical 路径（新持有者还没成功时）。这是有意为之——**宁可留一个可能是旧的产物，也不能抹掉一个可能是被承认的结果**。已写进 docstring 并注明"不要当漏判去修"。

`_stat_identity` 整段删除。按监督员定的标准：**去掉它若没有任何测试变红，它就是死代码**。它的原理已被双重证伪，留着只会让人以为有保护。

### 变异验证（主控独立复现，非采信报告）

```
变异1 去掉 claimed_by 判断: exit=1
    FAILED test_fenced_artifact_not_voided_when_rewritten_by_new_holder
变异2 去掉 SUCCEEDED 判断: exit=1
    FAILED test_fenced_artifact_not_voided_when_task_succeeded
```

两条判断都是活的。

## 三、缺陷三：`grace` 分支零覆盖

`ProcessReaper(grace=...)` 只有测试传，生产路径用默认 `grace=0.0`，所以 SIGTERM→升级 SIGKILL 这条分支零覆盖。

**这恰恰是回收器唯一会真正杀人的路径。** 实现者没有只把它记进笔记，而是补了 `test_kill_tree_grace_escalates_to_sigkill`：子进程 `SIG_IGN` 掉 SIGTERM + `Event` 握手确认处理器已装好 + 断言 `elapsed >= 0.2`。

最后那条断言是防作弊的关键——若 grace 被忽略、直接 SIGKILL，耗时断言先红。

## 四、Windows 分支：明确未经测试

以下行为**没有任何本机验证**（全部测试跑在 WSL/kali）：

1. `AssignProcessToJobObject` 的权限要求
2. assign 时机导致"早期孙进程漏在 job 外"
3. `KILL_ON_JOB_CLOSE` 的句柄继承时机
4. Job Object 结构体布局与 `argtypes`
5. `grace` 在 Windows 上被忽略（`TerminateJobObject` 即时）
6. `TerminateJobObject` 后 `process.exitcode` 是否立即非 `None`

**`KILL_ON_JOB_CLOSE` 的保证有前提**：job 直到第一次 `kill_tree` 才创建并 assign，只有那之后才成立。父进程若在首次 kill 之前崩溃，子进程照样存活。docstring 已按此改正——原文称"唯一可靠的方式"是过度承诺。

## 五、方法论收获

### 1. 变异力度必须匹配缺陷成因

阶段 4 修 `finding_id` 撞车时，第一次只把其中一处退回，测试没红——因为另外两处仍带形态。**必须三处全退回才复现**。

只改一处就宣布"测试能抓"，等于没验。

### 2. 描述防线要写清它挡什么、不挡什么

第一版 docstring 写 "strict improvement"，容易被读成"已经改进了"。实际只覆盖半个窗口。

"improvement"、"hardening"、"defense in depth" 这类词听起来都像"有保护"，但都不说明保护了什么。**写防线必须写边界**，否则下一个人按最乐观的理解使用它。

### 3. 改事实性陈述先 grep 关键词，再动手

"setsid 无条件做"这句话散在四处（launcher docstring、launcher 注释、reaper docstring、笔记）。实现者按"被指出的位置"逐个改，改三处漏第四处。

正确动作：先 `grep` 关键词拿到全部命中点，逐个判断，改完再 `grep` 确认。**两次 grep 之间才是修改。**

### 4. 笔记的行号是易失引用，锚点是稳定引用

笔记里的行号表出现"改一次文案就漂一次"三次后，改为 `grep` 锚点。这轮 `reaper.py` 因 docstring 加一行导致全文行号 +1，**锚点表零改动仍全部有效**——决定当场被验证。

锚点必须唯一：`if _WINDOWS:` 有 3 处命中，`^if _WINDOWS:` 才唯一，已在表中注明不可用 `grep -F`。

## 六、遗留

| 项 | 说明 |
|---|---|
| 灰度开关不进 `config.yaml` | 该文件有 `_config_version: 39` + schema，加段属另一变更集 |
| `setsid` 前的时间窗 | `Process.start()` 返回到子进程执行 setsid 之间，父进程崩溃则子进程留在父进程组。无法消除，已记录 |
| R6 的 query→replace 窗口 | 判据从"文件字节"变成"归属状态"，覆盖了真实场景，但仍有极短窗口 |
| 生产调用方 | `agent/orchestration/` 引用数仍为 0 |

## 七、阶段 5 完成度

计划验收四项：强制杀进程树无孤儿（通过）、fenced worker 产物作废（通过，判据重做一次）、Windows 孙进程可回收（**代码就位，未经测试**）、灰度开关（通过）。

**Windows 那条不能算通过**，只能算"已实现未验证"。如实记录。
