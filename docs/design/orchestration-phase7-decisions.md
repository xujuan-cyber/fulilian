# 阶段 7 冻结决议 · 清理（**计划的三项删除被撤销**）

> 主控裁定，实现者不得自行改动。
> 上游：`orchestration-implementation-plan.md` §阶段 7。计划原文要求"删除 `_active_subagents` / `_recent_subagents` / `_REGISTRY`；去掉 `agent/` 对 `tools.delegate_tool` 私有符号的 import"。

---

## 零、结论先行：三项删除全部撤销

计划假定这三个符号是死代码。**实测三个都是活的**，删除会造成功能静默降级。

| 计划项 | 实际归属 | 引用 | 裁定 |
|---|---|---|---|
| `_active_subagents` | `tools/delegate_tool.py` | 4 处（写入/读取/清理） | **不删** |
| `_recent_subagents` | `tools/delegate_tool.py` | 5 处（写入/读取/FIFO 裁剪） | **不删** |
| `_REGISTRY` | `agent/subagent_lifecycle.py` | **19 处** | **不删** |

`tools/delegate_tool.py` 里**根本没有** `_REGISTRY`（`grep -c` = 0）。计划把这个名字和 `subagent_lifecycle` 的核心注册表混在一起了。

---

## 一、为什么不能删：三份证据

### 1.1 `_active_subagents` + `_recent_subagents` 支撑一个活功能

两者共同支撑 `get_subagent_attribution()`：

```python
# tools/delegate_tool.py
def get_subagent_attribution(task_id) -> Optional[Dict]:
    with _active_subagents_lock:
        record = _active_subagents.get(task_id)   # 运行中
    ...
    retained = _recent_subagents.get(task_id)     # 已结束但近期
```

调用方是**真实存在的**：

```
tools/process_registry.py:3136   from tools.delegate_tool import get_subagent_attribution
tools/process_registry.py:3138   info = get_subagent_attribution(task_id)
```

用途：子代理起的后台进程（如 `npm ci` 带 `notify_on_complete=true`）**经常活过子代理本身**。它完成时，通知要回到父会话，并且必须知道"这是哪个委派起的"。删掉注册表，这条归属就丢了。

代码里对此有明确注释：

> Child-started background processes routinely outlive the child itself ... their completion notifications reach the parent conversation via the shared completion_queue and need delegation attribution even though the live registry entry is gone.

### 1.2 `_REGISTRY` 是 `subagent_lifecycle` 的核心存储

19 处引用，持有 `_Record`（handle / state / future / result），是终态保留与重连的唯一来源。删掉它，`subagent_lifecycle` 整个模块失效。

### 1.3 覆盖情况（**主控此处曾判断错误，已更正**）

主控最初写的是"零测试覆盖，删了测试照样全绿"。**这个判断是错的**，由 `cleanup-core` 指出并复核确认：

```
tests/tools/test_delegate_control_actions.py
  412  test_attribution_resolves_live_child          -> 覆盖 _active_subagents
  431  test_attribution_survives_child_completion    -> 覆盖 _recent_subagents
  449  test_attribution_unknown_task_id_is_none      -> 兜底路径
```

**错因**：主控当时的命令是

```
grep -rn "get_subagent_attribution\|_recent_subagents\|_active_subagents" tests/ | head -6
```

`head -6` 把输出截断在 gateway 的几行上，而 `tests/tools/` 的命中排在后面。**把截断后的结果当成了完整结果。**

教训：**用 `head` 截断输出之后，就不能再说"没有其它命中"。** 要么不截断（用 `wc -l` 先看总数），要么明确写"前 N 条"。这是主控本轮最该记的一次方法错误——它恰好发生在"论证别人代码危险"的时候。

### 1.3b 撤销结论是否仍然成立

**成立，但依据要换。** 不再依赖"删了也不红"，而是：

1. `get_subagent_attribution` 被 `tools/process_registry.py:3136` 真实调用，删符号等于删功能；
2. `_REGISTRY` 在 `subagent_lifecycle.py` 有 19 处引用，是核心存储；
3. 既有测试会红——这反而说明**删除是可被发现的**，风险低于主控原先的估计。

换句话说：主控原来认为"删了会静默降级"，实际是"删了会立刻红"。这降低了风险等级，但不改变"不该删"的结论——测试能抓住，不等于应该删。

---

## 二、本阶段真正要做的事（三项）

### P7-1 · 撤销删除项并写进计划文档

在 `orchestration-implementation-plan.md` 的阶段 7 表格后追加一段"**已撤销**"，说明三项为什么不能删、证据在哪。

理由：不写的话，下一个人会照着计划再删一次。**错误的计划比没有计划更危险**，因为它带着"这是经过评审的"的权威。

### P7-2 · 清理私有 import（计划唯一成立的一项）

```
agent/subagent_lifecycle.py:427   from tools.delegate_tool import _run_child_lifecycle
```

`_run_child_lifecycle` 定义在 `tools/delegate_tool.py:3528`。跨模块导入下划线开头的符号，等于把 `delegate_tool` 的内部实现变成 `agent/` 的公开依赖——`delegate_tool` 一改签名，`agent/` 就坏，而且没有编译期信号。

**做法**：在 `delegate_tool.py` 里加**公开包装函数**（不是模块级别名），docstring 写明"这是跨模块契约，签名变更需同步 `agent/subagent_lifecycle.py`"。**不要重命名原函数**——那样会波及 `delegate_tool` 内部所有调用点，收益为零、风险为正。

本阶段实际公开了**两个**符号，都是包装函数：

| 私有原函数 | 公开包装 | 调用方 |
|---|---|---|
| `_run_child_lifecycle` | `run_child_lifecycle` | `agent/subagent_lifecycle.py`（`_SubagentRuntime._run`） |
| `_build_child_preserving_parent_tools` | `build_child_preserving_parent_tools` | `agent/subagent_lifecycle.py`（`SubagentLifecycleService.spawn`） |

**为什么必须是包装函数，不能是 `public = _private` 别名**：别名在 import 时就把函数对象绑死了，之后 `monkeypatch.setattr("tools.delegate_tool._private", ...)` 打不中它。现有测试恰好依赖这两个打桩点（`tests/run_agent/test_sequential_tool_timeout.py`、`tests/tools/test_delegate_output_schema.py`），用别名会让打桩静默失效——测试照样跑，只是测了个假东西。包装函数体内按调用解析模块全局名，打桩点继续生效。

> 这条是踩出来的：第一次实现用了别名，`test_sequential_tool_timeout.py::test_sequential_tool_interrupt_hides_lifecycle_cancel_detail` 立刻变红，真实子代理生命周期被跑起来（`TypeError: sequence item 0: expected str instance, MagicMock found`）。改回包装函数后恢复。

**验收（已替换）**：`tests/tools/test_private_import_guard.py::test_agent_does_not_import_private_symbols_from_delegate_tool` 通过。

~~验收：`grep -rn "from tools.delegate_tool import _" agent/` 无输出。~~

**grep 版本已作废，因为它可被多行 import 绕过。** 实测 `agent/subagent_lifecycle.py` 里就有这样一段，grep 抓不到：

```python
from tools.delegate_tool import (
    _build_child_preserving_parent_tools,   # ← 下划线在下一行，grep 匹配不到
    DEFAULT_MAX_ITERATIONS,
)
```

而且这段 import 上面两行的注释还写着 "Delegate construction remains internal so plugin code never imports private delegation helpers"——**注释说"不导入私有 helper"，紧接着三行就在导入私有 helper**。注释与代码相反，比没有注释更糟。

所以验收改用 AST：遍历 `agent/` 下所有 `.py`，检查 `ast.ImportFrom` 节点里 `module == "tools.delegate_tool"` 且 `alias.name.startswith("_")`。多行 import、括号别名列表、`import ... as` 全部覆盖。`grep` 只查字形，`ast` 才查结构。

### P7-3 · 补归属测试（消除"删了也不红"）

这是本阶段最有价值的一项。零覆盖意味着这三个符号随时可能被下一次"清理"删掉。

要补的测试（`tests/tools/test_subagent_attribution.py` 新建）：

```
test_attribution_finds_running_subagent
test_attribution_finds_recently_finished_subagent
test_attribution_returns_none_for_unknown_task_id
test_attribution_returns_none_for_non_subagent_id
```

前两条必须**通过真实的注册/注销函数**建立状态，而不是直接往字典里塞——直接塞只能证明字典可读，证明不了生命周期函数会写。

---

## 三、验收

| # | 指标 | 判定 |
|---|---|---|
| ① | 私有 import 清零 | `tests/tools/test_private_import_guard.py` 通过（**AST 检查，非 grep**；grep 可被多行 import 绕过，见 §二 P7-2） |
| ② | 归属功能有测试 | 4 条测试全绿 |
| ③ | 测试能失败 | 删掉 `_recent_subagents` 的读取 → `test_attribution_finds_recently_finished_subagent` 必须红 |
| ④ | 全量绿 | `pytest tests/ -q`（本阶段首次允许跑全量，因为改了 `agent/` 生产代码） |
| ⑤ | 计划文档已标注撤销 | 阶段 7 表格后有"已撤销"说明 |

---

## 四、禁止事项

1. **不得删除 `_active_subagents` / `_recent_subagents` / `_REGISTRY`。**
2. 不得重命名 `_run_child_lifecycle`（只加公开别名）。
3. 不得改 `tools/process_registry.py` 的调用逻辑（只可能改 import 形式）。
4. 不得为了让测试通过而放宽断言。
5. 不得跑单个测试文件就宣布完成——本阶段改了生产代码，必须跑全量。

## 五、环境

```
wsl.exe -d kali-linux -- bash -lc 'cd /home/xujuan/.fulilian/fulilian-agent && <cmd>'
```
Python `./venv/bin/python`。⚠️ `Edit`/`Write` 对 UNC 路径报 `ModifyBackup failed`，改文件用「写脚本到 `C:\Users\Administrator\AppData\Local\Temp\` → WSL 内执行 + `os.replace`」。

**落盘后必须读回关键行确认文件真的变了。**
**笔记里的定位用锚点字符串，不要写行号。**
