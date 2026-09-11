# CTF 解题 Agent 优化计划书

> **状态：仅为计划，尚未实施。** 本文档不含任何已落地的改动。
> **撰写日期：** 2026-09-11
> **目标：** 把 fulilian 打造成以 CTF 解题为重点的智能体 —— 强项在难题，简单题一次通过。
> **用途：** 自包含的上下文保险。阅读本文不需要原始对话；所有数字附复现命令，所有代码结论附文件:行号。

---

## 0. 一句话结论

**fulilian 的问题不是"CTF 功能不够"，而是三层错配：**

1. **真正跑题的是一个通用助理 agent 循环。** 全仓 1,961,148 行 Python（5,313 个 `.py`），CTF 相关只有 15,460 行（**0.8%**）。其余是 Telegram/Discord/Slack/Feishu/Matrix 平台适配、看板、cron、TTS、视频生成、宠物、Home Assistant。
2. **CTF 层几乎全是"壳"。** `fulilian_ctf` 里所有东西最终收敛到一次 `run_agent.main(query, mode="ctf")`。planner / reasoner / specialist **全是确定性 Python，一次额外 LLM 调用都没有**。
3. **它对外宣传的 CTF 核心能力，在用户实际使用的路径上从未被调用过一次。**

**根因：fulilian 把"对话本身"当作唯一记忆。** 压缩一次就失忆一次，于是靠**重跑命令**把事实找回来。重复调用（62–79%）、串行往返（1.12 次/轮）、巨量 cache-read —— 全是这一条的下游。

---

## 1. 实测基线（记分牌）

改动的唯一验收依据。改动前请重跑一遍确认基线未漂移。

| # | 指标 | 实测基线 | 采集方式 |
|---|---|---|---|
| M1 | **重复工具调用占比** | **79.9%**（8 个 CTF 会话汇总，3,353/4,196 冗余） | §8.1 / §8.6 |
| M2 | **平均工具调用数 / assistant 消息** | **1.04** | §8.1 / §8.6 |
| M3 | **被压缩消息占比** | **82.2%**（7,094/8,634） | §8.1 / §8.6 |
| M4 | **CTF 工具调用次数** | **0** | §8.2 / §8.6 |
| M5 | 到 flag 的工具调用数（简单题） | 7（logd）/ 26（ezRSA）/ **127（WEB2）** | §8.1 |
| M6 | 到 flag 的工具调用数（难题） | 397 | §8.1 |
| M7 | cache-read token / 难题会话 | **42.9M**（迷路的魔法少女）；8 会话合计 86.2M | §8.1 / §8.6 |
| M8 | 固定开销（中性 cwd） | 75.6 KB ≈ 22k tokens | §8.3 |
| M9 | 固定开销（仓库 cwd） | **175 KB** | §8.3 |
| M10 | 知识检索 2 字中文命中 | `"注入"`/`"上传"`/`"逆向"` → **0 行** | §8.4 |

> **基线存档（2026-09-11）：** `benchmarks/baselines/2026-09-11-ctf-chatpath.json`
> 采集器：`benchmarks/process_metrics.py`（只读 state.db，纯新增）。
> ⚠️ 该基线测的是 **`fulilian chat` 人工解题路径** —— 见 §3.D2，CTF 层从未执行过。
> 只作用于 `mode="ctf"` 的改动无法用它验证。

### 1.1 逐会话明细

| 会话 | terminal 调用 | 不同命令 | 重复 | 重复率 |
|---|---|---|---|---|
| 迷路的魔法少女（难） | 1521 | ~313 | 1208 | **79%** |
| Power Cookie | 702 | 191 | 511 | **73%** |
| BUUCTF WEB2（入门） | 348 | 133 | 215 | **62%** |

同一难题会话内：
- `robots.txt` 的输出出现在消息索引 **19、79、131** —— 同一发现被重新推导三次。
- 同一个 `exploit.sh` 被执行 **14 次**。
- `ctf-web-exploitation`（130 KB SKILL.md）被 `skill_view` 加载 **20 次**。

### 1.2 工具调用数分布（11,573 条 assistant 消息）

```
{1: 10395, 2: 1013, 3: 100, 4: 31, 5: 31, 6: 3}   → 平均 1.12
```

即 **90% 的模型回合只做了一件事**。每次往返重发 40–100k tokens。

---

## 2. 冒烟枪：压缩不是"摘要"，是"删除"

这是全部问题里最重要的单点，也是投入产出比最高的修复目标。

```python
# agent/context_compressor.py:763
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"

# agent/context_compressor.py:769
_PRUNE_MIN_CHARS = 200
```

旧工具输出被**整条替换成这一句话**。没有摘要、没有头尾、没有指针、没有路径。超过 200 字符一律照删。

**这解释了重复调用循环的确切机制**：模型不是"忘了"，是**它的发现被 runtime 从上下文里物理删除了**，且没有任何找回途径，只能重跑。

同时它解释了 M3 的构成：75% 消息被标记 `compacted`，但只有 116 条带摘要标记。**绝大多数是 Phase-1 的 tool-result prune（替换为占位符），而非 Phase-2 的摘要。** 也就是说大部分"压缩"根本没产生摘要，只是留了个洞。

---

## 3. 证据明细

### A. CTF 工具调用次数 = 0

遍历 `state.db` 全部 112 个会话 / 26,127 条消息 / 13,018 次工具调用：

```
verify_flag, submit_flag, record_fact, http_session,
git_auto_commit, compile_check, checkpoint, generate_writeup  →  全部 0 次
```

交互式 `fulilian chat` 的 21 个工具 schema 里根本没有它们。
机制原因：`tools/ctf_solve.py` 用 `registry.register()` 在**导入时**注册，但启动路径上没有任何模块导入它。**黑板、验证门、声明式提交 —— 整套卖点都不在链路上。**

### B. 上下文失忆 → 重复劳动

见 §1.1、§2。

```
64 处 [SKILL_PRUNED: content lost in compression; reload with skill_view(...)]
```

框架主动把已加载的 skill 正文裁掉、再指示模型重新加载 —— 一个可测算的 load→prune→reload 循环。

### C. 串行工具调用

见 §1.2。`agent/prompt_builder.py:430-520` 里的 `PARALLEL_TOOL_CALL_GUIDANCE` 存在，但实测 1.12 次/轮 —— **该引导没有生效**。

### D. 固定开销

| 场景 | system prompt | 工具 schema | 合计 |
|---|---|---|---|
| 中性目录 | 29.7 KB | 45.9 KB | **75.6 KB（~22k tokens）** |
| `~/.fulilian/fulilian-agent` 下启动 | 129.7 KB | 45.9 KB | **175 KB** |

- 多出的 96 KB 是 fulilian 自己的开发指南 `AGENTS.md`（96,318 B），在仓库 cwd 下每回合注入。
- 189 条 skill 名字占系统提示词 **20,239 字符**（~5.1K tokens）。
- **7.5 MB 的 `ctf-knowledge` 卡片集**：因为 `~/.fulilian/skills/ctf-knowledge/SKILL.md` 没有 YAML frontmatter，在索引里只渲染为一行 `    - ctf-knowledge`，没有任何描述 —— 模型不知道里面有什么。

### D2. CTF 层从未被真正执行过（2026-09-11 新发现）

`find ~/.fulilian -name usage.json` → **全盘不存在**。

`usage.json` 由 `fulilian_ctf/solver.py:88 write_usage_record()` 在每次
`fulilian solve` 尝试结束时写入 work_dir。它不存在，意味着
**`run_agent.main(mode="ctf")` 这条 CTF 路径一次都没有跑过**。

`state.db` 里那 8 个"解题"会话全部是 `fulilian chat`（`source=cli`）里
**人工对话解题**，不是 `fulilian solve`。

**推论（重要）：**
- 15,460 行 CTF 层从未在真实解题中承担过职责 —— 这解释了 M4 为何是 0，
  且比"工具没注册"更根本：**整条路径没被走过**。
- 因此**任何只作用于 `mode="ctf"` 的改动（如 P0.5.1），都无法用现有
  基线验证** —— 基线测的是另一条代码路径。
- `sessions.cache_write_tokens` 在全部 112 个会话、所有模型上**均为 0**
  → §3.H「压缩强制一次缓存全价重写」**无法从 state.db 验证**，只有代码
  逻辑支撑，属机制推断而非实测证据。**该条已从"证据"降级。**

### E. 知识检索基本是噪声

- trigram 分词器**匹配不了 2 字中文**：`"注入"`→0、`"上传"`→0、`"逆向"`→0（而这三个是最高频词）。
- 真实 pwn 查询 `堆溢出 tcache poisoning libc 2.31` → 端到端 **0 结果**。
- 描述式查询精度 ~30–40%（5 条里 1–2 条相关），噪声直接进 prompt。
- 直接对 FTS 索引执行原始 SQL 会因 `2.31` 抛 `fts5: syntax error near "."` —— **`knowledge_retriever.search()` 自身不做 sanitize**（`fulilian_ctf/knowledge.py::_sanitize_query` 只在上游生效）。
- **而"证明它有效"的 benchmark 是自证的**：

```python
# benchmarks/sampling/build_retrieval_golden.py:94
query = build_query(title)        # 用目标文档自己的标题当查询
# 结果: hit@5 = 1.0  ← 什么也没测到
```

### F. 该用的原语没被用

```
delegate_task:  15 / 13,018
todo:           14 / 13,018
```

用户自己在 `config.yaml` 里写了"嘈杂工作交给子代理"，实际从未发生。噪声全落在主上下文里。

### G. 死代码 / 半成品

| 模块 | 规模 | 状态 |
|---|---|---|
| `fulilian_ctf/budget.py` | 205 行 | **100% 死**（`BudgetTracker` 构造后从不读） |
| `fulilian_ctf/kb_writeback.py` | 231 行 | **全死**，docstring 宣称的调用方 `_writeback_wp` 在代码树中不存在 |
| `fulilian_ctf/challenge_resolve.py` | 136 行 | 死（`cli.py` 有份更好的私有副本） |
| `probe.AutoPrompter` | ~450 行 | 不可达 |
| `trace.SolverTrace` | — | 每个 worker 都写，**没有任何读者** |
| `planner.Planner` | — | 从未被实例化 |
| `Reasoner` | — | 从不接收 LLM 调用 |
| "三重验证门" | — | **实为二重**：gate2 与 gate3 是同一个谓词（`fulilian_ctf/verify.py:8-14` 自承） |
| 升级阶梯 | — | 只是往 description 追加中文提示 + timebox×1.5 + 换模型名 |
| `compression.threshold_tokens: 400000` | — | **死配置**，见 §3.H |

`benchmarks/.../benchmark.py` 把 `solver_impl` mock 掉了 —— **只能测壳，测不出"agent 变笨了"**。

### H. 每次压缩都是一次缓存写

`agent/prompt_caching.py:3` —— 「默认布局使用 4 个 cache_control 断点」。
子代理确认：**"A compression is the only thing that invalidates the cached system prompt."**

而 CTF 模式自己把阈值从 0.7 压到 0.6：

```python
# run_agent.py —— _cap_ctf_compression_threshold
ctf_cap = 0.60
```

128K 窗口下 → **78.6K token 就压缩一次**。每次压缩 → 系统提示词缓存失效 → 下一次调用把 76 KB 全价重写而非 cache-read。

**`AGENTS.md` 里写"提示词缓存是神圣的"，但 CTF 模式的 0.60 封顶正在主动、频繁地打破它。**

### I. 死配置确认

```python
# agent/context_compressor.py:3218  _apply_threshold_tokens_cap docstring
"""...
The cap itself is clamped to the current context length so
a cap larger than the model's window is a no-op
(the ratio-based threshold wins)."""
```

`min(400000, 131072) = 131072`，派生阈值 `131072 × 0.60 = 78643`。`131072 < 78643` 为假 → **从不生效**。

### J. CTF 路径每次都付一次 ~30K token 的背景审查

```python
# cron/scheduler.py:6434 —— 全仓唯一一处
skip_background_review=True,  # Cron has no human-in-the-loop need for
                              # skill/memory review forks (~30K tok/event)
```

而 CTF 路径：

```python
# run_agent.py:9211  _run_solver_turn 内的 AIAgent(...)
agent = AIAgent(
    base_url=base_url, model=model, api_key=api_key,
    max_iterations=max_turns,
    enabled_toolsets=enabled_toolsets_list,
    disabled_toolsets=disabled_toolsets_list,
    save_trajectories=save_trajectories,
    verbose_logging=verbose,
    log_prefix_chars=log_prefix_chars,
    ephemeral_system_prompt=ctf_prompt,
)   # ← 没有 skip_background_review，也没有 skip_memory
```

→ 每次解题结束都 fork 一个完整 `AIAgent` 去审查"这次解题该不该沉淀 memory/skill"，**~30K tokens/次**。批量 10 题 = 30 万 token 纯开销。

### K. 53 个 core tool 永不 defer

`toolsets.py:31` 的 `_FULILIAN_CORE_TOOLS` 是**字面量列表，恰好 53 个名字**，且 core 工具**永不被 `tool_search` 延迟**（`tools/tool_search.py:237 is_deferrable_tool_name`）。

**推论：精简工具面必须改这个字面量，靠 tool_search 收窄是无效的。**

`agent/conversation_loop.py:2588` 自带佐证：*"separately (compression needs them: 50+ tools = 20-30K tokens)."*

### L. 始终开启的静态引导

`agent/prompt_builder.py` 中 >400 字符的常量合计 **17,831 字符 ≈ 4,455 tokens**，全部无条件注入：

| 常量 | 字符 | ~tokens | CTF 相关？ |
|---|---|---|---|
| `KANBAN_GUIDANCE` | 6,604 | **1,651** | ✗ |
| `OPENAI_MODEL_EXECUTION_GUIDANCE` | 2,949 | 737 | 部分 |
| `_WINDOWS_BASH_SHELL_HINT` | 1,292 | 323 | ✓ |
| `MEMORY_GUIDANCE` | 1,225 | 306 | ✗ |
| `SKILLS_GUIDANCE` | 906 | 226 | ✓ |
| `TELEGRAM_RICH_MESSAGES_HINT` | 863 | 215 | ✗ |
| `GOOGLE_MODEL_OPERATIONAL_GUIDANCE` | 860 | 215 | 部分 |
| `TOOL_USE_ENFORCEMENT_GUIDANCE` | 824 | 206 | 部分 |
| `TASK_COMPLETION_GUIDANCE` | 769 | 192 | ✓ |
| `PARALLEL_TOOL_CALL_GUIDANCE` | 618 | 154 | ✓ |
| `DEFAULT_AGENT_IDENTITY` | 496 | 124 | ✓ |
| `WSL_ENVIRONMENT_HINT` | 425 | 106 | ✓ |

**一个 CTF 解题 agent 的上下文里躺着 1,651 tokens 的看板使用说明。**

### M. 迭代预算：文档与代码三方矛盾

| 出处 | 声称 |
|---|---|
| `agent/iteration_budget.py:3-9,20-30` docstring | "default 500" |
| `tools/delegate_tool.py:1765` 注释 | "default 50" |
| `agent/agent_init.py:627` docstring | "default: 90" |
| **实际** `run_agent.py:456` | **`sys.maxsize`**（子代理 `DEFAULT_MAX_ITERATIONS = 250`，`delegate_tool.py:1092`）|

**`max_turns` 是每轮上限，不是每会话上限**：`agent/turn_context.py:671` 每轮新建 `IterationBudget(agent.max_iterations)`。用户 config 的 `150` 是**单次 solve 的严格步数上限**。

### N. 压缩器参数（代码为准，非注释）

```python
# agent/context_compressor.py:3289-3294  ContextCompressor.__init__
threshold_percent     = 0.60     # ContextEngine 基类写 0.75（context_engine.py:121）
protect_first_n       = 3        # 基类写 3
protect_last_n        = 7        # 基类写 6
summary_target_ratio  = 0.20
segment_mode          = False    # 用户 config 设 true

# agent/context_compressor.py:1356, :1363
_FORCE_COMPRESS_TURNS    = 50    # 注释写 "(20)"
_PROACTIVE_COMPRESS_TURNS = 45   # 注释写 "(15)"
```

其他上限：`_MIN_SUMMARY_TOKENS = 2000`(`:735`)、`_SUMMARY_TOKENS_CEILING = 10_000`(`:741`)、`_SUMMARY_INPUT_MAX_CHARS = 160_000`(`:760`)、`_SUMMARY_FAILURE_COOLDOWN_SECONDS = 600`(`:1306`)、`_MISS_FRACTION = 0.10`（连续两次回收 <10% 则抑制压缩）。

---

## 4. 优化建议（按 ROI 排序）

### P0 — 修数据丢失（最高 ROI）

**P0.1 · 工具输出落盘，上下文只留指针**

- **改哪里：** `agent/context_compressor.py` 的 `_prune_old_tool_results` / `_PRUNED_TOOL_PLACEHOLDER` 路径；以及 tool 执行侧的输出截断（`tool_output: {max_bytes: 20000, max_lines: 1000}`）。
- **改成什么：** 超过 N 行的输出 → 全文写盘，上下文只保留「头 20 行 + 尾 20 行 + 文件路径 + 行数」。prune 时把整条替换为指针而非 `"[Old tool output cleared...]"`。
- **为什么：** 这是 §2 的冒烟枪。当前是**物理删除**，导致模型只能重跑。落盘后信息仍可寻回。
- **预期效果：** 直接打击 M1（62–79% 重复调用）。同时 token 增长曲线变平 → 更少触发压缩 → 连带缓解 §3.H 的缓存失效。

**P0.2 · solve-state 由 runtime 维护，不由模型维护**

- **改哪里：** 新增 runtime 侧账本；挂到 `agent/turn_context.py` 的 prologue（压缩之后）与 tool 返回之后。
- **改成什么：** 每次工具返回后抽取事实（命令 / 关键输出 / 产物路径）追加到结构化账本；**每次压缩后自动重注入**。
- **为什么：** 用户 `config.yaml` 里已有手写规则「发现即落盘 —— 上下文摘要会意译，笔记文件是唯一可信副本」。**用户已经用 prompt 规则诊断出了同样的问题**，但模型经常不遵守。这应该是 runtime 的责任，不是提示词的。
- **预期效果：** 消除 `robots.txt` ×3 那类重新推导。

### P0.5 — 一行级修复，先拿干净基线

**P0.5.1 · CTF 路径关掉背景审查 fork**

```python
# run_agent.py:9211  _run_solver_turn
agent = AIAgent(
    ...,
    skip_background_review=True,   # 新增
    skip_memory=True,              # 新增
)
```

- **为什么：** §3.J。cron 路径已经这么做了并写明理由（~30K tok/event）；CTF 路径漏了。CTF 的 skill/memory 沉淀应该在**批后统一做一次**，不是每题一次。
- **预期效果：** ~30K tokens/题。

**P0.5.2 · 删掉死配置 `compression.threshold_tokens: 400000`**

- **为什么：** §3.I，代码自己的 docstring 承认比窗口大的 cap 是 no-op。

**P0.5.3 · 重新评估 `_cap_ctf_compression_threshold` 的 0.60**

- **问题：** 它在用"**更频繁地压缩**"来应对"长解题轨迹"，而压缩恰恰是**丢数据 + 破缓存**的源头 —— **方向是反的**。
- **注意：** 这一条是**推断，不是代码注释的观点**。建议先做小样本对照（0.60 vs 0.75）再定。
- **前提：** 只有在 P0.1 落地后才应该提高阈值（否则删得更多）。

### P1 — 减少往返

**P1.1 · 提供 `run_script` / `batch` 工具**

- **改成什么：** 一次跑 N 条命令或一个 Python 脚本，返回收敛后的结果。
- **为什么：** §1.2 —— 模型只做到 1.12 次/轮，说明 `PARALLEL_TOOL_CALL_GUIDANCE` 那句劝说**没有生效**。**得靠工具形态，不能靠劝说。**
- **预期效果：** 348 次调用可压到 ~20 次。

**P1.2 · 持久 shell + 持久 cwd**

- **为什么：** `record_session_cwd` 已经存在，但模型不知道，每条命令都在重发 `cd X && T="http://..." &&` 前缀。

### P2 — 让委派自动发生

**P2.1 · 规则化自动委派**

- **改成什么：** 预计输出 >N 行或耗时 >T 秒的命令，runtime 自动丢给子代理，只回摘要。
- **为什么：** §3.F（`delegate_task` 15/13,018）。不要指望模型自觉。
- **前置事实（重要）：** 子代理上下文模型是**双向隔离**的 —— 子代理拿不到父历史（`tools/delegate_tool.py:1963` 起以空消息列表构造），父只拿子代理最终总结；工具集继承是**交集**（`:1664-1728`，注释："subagent must not gain tools the parent lacks"）；`MAX_DEPTH = 1`（`:129`）；模型传的 `max_iterations` **被忽略**（配置权威）。**自动委派必须自带充分 context，否则子代理什么也做不了。**

### P3 — 砍固定开销

**P3.1 · 精简 `_FULILIAN_CORE_TOOLS`（改源码，不是改 tool_search）**

- **改哪里：** `toolsets.py:31` 的 53 个名字字面量。
- **CTF 档建议保留：** `terminal` / `file` / `code` / `web` / `vision` / `delegate` / `todo` / `verify_flag`。
- **去掉：** `computer_use`(6.2KB) / `tts`(1.9KB) / `browser-use`(3KB) / `session_search`(3.2KB)。
- **预期效果：** 45.9 KB → **~15 KB**。

**P3.2 · 静态引导按模式门控**

- **改哪里：** `agent/system_prompt.py:341 build_system_prompt_parts`（`stable` 层组装处，`:386-769`）。
- **去掉：** `KANBAN_GUIDANCE`(1,651 tok) / `TELEGRAM_RICH_MESSAGES_HINT`(215) / `MEMORY_GUIDANCE`(306) / platform hints。
- **预期效果：** −2,500 tokens/次。

**P3.3 · 给 `ctf-knowledge/SKILL.md` 加 frontmatter**

- **为什么：** §3.D —— 7.5 MB 卡片集因缺 frontmatter 在索引里等于不存在。

**P3.4 · skills 索引开 `names_only` / `compact_categories`**

- **为什么：** 189 条技能名占 20,239 字符（~5.1K tokens），代码里已有这两个开关。

**P3.5 · AGENTS.md 注入加尺寸上限**

- **建议：** 上限 4 KB；且 CTF 解题时**绝不注入**仓库自己的开发指南。
- **为什么：** §3.D —— 仓库 cwd 下多出 96 KB。

### P4 — 修知识层

**P4.1 分词器**：换 `unicode61` + 分词，或保留 trigram 但让 2 字 CJK 查询直接走 fallback。
**P4.2 sanitize 下沉**：把 sanitize 放进 `knowledge_retriever.search()` 内部。
**P4.3 检索目标换成技术卡**：2583 篇中文赛后 wp 是给人看的；agent 需要紧凑的「技术 + payload」单元。那 20 篇专题（SQL 116K / PHP 反序列化 212K）配 `.idx.md` 分段索引才是对形状 —— **但目前没有任何代码读 `.idx.md`**。
**P4.4 加相关性闸门**：top-3 分数不达标就注入空。**噪声比沉默更贵。**
**P4.5 修或删 benchmark**：§3.E，自证的 `hit@5 = 1.0` 会带来虚假信心和错误的优化方向。

### P5 — 用能力替换仪式

**P5.1** 四阶段 RECON/PLAN/EXECUTE/REFLECT + ABANDON IF + `record_fact` 账本，是在给"不会规划的模型"打石膏，消耗轮次。对强模型换成 10 行操作规则。（`run_agent.py:9094 _build_ctf_system_prompt`）
**P5.2** 补真有用的：并行假设扇出（racer 已有，先确认能不能用）；"同一攻击 3 次变体失败"交给 **runtime 计算**，而不是让模型回忆。

### P6 — 模型路由

硬题走最强模型。现在默认 `DeepSeek-V4-Flash@128K` + 大量石膏 = 弱模型 + 重脚手架。**脚手架补不了模型的差距，模型能省掉脚手架。**

### P7 — 剪面积

68 个顶层 CLI 子命令，CTF 相关 6 个。启动不是瓶颈（`fulilian --version` = 0.166 秒），所以问题不是速度，是 **prompt 面与工具面的冗余**。一个 CTF 专用 profile 能同时减掉认知面与 token 面。

### P8 — 修文档（低风险，累积成本高）

§3.M 的迭代预算三方矛盾（500 / 50 / 90 ↔ 实际 `sys.maxsize` / 250）。
§3.N 的压缩器注释与实际值不符（"(15)"/"(20)" ↔ 45/50；基类 0.75/3/6 ↔ 实际 0.60/3/7）。
`fulilian_ctf/knowledge.py:158 inject_ctf_context()` docstring 把参数命名为 `system_prompt`，但**所有调用者传入的是首个 user 消息**。

---

## 5. 验证方法

**四个数就是记分牌：M1（重复调用率）、M2（调用数/轮）、M5/M6（到 flag 的调用数）、M7（token 数）。**

1. 拿一批**没做过的**真题做 holdout（现有 benchmark 测不出这些 —— 见 §3.E）。
2. 跑基线，确认与 §1 的 M1–M7 一致。
3. 一项一项改，每项单独重测。
4. 防回归：`M1` 必须单调下降；`M4` 应变为非零（CTF 工具真正进入链路）。

**建议的动手顺序：** P0.5.1 + P0.5.2（各一行 → 干净基线）→ P0.1（单函数）→ 重测 M1/M3。

---

## 6. 风险与未验证项

| 项 | 性质 | 说明 |
|---|---|---|
| P0.5.3（提高压缩阈值） | **推断，非代码观点** | 先做 0.60 vs 0.75 小样本对照 |
| P0.1 落盘 | 需设计 | 落盘目录、清理策略、指针格式待定 |
| §3.G 死代码判定 | 子代理全树引用扫描 | 如 `kb_writeback.py` 的 repo 级 grep 只有定义与 `__all__` |
| P3.1 精简工具面 | 需实测 | 去掉的 toolset 可能有隐藏依赖 |
| M1–M10 数字 | **直接查 `state.db` 实测，可复现** | 见 §8 |

---

## 7. 边界声明

- 本文档**不含任何已落地的改动**。
- `fulilian_ctf` 内部的死代码判定来自子代理对全树的引用扫描；§1 的 B/C/H 类数字为直接查库实测。
- 本次研究未逐行通读全部 196 万行代码。

---

## 8. 复现命令

### 8.1 会话统计（M1 / M2 / M3 / M5 / M6 / M7）

```bash
# state.db 有 WAL 争用，必须只读 + 长超时打开
sqlite3 'file:~/.fulilian/state.db?mode=ro&immutable=1' <<'SQL'
.timeout 300000
-- M3: 被压缩消息占比
SELECT COUNT(*) AS total, SUM(compacted) AS compacted FROM messages;
-- M2: 工具调用数分布
SELECT json_array_length(tool_calls) AS n, COUNT(*) FROM messages
  WHERE tool_calls IS NOT NULL AND tool_calls != '[]' GROUP BY n ORDER BY n;
SQL
```

单个会话的重复调用率（M1 / M5 / M6）：按 `session_id` 取出 `terminal` 调用，对命令体去重后算 `1 - distinct/total`。

### 8.2 CTF 工具调用（M4）

```bash
sqlite3 'file:~/.fulilian/state.db?mode=ro&immutable=1' \
  "SELECT COUNT(*) FROM messages WHERE tool_calls LIKE '%verify_flag%'
      OR tool_calls LIKE '%record_fact%' OR tool_calls LIKE '%submit_flag%';"
```

### 8.3 固定开销（M8 / M9）

```bash
cd /tmp && fulilian prompt-size          # M8：中性 cwd
cd ~/.fulilian/fulilian-agent && fulilian prompt-size   # M9：仓库 cwd
```

### 8.4 检索（M10）

```bash
sqlite3 "$FULILIAN_CTF_KB" \
  "SELECT COUNT(*) FROM writeups WHERE writeups MATCH '注入';"   # → 0
```

### 8.5 代码位置速查

| 主题 | 位置 |
|---|---|
| prune 占位符 | `agent/context_compressor.py:763` |
| CTF 压缩封顶 | `run_agent.py` `_cap_ctf_compression_threshold`（~:9152） |
| CTF solver 构造 | `run_agent.py:9211` `_run_solver_turn` |
| cron 关审查的范例 | `cron/scheduler.py:6434` |
| core 工具字面量 | `toolsets.py:31` |
| 压缩器参数 | `agent/context_compressor.py:3289-3294`、`:1356`、`:1363` |
| 压缩触发决策 | `agent/context_compressor.py:3778-3801` |
| 每轮预算重置 | `agent/turn_context.py:671` |
| 静态引导常量 | `agent/prompt_builder.py` |
| 系统提示词三层组装 | `agent/system_prompt.py:341` |
| 缓存断点 | `agent/prompt_caching.py:434` |
| 子代理隔离 | `tools/delegate_tool.py:129, 1092, 1664-1728, 1963` |
| CTF 提示词 | `run_agent.py:9094` `_build_ctf_system_prompt` |
| CTF 工具定义 | `tools/ctf_solve.py` |
| ctf_solve toolset | `toolsets.py:642-653` |
| 检索引擎 | `fulilian_ctf/knowledge_retriever.py` |
| 自证 benchmark | `benchmarks/sampling/build_retrieval_golden.py:94` |

### 8.6 过程指标采集器（2026-09-11 新增）

```bash
cd ~/.fulilian/fulilian-agent

# 列出可选会话
python3 benchmarks/process_metrics.py --list

# 单会话 / 批量 / 落基线
python3 benchmarks/process_metrics.py --session <id>
python3 benchmarks/process_metrics.py --recent 10
python3 benchmarks/process_metrics.py --recent 10 --json benchmarks/baselines/<日期>-<标签>.json
```

只读 `state.db`（`mode=ro&immutable=1`），**不碰 solver 一行代码**。

---

## 9. 实施日志

### 2026-09-11 · 分支隔离

```
ctf-opt                          ← 本次工作分支
wip/root-layout-2026-09-11       ← 你在途的布局重构（89 个变更）已快照
refactor/root-layout @ 974ac6b   ← 原分支，未被触碰
```

- `44d89a7` 根目录布局重构 WIP 快照（86 个文件）
- `383a63b` 本计划书

### 2026-09-11 · A1 完成

在途工作已快照到 `wip/root-layout-2026-09-11`，工作树干净，`ctf-opt` 为工作分支。
**未推送任何分支到 origin。**

### 2026-09-11 · A4 完成（过程指标采集器）

新增 `benchmarks/process_metrics.py` + `benchmarks/baselines/2026-09-11-ctf-chatpath.json`。

**验证：** 既有 harness 在布局重构后完好 —— `python3 -m fulilian_ctf.benchmark --suite unit`
仍 25/25 通过。

**核实的两处缺口：**
1. `--suite unit` 把 solver mock 成参考解（README 自承）→ **测不了 agent 质量**。
2. `--suite smoke` 是待填骨架（`"[BUUCTF 题号待填]"`），且 runner 一律 exit 2 →
   真 API 的真题测量**不存在**。
3. unit 摘要里 `平均token = None` → 连 token 都没在记。

**基线（8 个 CTF 会话）：** M1 79.9% · M2 1.04 · M3 82.2% · M4 0 ·
M6 86.2M cache_read / 1,036 api_calls / 平均 83k per call。

**本轮产生的修正：**
- §3.H 从「证据」降级为「机制推断」—— `cache_write_tokens` 全库为 0，无法验证。
- 新增 §3.D2：CTF 层从未执行过（`usage.json` 全盘不存在）。
- M5 是弱代理指标，只认同版本前后对照，不可跨版本比较。

**对后续步骤的影响：**
P0.5.1 / P0.5.2 只作用于 `mode="ctf"`，而**该路径从未跑过** →
要么先做一次真实 `fulilian solve` 建立 CTF 路径基线（需题 + API 配额），
要么接受 A2/A3 仅作代码级验证、把效果测量推迟到首次真实解题。

---

## 10. 当前状态

- **代码改动：0 处。** 计划书与采集器是纯新增。
- 分支：`ctf-opt`（未推送）。
- 下一步待定：见 §9 末「对后续步骤的影响」。
