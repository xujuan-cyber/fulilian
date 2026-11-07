# 阶段 7 · 清理（cleanup-core）

决议 `docs/design/orchestration-phase7-decisions.md`：三项删除全部撤销，本阶段只清理私有 import + 补测试。

改动：`docs/design/orchestration-implementation-plan.md`、`docs/design/orchestration-phase7-decisions.md`、`tools/delegate_tool.py`、`agent/subagent_lifecycle.py`、`tests/tools/test_subagent_attribution.py`、`tests/tools/test_private_import_guard.py`。

## 1. 撤销说明（已落进计划文档）

锚点 `> ### 已撤销（2026-11-01）`，位于阶段 7 表格之后、`**总计 10–12 周。**` 之前。结构：三个符号的实际归属与引用数 → 三条不能删的证据 → 对"零测试覆盖"的更正 → 本阶段实际执行的三项。核心一段：

> 删除 `_recent_subagents` 后，子代理起的后台进程完成时通知仍在，只是从"由 subagent `sa-xxx`（目标：…，委派 id：…）启动"退化成"由 subagent `sa-xxx` 启动"。功能静默降级，测试照旧全绿。

本机复核计数：`_REGISTRY` 在 `agent/subagent_lifecycle.py` **19** 处、`tools/delegate_tool.py` **0** 处；`_recent_subagents` **5** 处；`_active_subagents` **25** 处；`get_subagent_attribution` 在 `tools/process_registry.py` **2** 处。

**对决议的一处更正**：决议称归属功能"零测试覆盖"，实测不成立——`tests/tools/test_delegate_control_actions.py` 已有 `test_attribution_resolves_live_child` / `test_attribution_survives_child_completion` / `test_attribution_unknown_task_id_is_none`。覆盖存在但埋在控制面文件里，从文件名看不出归属契约，故另建独立文件做锚点。撤销结论不变。

## 2. 公开包装函数（不是别名）

| 私有原函数锚点 | 公开包装锚点 | 调用方 |
|---|---|---|
| `def _run_child_lifecycle(` | `def run_child_lifecycle(` | `agent/subagent_lifecycle.py`：`from tools.delegate_tool import run_child_lifecycle` |
| `def _build_child_preserving_parent_tools(**kwargs):` | `def build_child_preserving_parent_tools(**kwargs):` | 同文件：`from tools.delegate_tool import (DEFAULT_MAX_ITERATIONS, build_child_preserving_parent_tools)` |

**为什么是包装函数而非 `public = _private`**：别名在 import 时绑定函数对象，之后 `monkeypatch.setattr("tools.delegate_tool._private", ...)` 打不中它——打桩静默失效，测试测了个假东西。两个现有测试正依赖这两个打桩点：`tests/run_agent/test_sequential_tool_timeout.py`、`tests/tools/test_delegate_output_schema.py`。

第一版用了别名，`test_sequential_tool_timeout.py::test_sequential_tool_interrupt_hides_lifecycle_cancel_detail` 立刻红：真实子代理生命周期被跑起来，报 `TypeError: sequence item 0: expected str instance, MagicMock found`。改为按调用解析模块全局名后恢复。

## 3. 测试构造方式

`tests/tools/test_subagent_attribution.py`——状态**只**由真实生命周期函数建立；autouse fixture 仅做快照-还原（teardown 卫生），不参与构造状态。

| 测试 | 用哪个真实函数 |
|---|---|
| `test_attribution_finds_running_subagent` | `_register_subagent(record)` → 查归属，断言完整三元组 |
| `test_attribution_finds_recently_finished_subagent` | `_register_subagent` → `_unregister_subagent`（唯一写 `_recent_subagents` 的路径）；先断言 `sid not in _active_subagents`，再断言归属仍在 |
| `test_attribution_returns_none_for_unknown_task_id` | 未注册的合法 subagent id |
| `test_attribution_returns_none_for_non_subagent_id` | 进程 id / `""` / `None` |

`tests/tools/test_private_import_guard.py`——grep 换 AST：遍历 `agent/**/*.py` 的 `ast.ImportFrom`，`module == "tools.delegate_tool"` 且 `alias.name.startswith("_")` 即违规；附 `assert agent_files` 防 glob 为空导致假绿。

**grep 版为什么作废**：多行 import 的下划线在下一行，grep 抓不到。`agent/subagent_lifecycle.py` 里原就有这么一段，而它上方两行的注释写着 "plugin code never imports private delegation helpers"——注释与代码相反。

## 4. 测试输出原文

```
$ ./venv/bin/python -m pytest tests/tools/test_subagent_attribution.py -q
....                                                                     [100%]
4 passed in 0.89s

$ ./venv/bin/python -m pytest tests/tools/test_private_import_guard.py -q
.                                                                        [100%]
1 passed in 2.06s
```

## 5. 能失败验证

**归属测试**：注释掉 `get_subagent_attribution` 里 `retained = _recent_subagents.get(task_id)`（改为 `retained = None`），只该红一条：

```
.F..                                                                     [100%]
>       assert info is not None
E       assert None is not None
tests/tools/test_subagent_attribution.py:97: AssertionError
FAILED tests/tools/test_subagent_attribution.py::test_attribution_finds_recently_finished_subagent
1 failed, 3 passed in 0.86s
--- restored --- RESTORE_IDENTICAL: True
```

**AST 守卫**：往 `agent/subagent_lifecycle.py` 注入一段**多行**私有 import（grep 抓不到的那种）：

```
E       AssertionError: agent/ imports private symbols from tools.delegate_tool:
E           agent/subagent_lifecycle.py:556 -> _run_child_lifecycle
FAILED tests/tools/test_private_import_guard.py::test_agent_does_not_import_private_symbols_from_delegate_tool
1 failed in 2.31s
--- restored --- RESTORE_IDENTICAL: True
```

## 6. 全量测试（`scripts/run_tests.sh`，项目规范 runner）

```
=== Summary: 3437 files, 39680 tests passed, 716 failed, 316 skipped (100% complete) in 1120.4s (32 workers) ===
=== 168 files with test failures (716 tests failed) ===
```

**不绿，但不是本阶段造成的。** 本机 WSL 的 716 个失败是既有环境性失败（`test_install_ps1_*` 的 Windows 安装器测试、browser/daytona/mcp 等依赖外部服务的套件）。做了两次基线对照：

1. 把两处生产改动逆向还原，跑全量里失败的 170 个文件 → `167 files, 4012 passed, 718 failed`；改动后同一批 → `720 failed`。失败总数持平，差异全在 3 个与本阶段无关的文件（`honcho_plugin`/`browser_snapshot`/`process_registry`），隔离复跑均通过或为抖动。
2. 逐个隔离复跑差异文件，再把改动还原后复跑：`browser_snapshot_threshold`（mtime 缓存）与 2 条 `mcp_serve`（事件回放基线）在**未改动代码上同样失败**；`honcho_plugin/test_pin_peer_name.py` 连跑三次两过一败，是抖动。

与本阶段直接相关的 26 个文件（`tests/orchestration/`、`test_delegate*`、`test_subagent*`、`test_interrupt_compat`、`test_private_import_guard`、`test_subagent_attribution`）单独跑：**457 passed, 0 failed, 2 skipped**。

未修既有失败——超出本阶段范围，且不得为了让全量变绿去改无关测试。
