# CTF 解题 Agent 优化计划书

> **状态：证据与基线已就绪，优化项尚未开始实施。** §9 记录了已完成的前置工作
> （1 个阻断性 bug 修复、2 套基线采集器、2 处 A2/A3 小改动）；§4 的 P0–P8 优化项
> **一个都没做**。当前状态与下一步见 §10。
> **撰写日期：** 2026-09-11
> **目标：** 把 fulilian 打造成以 CTF 解题为重点的智能体 —— 强项在难题，简单题一次通过。
> **用途：** 自包含的上下文保险。阅读本文不需要原始对话；所有数字附复现命令，所有代码结论附文件:行号。

---

## 0. 一句话结论

**fulilian 的问题不是"CTF 功能不够"，而是三层错配：**

1. **真正跑题的是一个通用助理 agent 循环。** 全仓 1,961,148 行 Python（5,313 个 `.py`），CTF 相关只有 15,460 行（**0.8%**）。其余是 Telegram/Discord/Slack/Feishu/Matrix 平台适配、看板、cron、TTS、视频生成、宠物、Home Assistant。
2. **CTF 层几乎全是"壳"。** `fulilian_ctf` 里所有东西最终收敛到一次 `run_agent.main(query, mode="ctf")`。planner / reasoner / specialist **全是确定性 Python，一次额外 LLM 调用都没有**。
3. **它对外宣传的 CTF 核心能力，在用户实际使用的路径上从未被调用过一次。**
   （2026-09-11 追补：这**不是**"没人用"，而是 `fulilian solve -p` 被一个
   argparse `dest` 撞名劫持到了通用一次性对话分支，CTF 求解器根本没启动，
   而且**以退出码 0 静默结束**。根因与修复见 §3.D2 / §9。修好后 3/3 解出。）

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
> ⚠️ M1–M10 测的是 **`fulilian chat` 人工解题路径**（`source=cli`）。
> CTF 求解器（`mode="ctf"`）不参与这条路径，**这些数字对 CTF 层的改动无效**。
>
> **CTF 路径基线见 §1.3**（2026-09-11 建立，`benchmarks/baselines/2026-09-11-ctf-path.json`）。
> 在此之前 CTF 路径根本跑不起来（§3.D2 的 argparse `dest` 冲突，已由 `bbf054d` 修复），
> 所以这是 CTF 层的**第一个**可比基线。

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

### 1.3 CTF 路径基线（2026-09-11 采集，3 题全 easy）

M1–M10 测的是 `fulilian chat` 人工路径。CTF 求解器（`mode="ctf"`）此前**根本跑不起来**
（见 §3.O），修复后才第一次拿到真实数字。

| # | 指标 | 实测基线 | 采集方式 |
|---|---|---|---|
| C1 | 解出率 / flag 正确率 | **3/3，3/3**（与 manifest `expected_flag` 逐字一致） | §8.7 |
| C2 | 每题的 `attempts` | 1 / 2 / 1 | §8.7 |
| C3 | `api_calls`（usage.json） | 12 / 24 / 12，合计 **48** | §8.7 |
| C4 | **prompt : 补全 token 比** | 622,946 : 9,211 = **68 : 1** | §8.7 |
| C5 | 总 token | **888,482**（3 题） | §8.7 |
| C6 | 工具调用数 | 13 / 13 / 17，合计 43 | §8.7 |
| C7 | 工具重复率 | 23% / 31% / 35% | §8.7 |
| C8 | **工具发现开销占比** | **7/43 = 16.3%**（`tool_describe`+`tool_search`） | §8.7 |
| C9 | **shell : read_file** | **8 : 15**（CTF 本该 shell 主导） | §8.7 |
| C10 | API 延迟均值 / 最大 | 5.7–6.9s 均值 | §8.7 |
| C11 | 缓存命中率均值 | 80.5% / 87.1% / 88.5%；`cache_written` 全 0 | §8.7 |

逐题明细：

| fixture | 解出 | api | 总 token | 工具 | 重复率 | 发现开销 | shell/read | 缓存命中 |
|---|---|---|---|---|---|---|---|---|
| misc-morse-01 | ✓ | 12 | 213,144 | 13 | 23% | 2 (15%) | 2/4 | 80.5% |
| crypto-rsa-01 | ✓ | 24 | 436,020 | 13 | 31% | 2 (15%) | 3/5 | 87.1% |
| web-robots-01 | ✓ | 12 | 239,318 | 17 | 35% | 3 (18%) | 3/6 | 88.5% |

> **基线存档：** `benchmarks/baselines/2026-09-11-ctf-path.json`
> 采集器：`benchmarks/ctf_path_baseline.py`（读 work_dir 的 `usage.json` + `solver.log`）。
> 器材：3 个 fixture 复制到 `/tmp/ctf-baseline/` 后跑 —— 必须复制，因为
> `_prepare_work_dir` 返回的就是题目目录本身并往里写 `AGENTS.md` / `.git` /
> `FLAG`，直接跑会污染被跟踪的 `benchmarks/fixtures/`。

三条直接指向优化项的读数：

- **C8 = 16.3%。** 43 次工具往返里有 7 次纯粹用于「问出工具签名」（模型必须靠
  `tool_describe` / `tool_search` 才发现 `record_fact` 要 `work_dir`、
  `submit_flag` 要 `work_dir`）。这是 CTF 工具被推迟的直接代价 —— 对应 P0.2 与 P7。
- **C9 = 8 : 15。** CTF 解题本该 shell 主导（`curl`/`python -c`/`grep`），实测
  `read_file` 是 `terminal` 的近两倍。模型在「看」而不是「打」—— 对应 P1/C2
  （分批工具 + 持久 shell）。
- **C4 = 68 : 1 —— 见下方 §1.4，成因与初判不同，已重测修正。**

### 1.4 C4 的真正成因：每次调用重发固定开销，不是历史膨胀（2026-09-11 重测）

初版 §1.3 把 68:1 归因为「钱花在反复重发历史」，指向 P0.1。**重测后该归因不成立。**

**证据一：截断机制从未触发。** 三个 fixture 的 `solver.log` 里
`OUTPUT TRUNCATED` **0 次**、`persisted-output` **0 次**。
即 `tools/terminal_tool.py:3695` 的丢弃式截断与
`tools/tool_result_storage.py` 的落盘机制**一次都没跑过** ——
P0.1 在这批 fixture 上**零效果**（因为输出本来就小）。

**证据二：prompt 几乎不增长，主导成本是"每次重发首屏"。**

`📊 Request size: N messages, ~X tokens (~Y chars)` **只统计 messages，不含工具 schema**；
而 `💾 Cache: hit/total` 那行的 total 是**含工具的整包**。两者相减即得工具占用。
以 web-robots-01 第 1 次调用为例：messages 9,454 / 整包 14,561 → **工具 ≈ 5,107 tokens**。

逐次 messages 序列（§8.7 可复现）：

| fixture | 调用数 | 首次 | 末次 | 全程增长 | Σmessages |
|---|---|---|---|---|---|
| misc-morse-01 | 12 | 9,460 | 13,804 | **+4,344** | 146,346 |
| crypto-rsa-01 | 10 | 9,525 | 14,264 | **+4,739** | 120,616 |
| web-robots-01 | 12 | 9,454 | 16,220 | **+6,766** | 165,650 |

**对账（关键一步）：** 用「Σmessages + 调用数 × 工具占用」还原 provider 计数：

```
misc-morse-01: 146,346 + 12 × 5,107 = 207,630   vs usage.json input_tokens = 210,781
```

**误差 1.5%** —— 说明这条成本模型成立：

```
input_tokens ≈ Σ(每次 messages) + 调用数 × 工具 schema tokens
```

**结论：** 一次 12 调用的简单题，
**~83% 的 input token 是首屏那 14.5K（工具 5.1K + messages 9.5K）被原样重发 12 次**，
真正的对话增长只有 4.3K（占 2%）。
**省钱靠两件事：减少调用次数、压小首屏** —— 不是靠历史压缩，更不是靠输出落盘。

**证据三（修正 §3.K 对 CTF 的适用性）：CTF 只加载 14 个工具，不是 53 个。**
日志实测：`🛠️ Final tool selection (17 tools)` → `🛠️ Loaded 14 tools`
（`🔎 Tool Search (tier 1): 6 MCP/plugin tools deferred (~1272 tokens)`）。
§3.K 的「53 个 core tool 永不 defer」是 **chat 路径**的问题；CTF 路径经
`tool_search` 折叠后只有 14 个 —— 但**这 14 个仍然每次全量重发**。

| 工具 | schema 字符 |
|---|---|
| terminal | 3,281 |
| **memory** | **3,176** |
| **skill_manage** | **2,455** |
| search_files | 1,982 |
| patch | 1,970 |
| read_file | 1,675 |
| tool_search | 1,467 |
| vision_analyze | 1,358 |
| process | 1,356 |
| write_file | 1,270 |
| web_extract | 1,112 |

`memory` + `skill_manage` = **5,631 字符 / 22,942 字符 = 24.5% 的工具 schema**
= **~1,400 tokens/次调用 ≈ 全部 input token 的 8%**。
而 `toolsets.py:646` 的注释写明它们存在的唯一理由是「回合后自省触发依赖」
（`toolsets.py:637-640`：「主会话带上这两个工具后 fork 可正常执行写入」）——
**A3 已关掉那条 fork**。消费方不存在了，成本仍在每次请求上支付。
→ 新增 **P0.5.4**。

> **自我更正：** A3 条目里我写「不加 `skip_memory=True`，因为 `ctf_solve`
> toolset 刻意保留了 memory 工具」。**不加 flag 是对的，但推理不完整** ——
> 当时只看到"toolset 保留了它"，没看出保留它的**唯一理由**正是被 A3 关掉的
> 那条 fork。flag 不该加，而 toolset 里这两个工具该删。

**对优先级的影响（重要）：**
在现有 fixture 上，P0.1 的机制**从未触发**；真正的杠杆是
**P0.5.4（删死重工具）≈ P3/P7（砍首屏）> 减少调用次数**。
P0.1 只有在**难题**上才可能见效（长扫描、反编译转储、爆破日志），
而当前 3 题全 easy —— **这批基线验证不了 P0.1**。
（这不否定 P0.1 的价值，但改变了它的排序与验证方式。）

### 1.5 两条附带读数（2026-09-11，来自同一份 solver.log）

**（1）CTF 路径的压缩阈值实际是 600,000 —— 简单题上压缩永不触发。**

```
📊 Context limit: 1,000,000 tokens (compress at 70% = 700,000)
🧩 CTF mode: compression threshold capped 0.70 → 0.60
```

即 CTF 认为窗口是 **1,000,000**，0.70 被封顶到 0.60 → **600,000 才压缩**，
而实际用量 ~15K。**推论：**
- §2/§3.H/P0.5.3 所有关于压缩的分析，在 CTF easy 路径上是**惰性的** ——
  压缩一次都没发生。P0.5.3（0.60 vs 0.75）在这批题上**无可测量差异**。
- ⚠️ **潜在风险：** 若该模型真实窗口远小于 1,000,000（`DeepSeek-V4-Flash`
  经 `custom`/scnet.cn 转发），则 600K 的压缩闸**永远晚于** provider 的硬上限 ——
  长跑会在压缩之前先撞 400。**未验证**，需查 model metadata 与该 provider
  的实际上限（列为待办）。

**（2）§3.E 的具体实例：注入的 WP 参考确实无关。**

web-robots-01（robots.txt 题）被注入的三条"相似历史 WP"：

```
- cve-2024-29296 — ...{[baseline]*1000:.1...        （Portainer 中间件漏洞）
- harbor-tactics — ...[Web]hook 滥用 Harbo...
- mcp-attack-payloads — ...ool_[baseline](tool...   （MCP 攻击载荷）
```

**三条对 robots.txt 全部无关**，且正文被截成 `...{[baseline]*1000:.1...`
这样的碎片（疑似脱敏或模板渲染残留）。整个注入块 2,453 字符 ≈ 613 tokens，
其中 WP 段 474 字符 —— **成本不大，但信噪比接近 0**，且**每题必注入**。
→ 对应 P4（修知识层）。

### 1.6 P0.5.4 实测效果：删两个工具名 = 每次调用少 17,957 字符（2026-09-11 实施并对照跑）

**改动**：`toolsets.py` 的 `ctf_solve` 移除 `"memory"` 与 `"skill_manage"`。

**为什么牵连比预期大** —— 这两个名字不只是两个工具 schema。删掉后有三处**分别**
按 `valid_tool_names` 门控的内容一起消失（直接构造 system prompt 逐块比对得出）：

| 消失的内容 | 字符数 | 门控点 |
|---|---:|---|
| `memory` + `skill_manage` 工具 schema | 5,631 | `ctf_solve` 工具表 |
| `MEMORY_GUIDANCE` + `SKILLS_GUIDANCE` 引导块 | 2,134 | `system_prompt.py:437` / `:444` |
| **技能索引（205 条技能清单）** | **10,192** | `system_prompt.py:524` |
| **合计** | **17,957** | 每次 API 调用 |

> 重建验证：用 `enabled_toolsets=["ctf_solve"]` 构造 agent 后渲染 system prompt，
> 移除前 27,717 字符 / 14 工具，移除后 15,391 字符 / 12 工具 ——
> **14 / 12 与两次真跑日志里的 `Loaded 14 tools` / `Loaded 12 tools` 逐字吻合**，
> 说明这个重建忠实于真实路径。

**最大的一块是技能索引，而它在 CTF 路径上本来就够不着。** 基线日志的
`Final tool selection (17 tools)` 里**没有 `skill_view`，也没有 `skills_list`**：

```
compile_check, git_auto_commit, http_session, memory, patch, process, read_file,
record_fact, search_files, skill_manage, submit_flag, terminal, verify_flag,
vision_analyze, web_extract, web_search, write_file
```

也就是说：那 10,192 字符的索引**列了 205 个技能，而 agent 没有任何工具能打开其中
任何一个** —— 唯一在场的 `skill_manage` 是写入口（且因 A3 关闭自省 fork 而无人消费）。
这是**纯粹的噪声**，不是能力。

**对照跑（同一协议，3 题，改动前 vs 改动后）：**

| | 基线 | P0.5.4 后 | 变化 |
|---|---:|---:|---:|
| 解出率 | 3/3 | 3/3 | — |
| flag 逐字一致 | 3/3 | 3/3 | — |
| 首屏 prompt tokens | 9,454–9,525 | 6,290–6,297 | **−3,186/次调用** |
| api_calls | 48 | 31 | −35.4% |
| input tokens | 622,946 | 389,021 | −37.6% |
| 工具调用 | 43 | 38 | −11.6% |
| 延迟均值 | 5.7–6.9s | 5.35–5.58s | −4~19% |

**约束在哪一格要说清**：首屏的三个读数高度一致
（9,460→6,297 / 9,525→6,290 / 9,454→6,294，即 −3,160 / −3,235 / −3,163），
这是**确定性**的每调用节省 ≈ **3,186 tokens**。而 api_calls 48→31 是**行为差异**：
crypto-rsa-01 从 24 次掉到 8 次，单次运行无法区分是"提示更干净所以路径更直"
还是普通随机性 —— **n=1，不归因给 P0.5.4**，要归因得多跑几轮。所以
−37.6% 的总量降幅里，**只有 −3,186/次 那部分是本次改动可确证的**。

**耦合（已写进代码注释与测试）**：这两个工具**唯一**的用途是让回合后自省 fork 能
触发。A3 用 `skip_background_review=True` 关掉了那条 fork，触发条件无人消费。
**若将来重新开启 background_review，必须把这两个名字加回，否则自省会静默失效**
（不报错、不告警，只是经验不再沉淀）。`tests/test_toolsets.py` 的
`test_solver_spawn_and_toolset_are_coupled` 把这个耦合锁成双向断言，而不是锁单边。

---

## 2. 压缩后**无法找回内容**（原题：冒烟枪）

> **2026-09-11 修正（A8）：** 本节初稿称"旧工具输出被整条替换成占位符、
> 无摘要无指针"。**该描述只对其中一条路径成立**，且**两条路径在 CTF 路径上都
> 尚未触发过**（§1.5：CTF 压缩阈值 600K，easy 题用量 ~15K）。
> 下面是核对代码后的准确版本。

`agent/context_compressor.py` 里有**两套**不同的处置，严重度不同：

**（一）主路径 `_prune_old_tool_results`（`:3974`）—— 有摘要，但没有回程票。**

它调 `_summarize_tool_result()`（`:2004`）生成**保留关键元数据的一行摘要**：

```
[terminal] ran `curl -s http://t/p/` -> exit 0, 47 lines output
[read_file] read src/app.py from line 1 (3,400 chars)
```

命令、退出码、行数、文件路径都还在。**所以不是"删得干干净净"。**

**真正的问题是内容无处可寻：** 那 47 行输出**从未落盘**，摘要里因此
**没有任何路径可指**。模型知道"我跑过这条命令、它成功了"，但要拿回输出内容
**只能重跑** —— 这正是重复调用循环的机制，也是 P0.1 的靶子。
（判据：`_PRUNE_MIN_CHARS = 200`，`:769`，超过才摘。）

**（二）salvage 路径 `_prune_stale_reasoning_replay`（`:355`）—— 才是真·删除。**

```python
# agent/context_compressor.py:556-557
if isinstance(content, str) and len(content) > _PRUNE_MIN_CHARS:
    msg["content"] = _PRUNED_TOOL_PLACEHOLDER     # "[Old tool output cleared...]"
# agent/context_compressor.py:445
_SALVAGE_KEEP_RECENT_TOOLS = 2
```

**只保留最后 2 条**工具结果，其余超 200 字符的一律换成那句占位符 ——
**没有摘要、没有头尾、没有指针**。这条才是初稿描述的形状，但它是
**salvage 兜底路径**，不是常态。

**对 M3 的解释仍然成立：** 75% 消息被标记 `compacted`，但只有 116 条带摘要标记
→ 大多数"压缩"走的是 Phase-1 的 prune，而非 Phase-2 的 LLM 摘要。
**（该数字来自 chat 路径基线。）**

**修正后的 P0.1 定义：** 不是"把删除改成摘要"（主路径已经在摘要了），
而是**让摘要里有东西可指** —— 输出先落盘，摘要带上路径。§10 记了具体落点。

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

### D2. CTF 层从未被真正执行过 —— 根因已定位并修复（2026-09-11）

**症状：** `find ~/.fulilian -name usage.json` → **全盘不存在**。
`usage.json` 由 `fulilian_ctf/solver.py:88 write_usage_record()` 在每次
`fulilian solve` 尝试结束时写入 work_dir。它不存在，意味着
**`run_agent.main(mode="ctf")` 这条 CTF 路径一次都没有跑过**；
`state.db` 里那 8 个"解题"会话全部是 `fulilian chat`（`source=cli`）
人工对话解题。

**根因（不是"没人用"，是"用了也不走这条路"）：** `argparse` 的
`dest` 命名空间冲突。

```python
# fulilian_cli/_parser.py:153  顶层
parser.add_argument("-z", "--oneshot", metavar="PROMPT", default=None, ...)
#                              ^ 存**字符串** prompt

# fulilian_cli/subcommands/solve.py:37  solve 子命令（修复前）
solve_parser.add_argument("-p", "--print", dest="oneshot",
                          action="store_true", ...)
#                              ^ 存**布尔** True
```

argparse 的子解析器与顶层解析器**共用同一个 `Namespace`**。`dest` 同名时，
后写的子解析器参数会覆盖顶层同名属性。于是 `fulilian solve <id> -p` 把
`args.oneshot` 置成布尔 `True`，而 `main()` 在派发 `args.func(args)`
**之前**就命中：

```python
# fulilian_cli/main.py:14789
if getattr(args, "oneshot", None):
    _run_and_exit_oneshot(args.oneshot, ...)   # ← cmd_solve 永不执行
```

实测探针确认：`[SPY] _run_and_exit_oneshot fired! prompt=True type=bool` /
`[SPY] cmd_solve was NEVER reached`。

**后果链：** CTF 求解器从未启动 → 通用一次性对话收到一个 **Python 布尔值**
当 prompt → provider 回 `HTTP 400 "Format Error"` → **进程仍以退出码 0 退出**
（静默假成功）→ `usage.json` 永不落盘 → "CTF 路径是否执行过"这件事
**在观测上不可见**。也就是说 §3.A 的 M4=0 不只是"工具没注册"，而是
**整条路径被一个参数名吃掉了**，且失败得无声无息。

**修复：** `bbf054d`。`dest="ctf_oneshot"`（`solve.py:43`），
并在 `fulilian_ctf/cli.py:382` 保留读 `oneshot` 的回退以兼容既有测试。

**F4-002 附带排查：** 全量审计了其余子解析器的 `dest` 与顶层撞名情况 ——
`gateway.py --verbose/--quiet`、`import_agent.py --source`、
`solve.py --max-turns`、`skills.py --source`（×3）、`gui.py --source`、
`claw.py --source`（×2）、`knowledge.py --source`、`insights.py --source`、
`mcp.py --verbose`。**只有 `oneshot` 会在派发前重路由 `main()`**，
其余撞名是良性的（仅影响日志详细度），未改动。

**原推论需要修正的部分：**
- ~~"15,460 行 CTF 层从未承担过职责"~~ → 修复后 3/3 解出（§1.3），
  CTF 层**是**能跑通的，之前的 0 是参数劫持而非能力缺陷。
- ~~"任何只作用于 `mode="ctf"` 的改动都无法用现有基线验证"~~ → 现在
  **可以**：`benchmarks/ctf_path_baseline.py` + §8.7 已建立 C1–C11 基线。
- **仍然成立：** `sessions.cache_write_tokens` 在全部 112 个会话、所有模型上
  均为 0 → §3.H「压缩强制一次缓存全价重写」**无法从 state.db 验证**，
  只有代码逻辑支撑，属机制推断而非实测证据。**该条维持降级。**

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

### P0 — 修数据丢失

> ⚠️ **CTF 路径上本节已降级**（§1.4 / A7）：P0.1 的机制在 easy fixture 上
> **0 次触发**，而固定开销占 68–79%。当前 CTF 的最高 ROI 是 **P0.5.4** 与 **P3/P7**。
> P0.1 保留给难题（长扫描 / 反编译转储 / 爆破日志），需先有难题 holdout 才能验收。
> 本节内容对 `fulilian chat` 路径仍然成立。

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

**P0.5.1 · CTF 路径关掉背景审查 fork** ✅ **已完成（A3，`67fb68f`）**

```python
# run_agent.py:9222  _run_solver_turn（实施后的实际形态）
agent = AIAgent(
    ...,
    skip_background_review=True,   # 已加
    # skip_memory=True,            # 未加 —— 见下
)
```

- **实做与计划的差异：** 计划里还要加 `skip_memory=True`，**实施时去掉了**。
  按 `agent/agent_init.py:695-702`，`skip_background_review` 本身就是覆盖两条
  review 路径的单一开关；`skip_memory` 不带来额外收益，却会顺带关掉外部
  memory provider（`agent_init.py:1898`），而 `ctf_solve` toolset 刻意保留了
  `memory` 工具（`toolsets.py:646-650`，注释写明"回合后自省触发依赖"）。
- **为什么：** §3.J。cron 路径已经这么做了并写明理由（~30K tok/event）；CTF 路径漏了。CTF 的 skill/memory 沉淀应该在**批后统一做一次**，不是每题一次。
- **预期效果：** ~30K tokens/题。**效果尚未测量** —— 待做同 fixture 对照跑（§10）。

**P0.5.2 · 删掉死配置 `compression.threshold_tokens: 400000`** ✅ **已完成（A2）**

- **为什么：** §3.I，代码自己的 docstring 承认比窗口大的 cap 是 no-op。
- 已从 `~/.fulilian/config.yaml` 移除并原位留注释，备份
  `config.yaml.bak-20260911-200734`（仓库外改动）。

**P0.5.3 · 重新评估 `_cap_ctf_compression_threshold` 的 0.60**

- **问题：** 它在用"**更频繁地压缩**"来应对"长解题轨迹"，而压缩恰恰是**丢数据 + 破缓存**的源头 —— **方向是反的**。
- **注意：** 这一条是**推断，不是代码注释的观点**。建议先做小样本对照（0.60 vs 0.75）再定。
- **前提：** 只有在 P0.1 落地后才应该提高阈值（否则删得更多）。
- **已验证的前提：** 该 0.60 封顶**确实生效**（曾怀疑被 `_SMALL_CTX_THRESHOLD_PERCENT`
  这条 floor 抬回 0.75 从而失效 —— 查证后 floor 就是 0.60，`max(0.60, 0.60) = 0.60`，
  假设不成立，见 A2 条目）。

**P0.5.4 · 从 `ctf_solve` 工具集删掉 `memory` 与 `skill_manage`** ⏳ **未实施（ROI 最高）**

```python
# toolsets.py:642-650
"ctf_solve": {
    "tools": [
        "verify_flag", "checkpoint", "generate_writeup", "compile_check",
        # 回合后自省触发依赖（见上方注释）：记忆 + skill 写入
        "memory", "skill_manage",          # ← 删这两行
    ],
    "includes": ["terminal", "file", "web", "vision"],
}
```

- **为什么：** §1.4 的证据三。两者合计 **5,631 字符 ≈ 1,408 tokens，每次调用都重发**；
  而 `toolsets.py:637-640` 的注释写明它们存在的**唯一理由**是供
  `background_review` fork 写入 —— **A3 已关掉那条 fork**，消费方不存在了。
- **预期效果：** ~1.4K tokens/次调用。12 次的简单题 ≈ 17K；
  50 次的难题 ≈ 70K。改动是删两行 + 改注释，**零逻辑风险**。
- **前提：** 必须先确认 A3 的 `skip_background_review=True` 保持生效，
  否则会打断 fork 的写入（这正是当初保留它们的原因）。
- **验证：** 重跑一题，对比 C3（api_calls）与 C5（总 token）；
  并确认 `run_agent.py:9211` 处 flag 仍在。
- **与 A3 的关系：** 这是 A3 的**另一半**。A3 只关掉了 fork，没清理
  为 fork 服务的工具。两条一起做才是完整的。

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

**记分牌分两套，别混用 —— 它们测的是两条不同的代码路径：**

| 路径 | 记分牌 | 采集器 | 基线 |
|---|---|---|---|
| `fulilian chat`（人工解题） | M1 重复调用率 · M2 调用数/轮 · M5/M6 到 flag 的调用数 · M7 token | `benchmarks/process_metrics.py`（读 state.db） | §1.1 / §1.2 |
| `fulilian solve`（**CTF 层**） | C1 解出/正确率 · C3 api_calls · C4 prompt:补全 · C5 总 token · C8 发现开销 · C9 shell:read | `benchmarks/ctf_path_baseline.py`（读 work_dir） | **§1.3** |

改动只作用于 `mode="ctf"` 时，**只有 C 系列能验收**；反之亦然。

1. 拿一批**没做过的**真题做 holdout（现有 benchmark 测不出这些 —— 见 §3.E）。
2. 跑基线，确认与 §1 对应表格一致。
3. 一项一项改，每项单独重测。
4. 防回归：`M1`/`C6` 必须单调下降；`M4` 应变为非零（CTF 工具真正进入链路）。

**建议的动手顺序（已按 §1.4 重排）：** ~~P0.5.1 + P0.5.2~~ 已完成（A2/A3）
→ **P0.5.4**（删死重工具，零风险，~1.4K tok/次调用）
→ 一次对照跑同时验 A3 与 P0.5.4（`skip_background_review=False` vs 默认）
→ **P3/P7** 砍固定开销 → 最后才是 P0.1（需先有难题 holdout）。

**注意：** 现有 3 题基线**无法验收 P0.1**（§1.4 证据一：机制 0 次触发）。
在拿到难题 holdout 之前，P0.1 的任何"效果"都不可测 —— 别用它当第一个改动。

---

## 6. 风险与未验证项

| 项 | 性质 | 说明 |
|---|---|---|
| P0.5.3（提高压缩阈值） | **推断，非代码观点** | 先做 0.60 vs 0.75 小样本对照 |
| P0.1 落盘 | 需设计 | 落盘目录、清理策略、指针格式待定 |
| §3.G 死代码判定 | 子代理全树引用扫描 | 如 `kb_writeback.py` 的 repo 级 grep 只有定义与 `__all__` |
| P3.1 精简工具面 | 需实测 | 去掉的 toolset 可能有隐藏依赖 |
| M1–M10 数字 | **直接查 `state.db` 实测，可复现** | 见 §8 |
| C1–C11 数字 | **3 题，全 easy，样本极小** | 足以做前后对照，**不足以断言能力**；难题 holdout 仍缺 |
| A3 的效果 | **未测** | 需 `skip_background_review=False` 对照跑（§10） |
| CTF API 无读超时 | **实测会挂死** | 一次挂起样本；属 P0 邻域，未处理 |
| **P0.1 在本基线零效果** | **实测：机制 0 次触发** | §1.4 证据一；**不能用现有基线验收 P0.1** |
| **C4 的归因** | **已重测修正** | 初判"重发历史"**错误**；实为每次重发固定开销（68–79%） |
| schema 字符→token | **4 字符/token 为估算** | 字符数是实测，token 数是换算；provider 计数可能不同 |

---

## 7. 边界声明

- 本文档**记录**已落地的改动（§9 / §10），但 §4 的优化项（P0–P8）**尚未实施**。
- §9 是**时序日志**：早期条目（如 A4）记录的是当时的判断，后来被推翻的部分
  已就地加注指向后续条目，**不追改历史原文**。
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

### 8.7 CTF 路径基线（2026-09-11 新增，§1.3 的数据来源）

```bash
cd ~/.fulilian/fulilian-agent

# 1) 复制 fixture 到 /tmp —— 必须复制，不能原地跑：
#    _prepare_work_dir 返回题目目录本身并往里写 AGENTS.md / .git / FLAG / solver.log，
#    原地跑会污染被 git 跟踪的 benchmarks/fixtures/。
mkdir -p /tmp/ctf-baseline
cp -r benchmarks/fixtures/misc-morse-01   /tmp/ctf-baseline/
cp -r benchmarks/fixtures/crypto-rsa-01   /tmp/ctf-baseline/
cp -r benchmarks/fixtures/web-robots-01   /tmp/ctf-baseline/

# 2) 逐题解（每题独立进程；`solve` 的题号是**位置参数**，不是 --id）
venv/bin/python -m fulilian_cli.main solve /tmp/ctf-baseline/misc-morse-01 -p
venv/bin/python -m fulilian_cli.main solve /tmp/ctf-baseline/crypto-rsa-01 -p
venv/bin/python -m fulilian_cli.main solve /tmp/ctf-baseline/web-robots-01 -p

# 3) 立刻采集（solver.log 每次运行被 "w" 覆盖，不能隔夜）
python3 benchmarks/ctf_path_baseline.py \
    --dirs /tmp/ctf-baseline/misc-morse-01 \
           /tmp/ctf-baseline/crypto-rsa-01 \
           /tmp/ctf-baseline/web-robots-01 \
    --manifest benchmarks/manifest-unit.yaml \
    --json benchmarks/baselines/2026-09-11-ctf-path.json
```

**若采集器报 "缺 usage.json"** → 该次 solve **没走 CTF 路径**，
先查是否又出现 §3.D2 的 `dest` 撞名（`args.oneshot` 被设成 bool）。

**交叉校验：** 采集器读 `manifest-unit.yaml` 的 `expected_flag` 与 work_dir 的
`FLAG` 文件逐字比对（`flag_matches`），避免"解出来了但答案是错的"被记成成功。

### 8.8 §1.4 的两项测量（A7 新增）

```bash
cd ~/.fulilian/fulilian-agent

# (1) 逐次 prompt 大小 —— 看固定开销 vs 对话增长
for d in misc-morse-01 crypto-rsa-01 web-robots-01; do
  echo "=== $d ==="
  grep -o "📊 Request size: [0-9]* messages, ~[0-9,]* tokens" \
      /tmp/ctf-baseline/$d/solver.log | sed 's/📊 Request size: //'
done

# (2) 截断/落盘机制是否触发过（A7 证据一，期望 0）
grep -c "OUTPUT TRUNCATED"  /tmp/ctf-baseline/*/solver.log
grep -c "persisted-output"  /tmp/ctf-baseline/*/solver.log

# (3) CTF 工具集的 schema 体积（A7 证据三）
./venv/bin/python - <<'PY'
import json, sys; sys.path.insert(0, ".")
from model_tools import get_tool_definitions
defs = get_tool_definitions(enabled_toolsets=["ctf_solve"], quiet_mode=True)
blob = json.dumps(defs, ensure_ascii=False)
print(f"{len(defs)} 个工具, {len(blob):,} 字符")
for n, d in sorted(((len(json.dumps(d, ensure_ascii=False)), d["function"]["name"])
                    for d in defs), reverse=True):
    print(f"  {n:>7,}  {d}")
PY
```

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

> ⚠️ **本条目已被后续工作取代，保留以存档当时的判断。** 上句"该路径从未跑过"
> 的**原因**在 A5 定位到了：不是没人跑，是跑了被 argparse `dest` 撞名劫持
> （§3.D2 / A5）。CTF 路径基线已于 A6 建立（§1.3 / §8.7），
> 故"A2/A3 无法验证"这一结论**不再成立** —— 现在可以做前后对照跑。

### 2026-09-11 · A3 完成（P0.5.1，第一处代码改动）

`run_agent.py:9222` `_run_solver_turn()` 的 `AIAgent(...)` 增加
`skip_background_review=True`（+8 行含注释）。

- **只加这一个 flag**，按 `agent/agent_init.py:695-702` 的说明：它本身就是
  覆盖两条 review 路径的单一开关。
- **不加 `skip_memory=True`**：不带来额外收益，却会顺带关掉外部 memory
  provider（`agent_init.py:1898`），而 `ctf_solve` toolset 刻意保留了
  `memory` 工具（`toolsets.py:646-650`，注释写明"回合后自省触发依赖"）。
- 验证：`python3 -m py_compile run_agent.py` 通过；`AIAgent.__init__`
  在 `run_agent.py:513` 确有该参数。

### 2026-09-11 · A2 完成（P0.5.2，死配置）

`~/.fulilian/config.yaml` 移除 `compression.threshold_tokens: 400000`，
原位留注释说明为何是 no-op。备份：`config.yaml.bak-20260911-200734`。

**顺带做完的键名普查**（担心还有别的死键）：

| 键 | 是否接线 | 结论 |
|---|---|---|
| `threshold: 0.7` | ✅ | 128K 下生效值 0.7（不是被 floor 抬到 0.75） |
| `target_ratio: 0.4` | ✅ | 映射到 `summary_target_ratio` |
| `proactive_prune_tokens: 80000` | ✅ | 映射到同名参数 |
| `protect_first_n: 4` / `protect_last_n: 20` | ✅ | 已接线 |
| `threshold_tokens: 400000` | ❌ | **死**，已移除 |

**新增的文档错误（§3.N 同类）：** `fulilian_cli/config_defaults.py:808`
注释写 "floored at **0.75**"，而 `agent/context_compressor.py`
`_effective_threshold_percent` 用的是 `_SMALL_CTX_THRESHOLD_PERCENT = 0.60`。
实际 floor 是 **60%**，注释错。

> 附一条被证伪的假设：我曾怀疑 CTF 的 0.60 封顶会被这条 floor 抬回 0.75
> 从而失效。查证后 **floor 是 0.60**，`max(0.60, 0.60) = 0.60` —— 封顶有效，
> 该假设不成立。

### 2026-09-11 · 阻断性 bug：`solve -p` 从未进入 CTF 路径（A5，`bbf054d`）

**这是本次工作影响最大的发现。** 首次尝试跑真实 CTF 路径（A2/A3 的验证载体）
时，3 个 fixture **全部瞬间失败**，报 `HTTP 400: Format Error`，且**退出码 0**。

**排查路径（三条被证伪的假设，按序）：**
1. ~~`AIAgent._summarize_api_error` 吞掉了真实错误~~ → 打补丁后**该函数根本没被调用**。
2. ~~`httpx` 层面的请求有问题~~ → 补丁后**一个请求都没记录到**，只有
   `API call failed after 3 retries: Connection error.`
3. ✅ 改为拦截 `builtins.print` + `sys.stdout/stderr.write`，才看到真实 prompt
   是一个 **Python bool**。据此定位到 argparse `dest` 冲突。

**根因：** `fulilian_cli/subcommands/solve.py:37` 的
`-p/--print` 用了 `dest="oneshot"`，与顶层 `fulilian_cli/_parser.py:153`
的 `-z/--oneshot`（存字符串 PROMPT）**共用一个 Namespace**。子解析器覆盖后
`args.oneshot = True`（bool），`fulilian_cli/main.py:14789` 在
`args.func(args)` 派发**之前**就 `_run_and_exit_oneshot(True)` ——
`cmd_solve` 永不执行。完整后果链与修复见 §3.D2。

**修复：** `dest="ctf_oneshot"`，并在 `fulilian_ctf/cli.py:382` 保留读
`oneshot` 的回退，兼容直接构造 Namespace 的既有测试与调用方。

**已如实记录的既有失败：** `tests/fulilian_ctf/test_solve_modes.py::test_json_mode_emits_start_and_result`
在本修复后仍失败（`JSONDecodeError: Expecting value: line 1 column 2`）。
用 `git stash push -- fulilian_cli/subcommands/solve.py fulilian_ctf/cli.py`
回到 HEAD 复现 → **同样失败** → `git stash pop` 恢复。
**该失败先于本次改动存在，非本次引入**，已写进提交信息，未修（超出本次范围）。

**同批排查（F4-002）：** 全量审计其余子解析器的 `dest`/顶层撞名 —— 共 11 处，
**只有 `oneshot` 会在派发前重路由 `main()`**，其余仅影响日志详细度，属良性，未动。

### 2026-09-11 · CTF 路径基线建立（A6，`91c52d6`）

新增 `benchmarks/ctf_path_baseline.py`（纯标准库，读 work_dir 的
`usage.json` + `solver.log`，含 CPU 侧的 flag/manifest 逐字交叉校验）
+ `benchmarks/baselines/2026-09-11-ctf-path.json`。数据见 §1.3，复现命令见 §8.7。

**结果：3/3 解出，3/3 flag 与 manifest 逐字一致。** 修复正确性由此获得实证。

**本轮产生的修正：**
- §3.D2 重写：从"CTF 层从未被执行过"改为"被 argparse dest 冲突吃掉，
  根因已定位并修复"，并撤销随之而来的两条过强推论（见 §3.D2 末段）。
- §1 新增 §1.3 CTF 路径基线表（C1–C11），与 §1.1/§1.2 的 chat 路径并列。
- §8 新增 §8.7 复现命令，含"必须复制 fixture 到 /tmp"这一非显然前提。

**三条读数直接对应后续优化项：**
- C4 prompt:补全 = **68 : 1** → P0.1（工具输出落盘）的靶子。
- C8 工具发现开销 **16.3%**（7/43 次往返纯为问工具签名）→ P0.2 / P7。
- C9 shell : read_file = **8 : 15** → P1 / C2（分批工具 + 持久 shell）。

**采集器已知局限（写在文件 docstring 里）：**
`solver.log` 的 API 计数**低于** `usage.json`（crypto-rsa-01：10 vs 24，重试与
压缩轮不落日志）→ 跨字段比较以 `usage.json` 为准；`solver.log` 每次运行被
`"w"` 覆盖 → 基线必须当次跑完立刻采集；**只看过程不看能力** —— 要回答
"agent 变聪明了吗"需要 holdout 真题。

**仍未解决（已记录，未处理）：** CTF API 路径**无读超时**（实测一次挂起：
CPU 冻结、`ESTAB ... Send-Q 4290`、最后活动 20:27:38 停在 API call #7）——
长跑有静默卡死风险，属 P0 邻域。

### 2026-09-11 · A7：C4 归因重测 —— 推翻自己的初判，优先级重排

**触发：** 准备动手做 P0.1（工具输出落盘）前，先去核实它的触发条件在基线里
到底出现过没有。**结果是 0 次** —— 于是回头重测了 C4 的成因。

**测到的三件事：**
1. `OUTPUT TRUNCATED` / `persisted-output` 在三个 fixture 里**各 0 次**。
   截断与落盘机制从未触发 → P0.1 在这批 fixture 上**零效果**。
2. prompt 全程只增长 4.3–6.8K（9.5K → 13.8K），**固定开销占累计的 68.5–79.0%**。
3. CTF 工具集 14 个工具、schema 22,942 字符；其中 `memory`(3,176) +
   `skill_manage`(2,455) = **5,631 字符/次调用**。

**推翻的结论：** §1.3 初版写「68:1 是 P0.1 要打的靶子」—— **错**。
那 62 万 token 主要不是历史膨胀，而是**每次调用原样重发的 ~9.5K 基线**。

**自我更正的第二处：** A3 条目里我以「toolset 刻意保留了 memory」为由说明
为何不加 `skip_memory=True`。不加 flag 仍是对的，但**遗漏了**：保留这两个工具的
**唯一理由**就是被 A3 关掉的那条 fork（`toolsets.py:637-647`）。
→ 新增 **P0.5.4**，并把它标为当前 ROI 最高的一项。

**对计划的结构性影响：**
- **优先级重排：** P3/P7（砍固定开销）与 P0.5.4 > P0.1。原顺序把 P0.1 排第一，
  是建立在"钱花在重发历史"这个**未经验证的假设**上的。
- **基线的适用边界收窄：** 这 3 题**验证不了 P0.1**（机制不触发）。
  要验证 P0.1 必须有难题 holdout（长扫描 / 反编译转储 / 爆破日志）。
- **§1.4 记录了两条可复现的测量方法**（逐次 `📊 Request size` 抽取、
  `get_tool_definitions()` schema 计量），后续改动可直接复用。

**方法论备注：** 这次是"动手前先验证触发条件"，而不是"改完再测效果"。
如果直接按原计划写 P0.1，会得到一个**无法被现有基线证伪、也无法被证明**的改动。

### 2026-09-11 · A9：P0.5.4 实施 + 对照跑（首项 P0 落地）

**动机（来自 A7）：** `ctf_solve` 里的 `memory` + `skill_manage` 的唯一用途是让
回合后自省 fork 能触发，而 A3 已把那条 fork 关掉；此前的基线跑里这两个工具
**43 次工具调用中调用 0 次**。

**改动：**
- `toolsets.py` —— `ctf_solve` 工具表删两行；注释块重写为「⚠️ 耦合」说明，
  写明**若重新开启 background_review 必须把名字加回，否则静默失效**。
- `run_agent.py:9222-9232` —— 修正 A3 注释里已失效的一句
  （原文写"ctf_solve toolset 刻意保留了 memory 工具"，改动后自相矛盾）。
- `tests/test_toolsets.py` —— 原有的 3 个测试**锁的正是被推翻的结论**
  （断言这两个工具必须在场）。没有删掉它们，而是**翻转成双向耦合断言**：
  `test_solver_spawn_and_toolset_are_coupled` 同时检查
  `_run_solver_turn` 的 `skip_background_review=True` 与工具表内容，
  两个方向任一被单独改坏都会失败。这比锁单边更贴近真正的不变量。

**验证：**
- 单测：`tests/test_toolsets.py` 29 项 ✓；`test_skip_background_review.py`
  + `tests/fulilian_ctf/` 683 项 ✓。
- 对照跑（同协议 3 题）：3/3 解出、flag 与基线逐字一致；
  **首屏 prompt 9,460/9,525/9,454 → 6,297/6,290/6,294**，即
  **−3,160 / −3,235 / −3,163 tokens/次调用**，三次高度一致。
- 日志侧确认：`Final tool selection` 17→15，`Loaded` 14→12。

**一个比预估大一倍多的连带效应（A9 的主要发现）：**
预估只算了两个 schema（1,408 tok）。实测省 **3,186 tok/次**，因为是**三处**
按 `valid_tool_names` 门控的内容一起消失 —— 见 §1.6。其中最大的一块是
**10,192 字符的技能索引**，而基线日志的工具表里**既无 `skill_view` 也无
`skills_list`**，即那份索引列了 205 个技能、agent 却没有任何工具能打开 ——
**够不着的清单，纯噪声**。这条已推广为 P3/P7 的评估方法（§10 下一步表下注）。

**未归因的部分（n=1，不许当成结论）：** api_calls 48→31（crypto-rsa-01 从
24 掉到 8）、input tokens −37.6%。三个 fixture 各只跑一次，无法区分
"提示更干净→路径更直"与随机性。**已列为下一步第 5 项：n≥3 重跑。**

**顺带的用户侧问题（尚未处理）：** `~/.fulilian/config.yaml` 里用户手写的 5 条
「CTF 工作纪律（每次任务都生效）」**在 CTF 路径上不生效** —— 该配置键
（`agent.system_prompt`）的唯一读取点是 `fulilian_cli/personality.py:160`，
调用者只有 `cli.py` / `gateway/run.py` / `tui_gateway/server.py`，
**CTF 路径不在其中**；`agent_init.py` 无该读取；`system_prompt.py:781` 要求
`system_message is not None` 才追加，而 CTF 路径传 None。
用户写下的「大输出先落盘」正是 P0.1 的手工版 —— 它没生效。
→ 需决定：把该配置接进 CTF 路径，还是改写进 `_build_ctf_system_prompt()`。
**未向用户报告，也未实施。**

### 2026-09-11 · A10：用户 CTF 工作纪律接入求解路径（`5ec2cc5`）

**承接 A9 末尾那条"顺带的用户侧问题"。** 用户选择接入 config（而非把 5 条
纪律硬编码进 `_build_ctf_system_prompt()`）—— 前者让纪律继续由用户自己维护，
后者会把用户内容拷进仓库、从此两边漂移。

**改动：** `run_agent.py` 新增 `_resolve_ctf_user_overlay()`，由
`_build_ctf_system_prompt()` 追加在认知架构之后。三个刻意的选择：

1. **委托共享解析器，不自己读 `agent.system_prompt` 键。**
   overlay 解析的 single-owner 是 `fulilian_cli.personality.resolve_ephemeral_system_prompt`
   （`fulilian_cli/config.py:3317` 只是转发壳）。自己读键会造出第二个所有者，
   而这条链上已经有"人格覆盖 `system_prompt`"的语义 —— 重复实现必然漂移。
   `FULILIAN_EPHEMERAL_SYSTEM_PROMPT` 环境变量优先，与 chat 路径同语义。
2. **放在末尾，并写明"冲突时以本节为准"。** 用户显式写的纪律优先于通用架构。
3. **解析失败返回空串。** overlay 是增强项，缺了不该中断解题。

**验证：**
- 合并结果 **1,466 字符**（架构 1,037 + overlay 429，与 `wc -c` 实测的 430 吻合）。
- 真跑 `misc-morse-01`：解出 `flag{morsecodebegin}`，flag 正确；
  **首屏 6,692 tokens vs 无 overlay 的 6,290/6,297/6,294 = +395**，
  与 429 字符的 CJK overlay 吻合 → overlay 确实送达求解器。
  （判据用 token 数而非 `grep ctf-notes.md` —— 日志把 ephemeral prompt
  **截断**成 `'…（4 阶段循环）\n\n你正在以…\n\n### PHASE...' (not saved to
  trajectories)`，grep 是行式匹配，只能看到第一行。这个坑值得记：**不要用
  grep 判断 ephemeral prompt 的内容是否完整**。）
- 单测：新增 `tests/fulilian_ctf/test_ctf_system_prompt_overlay.py` 6 项 ✓；
  `tests/test_toolsets.py` 29 项 ✓（共 35 项）。

**不损伤提示缓存：** overlay 在 `_build_ctf_system_prompt()` 里构建**一次**
（`run_agent.py:9438` 调用点），整轮求解内恒定，只是把缓存前缀加长 429 字符，
不改变命中率 —— 符合 AGENTS.md「提示缓存是神圣的」这一约束。

**A10 暴露的两个未决问题（都不是本改动的回归，但都由它揭示）：**

1. **纪律送达了，但没被遵守** —— 该次运行**没有生成 `ctf-notes.md`**。
   规则 1「发现即落盘」送达后模型未照做（可能是 easy 题上判断不值得，
   也可能是措辞太软）。**n=1，且 easy 题本来就不需要笔记，暂不归因**；
   需要难题 holdout 才能判断是措辞问题还是场景问题。
2. **规则 1 的「并同步 memory」现在无法满足** —— 用户在 config 里写的是
   「写 ctf-notes.md，**并同步 memory**」，而 A9/P0.5.4 已把 `memory` 工具
   移出 `ctf_solve`。这条指令现在是**不可执行**的。两条出路：改 config 文字
   （去掉"并同步 memory"），或把 `memory` 加回（代价 3,186 tok/次）。
   **决定权在用户。**

→ 这两个问题共同指向同一件事：**A10 修好了"送达"，但"遵守"没有被测量。**
   在难题 holdout 就位前，不应再对 CTF 提示词做措辞调优 —— 没有能证伪它的
   观测手段（与 §1.4 对 P0.1 的判断同理）。

---

### 2026-09-11 · 难题 holdout 建成，以及一次真实的基准污染（`9f1caf1`、`7603a78`）

§10 第 4 条"没有难题 holdout"已解除。三道题，**各自盯一个不同的能力维度**
（不是同一维度的三个样本），物理隔离在 `benchmarks/fixtures-hard/`：

| fixture | 维度 | 语料 | 参考解步数 |
|---|---|---|---|
| `misc-bigscan-01` | 工具输出纪律 | 4,001,611 B / 110,089 行扫描输出，命中行埋在 **65% 深度**且不含关键字 | 4 |
| `reverse-obfchain-01` | 调用图推理 | 3,514 行反编译产物，42 个 `sub_*` + 480 个 `noise_*`，只有一条链从 `main` 可达 | 6 |
| `forensics-brutelog-01` | 交叉判断 | 3,320,147 B / 27,250 行 auth.log，9,004 条 Accepted 里**只有 1 条**来自内网段之外 | 5 |

语料**不入库**：由固定 seed 的 `make_data.py` 确定性生成，任何人可复现逐字节
相同的语料 —— 比入库一个 4 MB 二进制更硬（能独立验证题目没被偷换）。
`ctf_hard_run.sh` 在 solve 之前先跑参考解自证，解不出就中止：一次"解出率 0"
的跑批无法区分「agent 不行」和「fixture 坏了」，基准自己错了所有结论都是假的。

**这批 fixture 抓到的第一个问题不是 agent 的，是跑批器自己的。** 初版 runner
把 `solve_reference.py` 和 README 一起 `cp` 进了 solve 工作目录，agent 于是
**主动去偷**。这不是理论风险，是日志里的原话：

```
🤖 Assistant: Let me re-verify the base64 decoding and check the reference
              common module for any flag extraction logic
  📞 Tool 1: terminal  → {"output": "file not..."}      # 找不到
  📞 Tool 2: terminal  → {"output": "Tracebac..."}      # 异常
  📞 Tool 3: search_files(pattern="solve_r...") → {"total_count": 0}   # 0 命中
```

三次全败，flag 仍是真的解出来的 —— 但**全败纯属运气**（它搜错了路径），
不是设计保证。一次成功偷到就是满分假象。修法：自证移进 `$OUT/_selfproof/$id`，
solve 目录只留题面 + 语料，并在 solve 前加 `find` 硬闸（出现 `solve_reference*`
就拒绝开跑，不靠"记得别 cp"）。

**污染批是乐观偏差，有数字佐证：** 即使一次都没偷到，光是**看得见**参考解
文件名，行为就明显不同 —— 污染批 798,612 token / 重复率 21–35%，
干净批 **1,443,545 token / 重复率 37–60%**，几乎翻倍。

**干净基线（3/3 解出，3/3 flag 与 manifest 逐字一致，尝试次数全 1）：**

| fixture | api_calls | 参考解步数 | 倍数 | 总 token | shell:read | 缓存命中 |
|---|---|---|---|---|---|---|
| `misc-bigscan-01` | 18 | 4 | 4.5× | 301,822 | 17:2 | 81.6% |
| `reverse-obfchain-01` | 26 | 6 | 4.3× | 851,311 | 12:12 | 81.4% |
| `forensics-brutelog-01` | 12 | 5 | 2.4× | 290,412 | 15:2 | 72.8% |

合计 api_calls 56 / 工具 78 / 工具发现开销 6 次（7.7%）/ shell:read = 44:16。

**三个可直接使用的结论：**

1. **A10 遵守率 3/3** —— 三题全部生成 `ctf-notes.md`（污染批是 2/3）。§10 里
   「送达已证明、遵守未证明」这一条**在难题上已被证明**，不再是未决项。
2. **overlay 不伤缓存（n=3）** —— 缓存命中 81.6 / 81.4 / 72.8%，与无 overlay 的
   easy 基线（81.7 / 86.0 / 87.6）同量级。此前 n=1 时观察到的 69.0% 是前 3 次
   调用的冷启动（缓存读取恰好 4,096 = 一个块），不是 overlay 的系统性代价。
3. **这三题对当前 agent 不够难** —— 3/3 一次通过意味着**天花板效应**：
   以它为基线去验收 P0.1 等优化，测不出提升。真正可用的是
   `api_calls / solve_reference_steps` = **2.4–4.5×** 这个"路径不经济"信号 ——
   题解得出，但绕了 2–4 倍的远路。这才是后续削减工作的靶子。

---

### 2026-09-11 · 2b：把"路径经济性"落地为可采指标，并补一道更硬的探针题

上面第 3 条不是结论，是待办。2b 是它的实施，分两步，外加一次意外发现。

**第一步（`c0746cd`）—— 经济性提为一等指标，改的是采集器不是题。**
`ctf_path_baseline.py` 直接消费 manifest 的 `solve_reference_steps`，出
`×参考解` 列与汇总行。指标定义：

```
ref_multiple = api_calls / solve_reference_steps
```

选它的理由是**它是连续量**。解出率在难题上会饱和（3/3 就没有下降空间），
而绕远路的倍数不会 —— 任何一次减冗余都能在它上面看到位移。分母取"参考解的
最少步骤数"是因为它同时是难度的代理：分子里的多余往返正是 P0.1 类改动的靶子。
老 manifest 没有该键时整体退化为 `—` 而不是报错，unit 那 25 题照常可用。

**第二步（`ce3cb11`）—— 加 `misc-chunkconcat-01`，压在 P0.1 路径上更硬的一段。**
已有三题里 bigscan 只需**一次** grep 就能命中（输出纪律只考了"别整读"）。
新题把这条堵死：2,949,698 B / 39,382 行的传输日志，目标通道 1,379 块**乱序**
散落，`grep chan=07` 的过滤输出本身就有 **103,269 B —— 超截断线 5.2×**。
即"过滤对了也读不完"，必须落盘再处理。参考解 5 步。

生成器 `make_data.py` 自己带四条断言，这是本题可用的前提（基准自证，不是信任）：

| 断言 | 挡住的退化 |
|---|---|
| 日志内字面 `flag` 出现 0 次 | 答案直接躺在语料里，难度归零 |
| 目标通道过滤输出 > 20,000 B | 退化成 bigscan（一次 grep 就够），失去探针意义 |
| 按 `off=` 排序拼接解码后含 flag | 生成器自己错了 → 参考解也解不出，跑批无法归因 |
| **按出现顺序**拼接解码后**不含** flag | "乱序"这层难度是假的（假难度比没难度更坏） |

最后一条是这道题的核心：它保证"必须按流内偏移重排"这件事**是被验证过的**，
而不是题面里一句自称。

**跑批（v2，4 题）—— 4/4 解出、4/4 flag 逐字一致、尝试次数全 1。**
经济性 58 api_calls / 20 参考步数 = **2.9×**。新题本身 15 api / 5 步 = 3.0×。

**但单次跑批不足以支撑归因：** v1（3 题）api 56 / 3.7×，v2（4 题）api 58 / 2.9×，
其中 `reverse-obfchain-01` 从 26 掉到 14 api。同一 fixture、同一代码，位移近半，
**这是采样方差而非改动效果**。结论：经济性可以做主指标，但验收任何改动仍需
n≥3；单点差异一律不当证据（与 §1.4 对 P0.1 的判断同源）。

**意外发现 —— 运行日志落在 agent 地盘里，被 agent 自己覆盖了。**
`misc-chunkconcat-01` 那一跑数据不可能：解出 flag、api_calls 15，工具面却全是 0
（工具 0 / 重复率 0% / 延迟 None）。0 看着像满分成绩，查下去才发现
`solver.log` 只有 14 行，内容是 `# Solution / ## Method / ## Flag` ——
**agent 用 `write_file` 把运行日志覆盖成了一份解题报告**，就发生在跑的过程里。

这与 `7603a78` 那次污染**是同一类缺陷**：基准基础设施落在 agent 可写的地盘。
偏的方向不同而已 —— 那次可能造出**假阳性**（偷到就是满分假象），
这次造出**假高效**（数据没了，看起来却像零浪费）。

已做的（`5d55fe7`）是**检测与报警**，不是根治：采集器出 `log_issue`
（`missing` / `overwritten` —— 判据是运行日志必然含 `Making API call` 行），
不可信行的工具面四列置 `—` 而非 0，行名加 ⚠️，汇总里单列报警并把工具总数标注为
**下界**。关键点在于**缺失必须看得见缺失**：把它打成 0，等于在报告里写下
"这题一次工具都没调、零重复、零延迟"这种不存在的事实。

根治（把运行日志移出 work_dir）是独立改动，**未做**，见 §10 第 3 条。

**2b 留下的两件事：** 经济性指标需 n≥3 采样才有验收力；`solver.log` 的写位置
需要改到 work_dir 之外 —— 在那之前，每次跑批完必须立刻采集，且要核对
⚠️ 标记。

## 10. 当前状态

**分支 `ctf-opt`（未推送任何内容到 origin）。**

| 类 | 项 | 位置 |
|---|---|---|
| 代码 | **A10 config overlay 接入 CTF 路径** | `run_agent.py` `_resolve_ctf_user_overlay()` + `_build_ctf_system_prompt()` |
| 测试 | A10 overlay 回归锁（6 项） | `tests/fulilian_ctf/test_ctf_system_prompt_overlay.py` |
| 代码 | **A9/P0.5.4 删 `memory`+`skill_manage`** | `toolsets.py:625-642`（工具表 + 耦合说明） |
| 代码 | A3 `skip_background_review=True` | `run_agent.py:9222`（+8 行） |
| 代码 | A5 `dest="ctf_oneshot"` + 回退读 | `fulilian_cli/subcommands/solve.py:43`、`fulilian_ctf/cli.py:382` |
| 测试 | A9 耦合回归锁（双向断言） | `tests/test_toolsets.py` `TestCtfSolveToolset` |
| 配置 | A2 删死键 `threshold_tokens` | `~/.fulilian/config.yaml`（仓库外，已备份） |
| 基准 | A4 chat 路径采集器 + 基线 | `benchmarks/process_metrics.py`、`baselines/2026-09-11-ctf-chatpath.json` |
| 基准 | A6 CTF 路径采集器 + 基线 | `benchmarks/ctf_path_baseline.py`、`baselines/2026-09-11-ctf-path.json` |
| 基准 | **A9 对照跑基线（改动后）** | `baselines/2026-09-11-ctf-path-p054.json` |
| 基准 | **难题 holdout（4 题 / 4 个维度）+ 跑批器** | `benchmarks/fixtures-hard/`、`manifest-ctf-hard.yaml`、`ctf_hard_run.sh` |
| 基准 | **难题 holdout 干净基线** | `benchmarks/baselines/2026-09-11-ctf-hard-holdout.json` |
| 基准 | **路径经济性指标（C1b，消费 `solve_reference_steps`）** | `benchmarks/ctf_path_baseline.py` `analyze()` / `print_aggregate()` |
| 基准 | **探针题 `misc-chunkconcat-01`**（4 题 holdout） | `benchmarks/fixtures-hard/misc-chunkconcat-01/` |
| 基准 | **v2 跑批基线（4 题，含经济性）** | `benchmarks/baselines/2026-09-11-ctf-hard-holdout-v2.json` |
| 基准 | **运行日志可信性检测（`log_issue`）** | `benchmarks/ctf_path_baseline.py` `analyze()` / `print_table()` |
| 代码 | **运行日志镜像（根治 §10 第 3 条）** | `fulilian_ctf/solver.py` `SOLVER_LOG_MIRROR_ENV` / `tee_solver_log` / `_TeeStream` |
| 测试 | 镜像日志回归锁（4 项，含"agent 覆盖后镜像仍完整"） | `tests/fulilian_ctf/test_solver_log_tee.py` |
| 文档 | 本计划书 | `docs/ctf-agent-optimization-plan.md` |

**已验证：** A5 —— 修复前 3/3 瞬间失败（HTTP 400，退出码 0）；修复后
**3/3 解出、3/3 flag 与 manifest 逐字一致**（§1.3）。

**已验证：** **A9/P0.5.4** —— 对照跑 3/3 解出、flag 逐字一致，
**首屏 prompt 每题一致地降 3,160–3,235 tokens**（§1.6）。
`tests/test_toolsets.py` 29 项、`tests/agent/test_skip_background_review.py`
+ `tests/fulilian_ctf/` 683 项全绿。

**已验证：** **A10**（`5ec2cc5`）—— 合并 prompt 1,466 字符；真跑
`misc-morse-01` 解出且 flag 正确，首屏 +395 tokens 证实 overlay 送达（§9 A10）。
**送达与遵守均已证明** —— 难题 holdout 上 **3/3 生成 `ctf-notes.md`**
（easy 单点上曾是 0/1，现已被 n=3 覆盖）。缓存代价也已排除：runs 命中
81.6/81.4/72.8%，与无 overlay 基线同量级。

**已验证：** **无测试回归** —— `tests/fulilian_ctf/ + tests/run_agent/`
在本分支 `9f1caf1` 为 13 failed / 2524 passed，在 HEAD `1b8a500` 为
13 failed / 2518 passed：**失败集合逐条一致（13/13）**，多出的 6 passed
正是 A10 的新增测试。两边各有 10 次同一个环境原因
（`The 'anthropic' package is required`），与本分支改动无关。

**已验证：** **2b —— 路径经济性已可采（`c0746cd`）**，新探针题
`misc-chunkconcat-01` 已入 4 题 holdout（`ce3cb11`），v2 跑批 **4/4 解出、
4/4 flag 逐字一致、尝试次数全 1**，经济性 **2.9×**（58 api / 20 参考步数）。
新题自带的四条生成器断言全过 —— 尤其"按出现顺序拼不出 flag"这条，把
"必须按偏移重排"从题面自称变成了被验证的事实。
**但单次采样不能归因：** v1 3.7× / v2 2.9×，`reverse-obfchain-01` 从 26 掉到
14 api，同一代码的位移近半 → 经济性可用作主指标，验收仍需 **n≥3**。

**仍未验证：** A2/A3 的**效果**。它们只作用于 `mode="ctf"`，现在该路径能跑了，
但"关掉回合后背景审查"与"删掉死配置"各自省了多少，需要**同 fixture 前后对照**，
而当前只有修复后的单点数据（无修复前基线可采——那时根本跑不起来）。
→ 可行的做法：在下一批改动前，对 A3 做一次 `skip_background_review=False`
的对照跑，用 C3/C5（api_calls / 总 token）差分。
→ **holdout 已可用作对照地形**，但见第 4 条：4 题 4/4 一次通过，要用它们做
差分得靠 api_calls / 工具往返这类连续量，不能靠解出率（没有下降空间）。
→ 2b 已把这条连续量做出来了；**缺的是 n≥3 的采样，不是指标。**

**阻断性发现已清除：** §3.D2 的 argparse `dest` 冲突（`bbf054d`）。
在此之前，"CTF 层是否存在缺陷"这个问题在观测上无法回答——每次
`solve -p` 都在无声地跑另一条路径并以退出码 0 结束。

**已知未处理（按优先级）：**
1. **CTF API 路径无读超时** —— 实测挂死一次（§9）。长跑静默卡死风险。
2. `test_json_mode_emits_start_and_result` **先存的失败**（HEAD 上同样失败）。
3. **运行日志落在 agent 可写的地盘里，被 agent 自己覆盖** —— 原描述
   「跑完不立刻采集就丢数据」**低估了它**。真实形态在
   `misc-chunkconcat-01` 上实测到了：agent 用 `write_file` 把 `solver.log`
   覆盖成解题报告，**就发生在跑的过程中**，跑批完立刻采集也拿不到。
   → 检测（`5d55fe7`）：采集器出 `log_issue`，不可信行工具面置 `—` 并打 ⚠️，
   汇总把工具总数标注为下界 —— 不再把"数据没了"静默读成"零浪费"。
   → **根治（镜像日志）**：`tee_solver_log` 支持 `FULILIAN_SOLVER_LOG_MIRROR`，
   同一份字节额外写一份到指定路径；跑批器把它指到 `$OUT/_mirror/`（solve 目录
   之外）。**刻意只在增不改**：`work_dir/solver.log` 原地保留，dispatcher 的
   增量扫描、replay/writeup、racer / multi_agent 的子目录证据全部不受影响 ——
   移动日志会打断这些消费者（`dispatcher.py:1005,1096` 按字节偏移追增长）。
   采集器加 `--mirror-dir`，有镜像就优先采信，并**单独**报 work_dir 那份是否
   被扰动（测量有效、产物损坏，两件事分开说）。
   → **仍存在的边界**：只覆盖默认 solve 路径（`tee_solver_log`）；
   `--race` / `--multi-agent` 各自开日志，未接镜像。环境变量不设时行为不变。
4. ~~**没有难题 holdout**~~ —— **已解除**（`9f1caf1`），**2b 已实施**
   （`c0746cd` 经济性指标 + `ce3cb11` 第 4 题 + `5d55fe7` 日志可信性）。
   当前 4 题，v2 跑批 4/4 一次通过 → **天花板效应仍在**，但可用信号已经落地：
   `ref_multiple = api_calls / solve_reference_steps`，v2 为 **2.9×**。
   → **剩余待办不是加题，是 n≥3 采样**（单跑方差已实测：3.7× vs 2.9×）。
5. ~~**`config.yaml` 规则 1 的「并同步 memory」不可执行**~~ —— **已关闭**
   （用户 2026-09-11 选择改 config 文字）。「，并同步 memory」已删，
   overlay 429→418 字符，备份 `~/.fulilian/config.yaml.bak-20260911-rule1`。
   A10 的遵守率也已在难题 holdout 上证明（3/3 生成 `ctf-notes.md`）。

**下一步（已按 §1.4 重排）：**

| 顺序 | 项 | 理由 | 状态 |
|---|---|---|---|
| 1 | ~~**P0.5.4** 删 `memory`+`skill_manage`~~ | 实测 **−3,186 tok/次调用**（比预估的 1,408 大一倍多，见 §1.6） | **✅ 完成** |
| 0 | ~~**A10** config overlay 接入 CTF 路径~~ | 用户手写的纪律此前静默失效；已在用户选择下实施 | **✅ 完成** |
| 2 | ~~**难题 holdout（长扫描 / 反编译转储 / 爆破日志）**~~ | 已建成并跑通（`9f1caf1`）；A10 遵守率据此证明 3/3 | **✅ 完成** |
| 2b | ~~**路径经济性提为主指标 + 加更硬的探针题**~~ | 已实施：`c0746cd` 指标 + `ce3cb11` 第 4 题 + `5d55fe7` 日志可信性；v2 4/4 解出、经济性 2.9× | **✅ 完成** |
| 2c | **经济性采样 n≥3** | 单跑方差已实测（v1 3.7× / v2 2.9×，obfchain 26→14 api）—— 不做 n≥3，经济性就只是"有指标"，不是"能验收" | **新增（由 2b 派生）** |
| 2d | ~~**`solver.log` 移出 work_dir**~~ | 已实施为**镜像日志**（只增不改）：`FULILIAN_SOLVER_LOG_MIRROR` + 采集器 `--mirror-dir`。移动会打断 dispatcher 按偏移追增长的消费者，故取镜像 | **✅ 完成** |
| 3 | **A3 对照跑**（`skip_background_review=False`） | 拿 A3 的净效果（P0.5.4 已单独验收） | 待做 |
| 4 | **P3/P7** 砍固定开销（terminal schema 3,281 字符最肥） | 固定开销是主体；§1.6 证明"够不着的工具"是同一类浪费 | 待做 |
| 5 | **P0.1** 工具输出落盘 | 只在难题上见效 —— 且需先解决 2b 的天花板效应 | 降级 |
| 6 | **重跑 P0.5.4 对照（n≥3）** | 首屏 −3,186/次是确定的，但 api_calls 48→31 是 n=1，不能归因 | 待做 |

> **顺序说明（A10 之后调整）：** 难题 holdout 从"P0.1 的前置"提升为**全局
> 第二项**。原计划里它只是 P0.1 的门票；A10 之后可以看到，它同样是 A10
> 「送达已证明、遵守未证明」的唯一解药，也是后面所有提示词层改动的判据。
> 继续在只有 3 道 easy 题的基线上做改动，会陷入"每次都能测出 token 变化、
> 永远测不出能力变化"的状态 —— 而用户的原始诉求正是**难题能力**。
>
> **第二项已完成，但它交付的不是"够用的判据"，而是"判据还不够难"。**
> 三题 3/3 一次通过意味着现在的判据同样测不出能力变化（天花板效应）。
> 这一步的真实收获是三条：A10 遵守率 3/3、overlay 不伤缓存（n=3）、
> 以及一个**新的可测信号** —— `api_calls / solve_reference_steps` 2.4–4.5×。
> 下一步要么把题加难到会失败，要么直接以路径经济性为主指标。
>
> **2b 选了后者，并已落地：** 经济性提为一等指标（`c0746cd`），第 4 题
> `misc-chunkconcat-01` 入 holdout（`ce3cb11`），v2 跑批 4/4 解出、经济性 2.9×。
> 天花板效应仍在（4/4 一次通过），但**靶子换成了连续量** —— 剩下的不是把题
> 加难，而是把采样做到 n≥3：单跑方差已实测到 3.7× vs 2.9×。

> **§1.6 的一般化教训（供 P3/P7 复用）**：删一个工具名省的不只是它的 schema。
> 任何按 `valid_tool_names` 门控的引导块 / 索引清单会**一起**消失。所以 P3/P7
> 评估"砍某个工具值不值"时，不能只算 schema 字符数，要先 grep
> `"<工具名>" in agent.valid_tool_names` 找出所有门控点，把连带消失的内容算进去。
> 反过来这也提供了机会：**某些体积很大但够不着的注入块，可能只需要删一个
> 从未被调用的工具名就能一并清掉**（技能索引 10,192 字符就是实例）。


> P0.1 的具体形态已查清，实施时不必重新调研：
> `tools/tool_result_storage.py` 的 `maybe_persist_tool_result`（Layer 2，
> 落 `$FULILIAN_HOME/cache/spillover`，24h 自动清理）**已经是**计划里想建的东西；
> 问题是 `tools/terminal_tool.py:3695` 在**工具内部**就先按 `tool_output.max_bytes`
> （用户配 20000，默认 50000）把中段**丢弃**了，而 Layer 2 的阈值是 78,643 字符
> （128K 窗口）。**20K 的刀比 78K 的闸早 4 倍落下，并且不带路径** ——
> Layer 2 因此永远拿不到超限的输入。所以 P0.1 不是"新建落盘"，而是
> **让工具内截断改走已有的落盘原语**（或抬高工具内阈值让 Layer 2 接手）。
> 但在 easy fixture 上这条路径**从不触发**（§1.4），所以先做上面三项。
