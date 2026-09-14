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

> **2026-09-12 按新口径重测（n=3，4 道难题）：−3,305 tokens/调用** ——
> 配对量首屏前缀，12/12 全为正，跨度 35（1.1%）。与上表的 −3,186 差 119（3.7%），
> **这 119 归属未查**（上表是 21:09 的树、3 道 easy 题；重测是当前树、4 道难题）。
> 两种口径都不影响结论，但**要精确报账必须在同一棵树、同一题集上量**，
> 不能拿两次不同来源的读数相减。见 §9「A3+A9 对照跑结案」第四节。

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
（**2026-09-14 ⑨ 勘误：** 这两个数字采自 chat 路径 —— `delegate_task` 根本不在
`ctf_solve` 工具面里，CTF solver **物理上无法委派**；CTF 路径上的"从未发生"
是原语缺席的必然，不是"模型不自觉"的行为证据。详见 §9 ⑨。）

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

**P0.2 · solve-state 由 runtime 维护，不由模型维护** ✅ **代码已完成 + 两轮 A/B 无收益（2026-09-14，见 §9 ⑤）——env 门控默认关，机制保留，重估需重复推导实锤**

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

**P0.5.3 · 重新评估 `_cap_ctf_compression_threshold` 的 0.60** ✅ **结案（2026-09-14）：本机制下不可测量，维持 0.60**

- **为什么：** 它在用"**更频繁地压缩**"来应对"长解题轨迹"，而压缩恰恰是**丢数据 + 破缓存**的源头 —— **方向是反的**。
- **注意：** 这一条是**推断，不是代码注释的观点**。建议先做小样本对照（0.60 vs 0.75）再定。
- **前提：** 只有在 P0.1 落地后才应该提高阈值（否则删得更多）。
- **已验证的前提：** 该 0.60 封顶**确实生效**（曾怀疑被 `_SMALL_CTX_THRESHOLD_PERCENT`
  这条 floor 抬回 0.75 从而失效 —— 查证后 floor 就是 0.60，`max(0.60, 0.60) = 0.60`，
  假设不成立，见 A2 条目）。
- **结案（§9 ⑦）：** cap 是 `min(ratio, cap)` 的**绝对上限**语义；把 0.60 提到 0.75
  只是把自然触发点 600K→700K 平移，而跑批峰值 ~32K、30 步上限下永远到不了 600K
  —— 自然 regime 里 A/B 无可分辨项；CTF_CONFIG_EXTRA 强制 regime 里 `min()` 直接
  把两者压成同一值。**0.60 vs 0.75 在现有机制与工作负载下测不出差异**，维持 0.60。
  重估条件：出现 ≥600K 峰值请求的轨迹。

- **问题：** 它在用"**更频繁地压缩**"来应对"长解题轨迹"，而压缩恰恰是**丢数据 + 破缓存**的源头 —— **方向是反的**。
- **注意：** 这一条是**推断，不是代码注释的观点**。建议先做小样本对照（0.60 vs 0.75）再定。
- **前提：** 只有在 P0.1 落地后才应该提高阈值（否则删得更多）。
- **已验证的前提：** 该 0.60 封顶**确实生效**（曾怀疑被 `_SMALL_CTX_THRESHOLD_PERCENT`
  这条 floor 抬回 0.75 从而失效 —— 查证后 floor 就是 0.60，`max(0.60, 0.60) = 0.60`，
  假设不成立，见 A2 条目）。

**P0.5.4 · 从 `ctf_solve` 工具集删掉 `memory` 与 `skill_manage`** ✅ **已完成（A9，`1b8a500`）**

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

**P1.1 · 提供 `run_script` / `batch` 工具** ✅ **已完成（2026-09-14，见 §9 ④）**

- **改成什么：** 一次跑 N 条命令或一个 Python 脚本，返回收敛后的结果。
- **为什么：** §1.2 —— 模型只做到 1.12 次/轮，说明 `PARALLEL_TOOL_CALL_GUIDANCE` 那句劝说**没有生效**。**得靠工具形态，不能靠劝说。**
- **预期效果：** 348 次调用可压到 ~20 次。

**P1.2 · 持久 shell + 持久 cwd** ✅ **探针结案（2026-09-14，见 §9 ⑥）—— cwd 机制早已工作；实测前缀开销可忽略（84 字符/8 条命令）；原假设被推翻；持久 shell 实现推迟**

- **为什么：** `record_session_cwd` 已经存在，但模型不知道，每条命令都在重发 `cd X && T="http://..." &&` 前缀。
- **探针结论：** 假设不成立 —— 宽日志实测 8 条 terminal 命令中 5 条自带绝对路径、3 条 cd 前缀全是多行 python -c、env 重导出 0 次。真正修掉的是**描述谎言**（旧描述无条件承诺 env 持久，local 后端静默违约）与死旋钮标记（`TERMINAL_LOCAL_PERSISTENT` 收集后丢弃）。

### P2 — 让委派自动发生

**P2.1 · 规则化自动委派**

- **改成什么：** 预计输出 >N 行或耗时 >T 秒的命令，runtime 自动丢给子代理，只回摘要。
- **为什么：** §3.F（`delegate_task` 15/13,018）。不要指望模型自觉。
- **前置事实（重要）：** 子代理上下文模型是**双向隔离**的 —— 子代理拿不到父历史（`tools/delegate_tool.py:1963` 起以空消息列表构造），父只拿子代理最终总结；工具集继承是**交集**（`:1664-1728`，注释："subagent must not gain tools the parent lacks"）；`MAX_DEPTH = 1`（`:129`）；模型传的 `max_iterations` **被忽略**（配置权威）。**自动委派必须自带充分 context，否则子代理什么也做不了。**

✅ **结案（2026-09-14，见 §9 ⑨）——探针推翻"为什么"，零代码改动。**
三重证据：① `delegate_task` 不在 `ctf_solve` 工具面，§3.F 的 15 次调用全是 chat
路径，"不要指望模型自觉"在 CTF 路径上无行为证据支撑（原语缺席时 0 次是必然）；
② 失效模式体量已被 P0.1 砍掉 —— 工具内 20K 截断+落盘+指针，全部 CTF 跑批
spillover 触发 0 次，峰值 ~32K tok/请求 vs 600K 压缩线，无上下文压力可缓解；
③ runtime 强制版双否决 —— 经济上委派是第二 agent loop，压缩从不触发的 workload
上是纯开销（④ 同构）；正确性上"输出>行/耗时>秒"规则无法为双向隔离的子代理
构造任务上下文，也分不清"过程长结论短"与"父代理下一步正需要这份输出"。
**附带发现：** 用户 config 纪律第 3 条"嘈杂工作交给子代理"经 A10 **送达但不可
执行**（指令到了、原语不在 —— A2 死配置/A10 静默失效同族第三形态）。加回
`delegate_task` schema 仅 ~700 字符（描述动态拼装，无门控块连带），但无收益
场景，挂起。**重估条件：** 难题轨迹压缩真实触发（≥600K）或 spillover 反复触发、
且体量可归因"过程长结论短"类命令 —— 届时先量"加 delegate_task 进 ctf_solve
（模型可选）"这一档，runtime 强制版仍需先解决任务上下文构造。

### P3 — 砍固定开销

**P3.1 · 精简 `_FULILIAN_CORE_TOOLS`（改源码，不是改 tool_search）**

- **改哪里：** `toolsets.py:31` 的 53 个名字字面量。
- **CTF 档建议保留：** `terminal` / `file` / `code` / `web` / `vision` / `delegate` / `todo` / `verify_flag`。
- **去掉：** `computer_use`(6.2KB) / `tts`(1.9KB) / `browser-use`(3KB) / `session_search`(3.2KB)。
- **预期效果：** 45.9 KB → **~15 KB**。

**P3.2 · 静态引导按模式门控** ✅ **已作为 A9 的副产品达成（2026-09-14 复核）**
- **原方案：** `agent/system_prompt.py:341 build_system_prompt_parts`（`stable` 层组装处，`:386-769`）。去掉 `KANBAN_GUIDANCE` / `TELEGRAM_RICH_MESSAGES_HINT` / `MEMORY_GUIDANCE` / platform hints。
- **实际：** A9 删除 memory/skill_manage 工具名时，`valid_tool_names` 门控连带使这些引导块（以及 skills 索引）在 CTF 路径**结构性缺席**——逐块复核 `build_system_prompt_parts`，所有 guidance 都以工具名在场为门，CTF 工具面不含它们。按模式门控的目标已达成，无需再动；chat 路径保留原样（那里引导是有效的）。

**P3.3 · 给 `ctf-knowledge/SKILL.md` 加 frontmatter** ✅ **已完成（2026-09-13）**

- **实做：** name/description/category/version/author 五键；仓库副本与已安装副本
  （`~/.fulilian/skills/`）同步。`GitHubSource._parse_frontmatter_quick` 验证两份
  均可解析。
- **为什么：** §3.D —— 7.5 MB 卡片集因缺 frontmatter 在索引里等于不存在。

**P3.4 · skills 索引开 `names_only` / `compact_categories`** ✅ **已作为 A9 的副产品达成（2026-09-14 复核）**
- **原方案：** 189 条技能名占 20,239 字符（~5.1K tokens），代码里已有这两个开关。
- **实际：** A9 之后 CTF 工具面无 skills_list/skill_view/skill_manage，`has_skills_tools` 门控为假时 `skills_prompt = ""`——整个 skills 索引在 CTF 路径已结构性移除，比"开关压缩"更彻底。chat 路径的索引压缩开关仍可在需要时打开，不再单列任务。

**P3.5 · AGENTS.md 注入加尺寸上限**

- **建议：** 上限 4 KB；且 CTF 解题时**绝不注入**仓库自己的开发指南。
- **为什么：** §3.D —— 仓库 cwd 下多出 96 KB。

### P4 — 修知识层

**P4.1 分词器**：换 `unicode61` + 分词，或保留 trigram 但让 2 字 CJK 查询直接走 fallback。
✅ **失效模式已消除（2026-09-14，随 P4.2/P4.4 顺势结案）**——2 字中文不再毒化多词 FTS
查询（sanitize 后 OR 连接，短词项空命中不拖垮其他项），纯短词 query 由 `_fallback_token_search`
兜住（金标 robust-04"注入"n=5 证实）。**换分词器/重排检索目标的增量收益并入 P4.3** ——
那是相关性问题的真正领地（realistic 20% 的 miss 全是 bm25 排序，不是短词崩溃）。
**P4.2 sanitize 下沉**：把 sanitize 放进 `knowledge_retriever.search()` 内部。
✅ **已完成（2026-09-14，见 §9 ⑦ 附记）**——`sanitize_match_query` 进 `search()` 首行，
清洗后为空早退不建索引；`knowledge._sanitize_query` 变兼容壳。realistic 20% 持平
（miss 是相关性问题，属 P4.1/P4.3），robustness 从"碰巧不崩"变成"结构上不崩"。
**P4.3 检索目标换成技术卡**：2583 篇中文赛后 wp 是给人看的；agent 需要紧凑的「技术 + payload」单元。那 20 篇专题（SQL 116K / PHP 反序列化 212K）配 `.idx.md` 分段索引才是对形状 —— **但目前没有任何代码读 `.idx.md`**。
✅ **已完成 v1（2026-09-14，见 §9 ⑩）**——但形状与设想不同：探针发现手工
`.idx.md` 行号漂移 32%（108 段抽检 35 段不符，idx 内容与文档标题结构脱节），
**代码不该读 `.idx.md`**。落地为 `topic_segments.py`：运行时从专题文档
`#{1,3}` 标题自建段索引（13 文档 / 906 段，mtime 缓存），token 重叠匹配 +
三重闸门（操作符剔除去重、≥2 token 或单个 ≥3 字具体词、ASCII 词边界防
`ida`⊂`IDAT`），注入「专题速查」块给出行号直达指针（`Read offset=`）。
同源金标评测：web 覆盖域 hit@2 = **75%**（3/4），域外正确沉默（pwn/crypto/
reverse 无专题库）；全档 3/10 vs WP 检索基线 20%。mutation 测试 3/3 被抓，
15 项新测试绿，既有 114 项知识层测试绿，golden 三档无回归。
**P4.4 加相关性闸门**：top-3 分数不达标就注入空。**噪声比沉默更贵。**
✅ **已完成（2026-09-13）**——特异性闸门（裸分类词不检索）+ 命中下限
（title+snippet 须含 ≥2 个不同查询 token）+ LIKE 兜底按 token 命中数降序。
真库验证与回归锁见 §9 ②。
**P4.5 修或删 benchmark**：§3.E，自证的 `hit@5 = 1.0` 会带来虚假信心和错误的优化方向。
✅ **已完成（2026-09-14，见 §9 ⑦）**——金标重构为三档，诚实基线 realistic hit@5 = **20%**。

### P5 — 用能力替换仪式

**P5.1** 四阶段 RECON/PLAN/EXECUTE/REFLECT + ABANDON IF + `record_fact` 账本，是在给"不会规划的模型"打石膏，消耗轮次。对强模型换成 10 行操作规则。（`run_agent.py:9094 _build_ctf_system_prompt`）
> ⚠️ **方向已被 ④ 实测否决（在弱模型上）**：hard-solve-protocol A/B 送达已证明（5/5 轨迹出现协议段）但经济性为负（ctl 2.7× / exp 3.0×）→ 协议层仪式不换、默认关。**未复测条件：** ⑪ 显示 GLM-5.3 api 持平、token −46%——若强模型成为默认，协议开销可否被能力抵消需在强模型上重测（n=1 不够重开此账）。
**P5.2** 补真有用的：并行假设扇出（racer 已有，先确认能不能用）；"同一攻击 3 次变体失败"交给 **runtime 计算**，而不是让模型回忆。
✅ **结案（2026-09-14，见 §9 ⑧）——两个子项都不需要新建任何东西**：racer 已建成可用（14 项测试绿，`solve --race` 与 dispatcher `switch_model` 升级路由双接线）；"runtime 算重复攻击"机制也已在（`stopper.count_variant_failures` → `HYPOTHESIS_REPEATED` → 强制换攻击类，34 项测试绿）——该行写于机制盘点之前，已过时。探针另证：现有存档日志全为 20 字符截断期，重复攻击失效模式零观测，无追加机制的需求信号。

### P6 — 模型路由 ✅ **代码完成 + 试水 A/B 已跑（2026-09-14，见 §9 ⑪）—— GLM-5.3 三题全解、token −46%、api 持平（噪声地板内）；正向信号但 n=1 不足以改默认路由。运营发现：scnet GLM 额度撑不满 3 题批，供应商已按用户指示全局切 ark**

硬题走最强模型。现在默认 `DeepSeek-V4-Flash@128K` + 大量石膏 = 弱模型 + 重脚手架。**脚手架补不了模型的差距，模型能省掉脚手架。**

### P7 — 剪面积

68 个顶层 CLI 子命令，CTF 相关 6 个。启动不是瓶颈（`fulilian --version` = 0.166 秒），所以问题不是速度，是 **prompt 面与工具面的冗余**。一个 CTF 专用 profile 能同时减掉认知面与 token 面。

### P8 — 修文档（低风险，累积成本高）✅ **已完成（2026-09-14，见 §9 ⑦ 附记二）**

§3.M 的迭代预算三方矛盾（500 / 50 / 90 ↔ 实际 `sys.maxsize` / 250）。
✅ `iteration_budget.py` docstring、`delegate_tool.py:1762` 注释、`agent_init.py:627` docstring 全部改为与代码一致。
§3.N 的压缩器注释与实际值不符（"(15)"/"(20)" ↔ 45/50；基类 0.75/3/6 ↔ 实际 0.60/3/7）。
✅ 触发点注释改为 (45)/(50)；基类默认值块加"实际以 ContextCompressor 覆盖为准"注记。
`fulilian_ctf/knowledge.py:158 inject_ctf_context()` docstring 把参数命名为 `system_prompt`，但**所有调用者传入的是首个 user 消息**。
✅ 参数改名 `prompt`（全部调用方本就走位置传参，无关键字破坏面），docstring 如实说明两种实参形态。

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
| CTF API 无读超时 | **已修复（2026-09-13）** | 客户端默认层 `read=None` → `FULILIAN_CLIENT_READ_TIMEOUT`（默认 600s）；见 §10 第 1 条 |
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

**~~仍未解决~~（2026-09-13 已修复，见 §10 第 1 条）：** CTF API 路径**无读超时**（实测一次挂起：
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

### 2026-09-11 · 静态前缀的 token 数被当成了花费（P3/P7 降级，见 §10 第 4 项）

在等 2c 跑批时顺手查了一件影响排序的事：**下面所有"省了 N tokens"的数字，
记的都是 prompt 尺寸，不是计费量。** 两者在本环境里差一个缓存折扣。

实测（`/tmp/ctf-*/*/solver.log`，19 个跑批，共 219 次 API 调用）：

```
有缓存写入的调用 = 0 / 219        写入总量 = 0 tokens
```

即 `💾 Cache: ... (85% hit, 0 written)` 是本环境的常态。原因是模型走
`DeepSeek-V4-Flash` + `custom` provider（`api.scnet.cn`，OpenAI wire），
属**服务端自动前缀缓存** —— 没有 Anthropic 那种 `cache_control` 写标记，
因此也没有 1.25× 的写入溢价（`agent/conversation_loop.py:4375` 的注释正是
在说这批 provider 会自动返回 `cached_tokens`）。

这直接改了两件事的算账方式：

1. **`usage.json` 的 `input_tokens` 是未打折的原始 prompt 总量。**
   `reverse-obfchain-01` 记 265,065 / 14 次调用 ≈ 18,933，与日志逐次
   `prompt_tokens`（10,238 → 23,447）之和吻合，而其中约 80% 每次都是缓存命中。
   所以**跨改动比 `input_tokens`，比的是尺寸差，不是账单差。**
2. **砍静态前缀，省下的只是缓存那一档，不是面值。**
   静态前缀（system prompt + 工具 schema）本身就在命中区间里：首屏
   `prompt_tokens = 10,238` vs 消息估算 6,686 → 前缀约 3,000–3,600 tokens，
   且首次调用就是 85% 命中（0 写入）。删掉一个已被命中的 token，
   省的是它的命中价，不是它的面值。

**于是 P3/P7（§10 第 4 项）被降级。** 该项原本的靶子是 `terminal` schema
3,247 字符"最肥"。实测拆开是：

| 组成 | 字符 | 59 次真实 `terminal` 调用里的使用次数 |
|---|---|---|
| `description` 总述 | 1,494 | — |
| `command` | 65 | **59** |
| `timeout` | 289 | 10 |
| `background` | 346 | **0** |
| `notify` | 514 | **0** |
| `pty` | 199 | **0** |
| `workdir` | 131 | **0** |

（另：总述段 2「Foreground/Background/PTY」766 字符，通篇讲后台进程与
`process(action=...)`，CTF 路径一次都用不到。）

看上去能砍 1,198（四个零使用参数）+ 766（后台段）≈ 1,964 字符，是
`schema` 的 60%。但按 §1.6 的口径 22,942 字符 ≈ 1,400 tokens，
**1,964 字符 ≈ 120 tokens，且是命中价 ≈ 每次调用 12 tokens 量级** ——
与 A9 那个"−3,186 tokens/次"（同样是尺寸数，其账单效果同样要打这个折扣）
不在一个量级。

> **这条要连 A9 一起读。** §1.6 记的 "−3,186 tokens/次" 是**首屏 prompt
> 尺寸**的下降，是事实；但它不是每次调用的账单下降 —— 首屏之后的调用，
> 那段前缀本来就走命中价。A9 仍然值得做（它同时删掉了**够不着**的技能索引
> 10,192 字符，那是纯噪声），但**用它去论证"静态前缀改动收益大"是错的**。
>
> 与之相对，**P0.1 / 2b 这类改动作用在增长中的消息历史上**（工具输出、
> 对话轮次），那部分**不在**稳定命中区间内 —— 命中率逐次从 96% 掉到 38%
> （见 `reverse-obfchain-01` 逐次 Cache 行）正说明这一点。**要省，就该省
> 那部分。** 这是 §1.4 结论的加强版，不是推翻。

顺带否掉一条可能的反对意见：schema 臃肿的另一个代价是"模型被多余参数带偏"。
实测不支持 —— 59 次调用里 `background`/`notify`/`pty`/`workdir` **一次没用过**，
不存在误用可修。

**未验证的一点（写下来免得下次当已知）：** 命中价具体的折扣率本环境取不到 ——
`usage.json` 的 `cost_usd` 全是 `0.0`（自定义 provider 不记账）。上面所有
"≈0.1×"均按 DeepSeek 系公开口径推算，**不是实测**。要实测得换一个会返回
计费字段的 provider，或在网关侧对账。

### 2026-09-11 · A9 之后 A3 已成死开关 —— §10 第 3 项按原样跑会得到假的"无效果"

准备第 3 项（A3 对照跑）时先查了它的触发条件，发现**按计划书写的那样跑不出任何东西**。

两条回合后审查路径都**硬门控在工具名上**：

```python
# agent/turn_context.py:778  记忆审查
should_review_memory = False
if (agent._memory_nudge_interval > 0
        and "memory" in agent.valid_tool_names      # ← 硬门控
        and agent._memory_store):
    ...

# agent/turn_finalizer.py:780  技能审查
_should_review_skills = False
if (agent._skill_nudge_interval > 0
        and agent._iters_since_skill >= agent._skill_nudge_interval
        and "skill_manage" in agent.valid_tool_names # ← 硬门控
        ):
    ...
```

两个 nudge interval 默认都是 10（`agent_init.py:1854,1983`），所以**唯一剩下的闸门
就是工具名**。而 A9 从 `ctf_solve` 里删掉的恰好是 `memory` 与 `skill_manage`。

展开验证过没有旁路进来：CTF 路径只启用 `ctf_solve`
（`run_agent.py:9475-9476`：`mode == "ctf"` 且未显式指定时 `enabled_toolsets_list = ["ctf_solve"]`），
而 `ctf_solve` = 4 个 CTF 工具 + `terminal`(terminal, process) + `file` + `web` + `vision`
= 13 个工具，**不含这两个名字**；全仓另外 24 个含它们的 toolset（`coding` / `memory` /
`skills` / 各 IM 宿主）在 CTF 路径上一个都没启用。

**结论：A9 之后，CTF 路径上背景审查 fork 已经不可能生成，`skip_background_review`
不再改变任何行为。A3 成了冗余开关（无害，但也不再是那"一半"）。**

**这直接作废了第 3 项的原设计。** 原写法是"把 `skip_background_review` 翻回 `False`
再跑"——但两个 `_should_review_*` 恒为 `False`，翻开关测出来的差异**必然接近 0**，
而那个 0 是实验设计的产物，不是 A3 的事实。**这正是本计划书反复在踩的同一类错：
把"信号到不了"读成"效果为零"。**（对照 §10 第 3 条那次：把日志缺失读成工具 0。）

**正确的对照跑必须同时回退 A3+A9**（把 `memory`/`skill_manage` 放回 `ctf_solve`
**并且** `skip_background_review=False`），即恢复到真正的 A3 之前状态。
这样一次跑同时回答第 3 项与第 6 项：

- 与当前基线（`57785ff` 之后）之差 = **A3+A9 的合计效果**
- 减去 A9 已单独验收的静态前缀分量（首屏 −3,186 tokens/次） = **A3 的净效果**

两个待办项合并成一次对照跑，而不是各跑一小时。

> **已按此跑完（2026-09-12）。** 但这套相减的算法有个前提没成立：**那一跑里
> "A3+A9 合计效果"这一项本身就"分辨不了"**（Δ 落在逐批地板以内），拿一个
> 分辨不了的数去减另一个数，得到的"A3 的净效果"是噪声相减。A3 的结论最终
> 靠的是**代码级证据**（fork 发不出 API 调用、其消耗不进 `usage.json`），
> 对照跑只是"没有反证"。见 §9「A3+A9 对照跑结案」。

> **这条与 toolsets.py 里那段「⚠️ 耦合」注释的关系：** 注释说"若重新开启
> `background_review`，必须把这两个名字加回，否则自省会静默失效" —— 方向仍然对，
> 但它写于 A3 时代，当时 fork 能被 flag 单独关掉。A9 之后是**两重**关闭：
> flag 关一次，工具名又关一次。回退时必须两处同退，只退一处等于没退。

### 2026-09-11 · 2c 完成：噪声地板 **1.40×** —— 从此"有没有效果"有判据了

三次连跑（同一份代码、同一协议、4 题 × 3 次 = 12 次 solve，
`benchmarks/baselines/2026-09-11-ctf-hard-n3.json`）：

| fixture | n | 解出 | flag | api 均值 | api 范围 | ×参考解 均值 | ×参考解 范围 | token 均值 |
|---|---|---|---|---|---|---|---|---|
| forensics-brutelog-01 | 3 | 3/3 | 3/3 | 14.0 | 12–17 | 2.8× | 2.4–3.4 | 285,501 |
| misc-bigscan-01 | 3 | 3/3 | 3/3 | 16.3 | 15–18 | 4.08× | 3.75–4.5 | 332,000 |
| misc-chunkconcat-01 | 3 | 3/3 | 3/3 | 21.3 | 18–25 | 4.27× | 3.6–5.0 | 743,960 |
| reverse-obfchain-01 | 3 | 3/3 | 3/3 | 21.3 | 18–26 | 3.55× | 3.0–4.33 | 860,901 |

**12/12 解出、12/12 flag 与 manifest 逐字一致。** 合并经济性 **3.6×**
（219 api / 60 参考步数）。

**噪声地板 = 1.40×**（`misc-chunkconcat-01` 3.6–5.0×）。这是 2c 交付的东西：
**此后任何改动的 ×参考解 位移若小于 1.40×，本判据分辨不了，不得归因。**

三条被这批数据改写的判断：

1. **v1→v2 那 0.8× 的"提升"仍然不成立** —— 结论没变，但依据变了。
   n=2 时算出的地板是 2.00×，那是**高估**：两个样本只能撞上极值，看不到真实
   分布的形状。n=3 把地板收到 1.40×，0.8× 依旧在它以内。
   （方法论：**n 越大，地板越低** —— 地板本身是随 n 收敛的量，不是常数。）
2. **`reverse-obfchain-01` 的 26→14 从来不是改进。** n=3 下同一份代码跑出
   18 / 20 / 26 api —— v2 那个 14 是分布的一端，v1 那个 26 是另一端。
   把它读成"v2 优化了 obfchain 的路径"是典型的单点归因错误。
3. **`misc-chunkconcat-01` 才是真探针**：token 均值 743,960（次高者的 2.2×）、
   api 跨度也最大。它同时是 2b 加进来的题和 §10 第 3 条那次日志覆盖的现场，
   现在看它确实压在 P0.1 想打的那条路径上。

> **2c 到此关闭。** 剩下的"经济性"工作只有一件事：**下次改动前先看这个 1.40×**。
> 若某改动的预期收益小于它，要么加大 n，要么别浪费一次跑批。

### 2026-09-11 · 把地板真正用起来：`--compare`，以及**合并指标比逐题指标灵敏一个数量级**

2c 交付了地板，但**没有任何代码去用它** —— 地板印在报告里，"这次改动有没有效"
仍然是肉眼看两个数字。这跟 2c 要解决的问题同源：判据存在 ≠ 判据被应用。

**先说最容易踩的那一脚：把两组批目录塞进一次 `--runs`。** 那样算出的"地板"
会把两组之间的**真实差异**一起算进去 —— 拿被测量的东西当尺子，差异越大尺子
越长，永远测不出显著。所以 `--compare 改动前.json 改动后.json` 必须分两侧估，
逐题给 Δ 与其自身地板，判据是 `|Δ| > 地板`（`c08c659`）。

三条**不许静默**的路径，全部点名报出，因为它们正是"把缺失读成零"的入口：

| 情形 | 静默的后果 | 报告的行为 |
|---|---|---|
| 只在单侧出现的题 | "没测到"读成"没效果" | 列出题目名 + "单侧数据不构成对照" |
| 参考步数两侧不一致 | 题目变了却当成同一道题比 | 排除 + 打印 `5 → 7` |
| 批没跑齐对照题集 | 偷偷缩小样本 | 列出批名（带侧别前缀） |

**然后是这批数据给出的、比预期更有价值的一条：合并指标的地板远小于逐题地板。**

同一份 n3 归档自比（Δ 恒为 0，纯看地板长什么样）：

| 指标 | 地板 |
|---|---|
| 逐题 ×参考解（最差题 `misc-chunkconcat-01`） | **1.40×** |
| 逐题 ×参考解（最好题 `misc-bigscan-01`） | 0.75× |
| **合并 ×参考解** | **0.07× 量级** |

机制是各题噪声**部分抵消**：合并值是 `Σapi / Σ参考步数`，四道题的摆动不同步，
在分子上互相削。实测（单测里的构造例）逐题跨度 4.0× 的两道题、摆动错开时，
合并跨度只有 3.0×；真实 n3 数据上差异更大。

**所以合并 ×参考解 才是验收该用的尺子，不是逐题。** 2c 的 1.40× 是**逐题**
地板 —— 把它当成"任何改动都要跨过 1.40×"的门槛，会白白放弃一个数量级的
分辨力，把 0.1× 量级的真实效果判成噪声。

地板本身**按跑批量实测**，不从逐题跨度推导：把每个跑批各自的合并值算出来取
跨度。这样地板与被判的量是同一个统计量，不依赖「只有一题在摆」之类的假设。
代价是**每侧至少 2 个跑批**，否则报"采样不足"（`None`）而不是 0。

> **一条要记住的方法论：判据必须和被判的量是同一个统计量。** 用逐题地板去
> 验收合并指标，和用合并范围去估组内噪声，是同一个错误的两面。

**第 3+6 项的对照跑（回退 A3+A9）已在 `/tmp/ctl` 隔离跑批中。** 隔离不是洁癖：
`revert` 在 doc 冲突处**静默停下**，第二个提交根本没回退 —— 若不核对，跑批器
会产出一份"控制组 = 实验组"的假对照。所以跑批脚本开头加了一段**对照前自证**：
断言模块确实从 `/tmp/ctl` 解析、`skip_background_review=True` 确实不在了、
`ctf_solve` 里 `memory`/`skill_manage` 确实回来了，任一条不成立就拒绝开跑。

### 2026-09-11 · A3 的账算错了：`solve -p` 上那条 fork **跑不起来**，而且**本来就测不到**

对照跑（回退 A3+A9）跑到第 2 题时，日志给出了直接证据。先说结论：

> **A3 在 `solve -p` 路径上省的钱 ≈ 0，不是 ~30K tokens/次。**
> 它关掉的那条 fork 确实被**创建**了，但在**发出任何 API 调用之前**就随进程退出
> 被销毁。§9「A3 完成」里那个「批量 10 题即 ~30 万 token 纯开销」**不成立**。

**证据（`~/.fulilian/logs/agent.log`，2026-09-11 对照跑现场）：**

```
23:32:47,363  [..0fe983] Turn ended: reason=text_response api_calls=16/30 tool_turns=15
23:32:47,406  run_agent: OpenAI client created thread=bg-review:128355894118080   ← fork 起来了
23:32:47,622  agent.model_metadata: ... (probe-down) ...                          ← 还在初始化
23:32:47,624  tools.tool_search: tool_search activated (tier 1)                   ← 还在初始化
23:32:47,963  tools.terminal_tool: Shutting down 1 remaining sandbox(es)...       ← 主流程已在收尾
23:32:49,664  fulilian_cli.plugins: FULILIAN_SAFE_MODE=1 ...                      ← 下一题的新进程已启动
```

**没有 `Background review complete` 行，也没有 `conversation turn ... msg='Review the
conversation above...'` 行** —— fork 从没走到模型调用。对照同一份日志里
**长驻会话**（12:40，TUI 路径）的同一个 fork：

```
12:42:05,127  agent.background_review: Background review complete:
              thread=bg-review calls=7 in=34859 out=5579 cache_read=376832 result=none
```

**同一个机制，两条路径上命运完全不同**：`solve -p` 是「一个进程解一题、解完就退」，
fork 是 daemon 线程，主进程退出即被杀；TUI/gateway 长驻，fork 能跑完 7 次调用、
吃掉 34,859 in-tokens。**A3 的依据（`agent_init.py:695-702` 的注释 + cron 先例）
描述的是后者，被套用到了前者身上。**

**第二层，也是更早该问的一层：这条 fork 的消耗从一开始就进不了 C 系列采集器。**
`usage.json` 由 `_read_session_usage(agent)` 从**求解 agent 自己的内存计数器**取
（`fulilian_ctf/solver.py:75-89`），而 fork 是**另一个 AIAgent 实例**，它的计数器
不会累加回父实例。fork 自己的消耗走
`agent/background_review.py::_record_review_usage_to_parent`，那条路径**只写
`session_model_usage`，明确不碰计数器**，而且要求父 agent 有 `_session_db` ——
`solve` 路径根本不建 session DB，所以连这笔记录也不会发生。

> **所以：即使 fork 能跑完，`--compare` 也一个 token 都看不见。**
> 把「对照跑没测出差异」读成「A3 无效果」是错的 —— 那是**尺子够不着**，
> 不是**量出来是零**。这正是本计划书反复踩的那一类错误的又一变体。

**对 A3 的处置：保留，但撤回它的收益主张。** `_run_solver_turn` 只服务 CTF
求解器，关掉 fork 对 TUI/gateway 无影响；在 `solve -p` 上它是一个**空操作**
（省 0，也不损失什么，因为 fork 本来就没跑完）。真正的教训是**依据的来源**：
拿长驻会话的实测数去论证短命批处理路径上的收益，中间少了一次「这条路会不会
真的执行到那里」的核对。

> **一般化（这次的真正收获）：** 任何「关掉 X 能省 N」的主张，都要先确认 X
> **在目标路径上确实执行了**，以及它的消耗**确实计入你用来验收的那个数**。
> 两个条件缺一个，省下来的都是纸面数字。核对成本很低 ——
> `grep` 一次日志找「开始行 / 结束行是否成对」，比跑一小时对照便宜得多。

**对照跑本身继续**（它仍然合法地回答第 6 项：A9 的 n≥3 复测）。预期结果：
A3+A9 合计效果 ≈ **A9 单独的效果**，因为 A3 那一半是 0。

### 2026-09-12 · A3+A9 对照跑结案：合并指标看不见它，配对量一次就看见

上一条预测「A3+A9 合计效果 ≈ A9 单独的效果」。**对照跑证实了这个预测，但
证实的方式不是那个判据** —— 判据说"分辨不了"。这一条记的是：判据为什么
分辨不了，以及真正的答案是怎么量出来的。

#### 一、先说对照本身合不合法（这一步归档替你做不了）

`--compare` 现在会印每侧的采集时间与跑批目录，但**归档记不下"两侧之间代码
差了什么"** —— 而这恰恰是判断一个 Δ 该记给谁的全部依据。这次必须手工核对：

```
$ git diff --stat 8ada9e6 b4f14cf          # 基线版 → 对照版
 run_agent.py           | 11 --------       # A3：skip_background_review
 tests/test_toolsets.py | 76 ++++++-------
 toolsets.py            | 29 ++++++-----    # A9：memory/skill_manage
```

即两侧**只差那两个 revert**。另一侧的核对同样必要：n3 基线的跑批窗口是
`22:59:04 – 23:27:51`，这段时间里没有任何触及 `run_agent.py` / `toolsets.py`
的提交（最近一次运行时改动是 `22:38:20` 的日志镜像修复）。**两个前提都成立，
这个对照才算数。**

#### 二、判据的读数：4 题全部"分辨不了"

对照 = `/tmp/ctl`（`8ada9e6` 上叠加 `5476537` 逆转 A9、`b4f14cf` 逆转 A3），
3 批 × 4 道难题。**12/12 解出、flag 全对。**

> **该状态已打标签 `ctf-ctl-a3a9-revert`**（原本只是 `/tmp/ctl` 上的游离 HEAD，
> 撤掉 worktree 后不可达 —— 一份写进计划书的测量不该依赖 `/tmp` 里一个随时会被
> gc 的提交）。复现：
> `git worktree add /tmp/ctl ctf-ctl-a3a9-revert` 然后
> `PYTHONPATH=/tmp/ctl bash /tmp/ctl/benchmarks/ctf_hard_run.sh <输出目录>`。
> **`PYTHONPATH` 能压过 editable 安装，已实测** —— 这是隔离对照而不动主仓库的
> 办法（并发会话多，主仓库不一定是你的）。

```
改动前 = 对照（A9 撤）   改动后 = 基线（A9 在）
```

| fixture | ×参考解 前 | ×参考解 后 | Δ | 地板 | 判据 |
|---|---:|---:|---:|---:|---|
| forensics-brutelog-01 | 2.67× | 2.80× | +0.13× | 1.00× | ❌ 分辨不了 |
| misc-bigscan-01 | 4.50× | 4.08× | −0.42× | 4.50× | ❌ 分辨不了 |
| misc-chunkconcat-01 | 3.20× | 4.27× | +1.07× | 1.40× | ❌ 分辨不了 |
| reverse-obfchain-01 | 2.95× | 3.55× | +0.60× | 1.33× | ❌ 分辨不了 |

合并经济性 **3.25× → 3.65×**（195 → 219 api / 60 参考步数），Δ **+0.40×**
对逐批地板 **0.80×** —— 也分辨不了。

**注意方向容易读反**：Δ 的字面意思是"施加 A9 后更贵 +0.40×"。这与 A9 的
机制相反（删工具只会让请求更小），所以它不是 A9 的效果 —— 见下一节。

地板 0.80× **全部来自对照侧**（逐批 3.45 / 3.55 / **2.75**），基线侧只有
0.20×（3.75 / 3.55 / 3.65）。一批跑得特别顺，地板就被抬到看不见 0.40×。
而每侧只有 3 个批，这个地板本身也只是 3 个数的跨度。

#### 三、token 的"倒挂"，以及它的完全分解

直接读数是：基线 2,222,362 < 对照 1,781,128，即**撤掉 A9 反而更省** ——
不可能。按每轮（4 题）归一：

| | 一轮 4 题 api | 一轮 token | **tok/调用** |
|---|---:|---:|---:|
| 对照（A9 撤） | 65.0 | 1,781,128 | **27,402** |
| 基线（A9 在） | 72.9 | 2,222,362 | **30,485** |

基线每调用反而多 3,083。把已单独测出的 A9 项（−3,305/调用，见下一节）扣掉：

```
基线若撤销 A9： 30,485 + 3,305 = 33,790 tok/调用
对照实际：                        27,402 tok/调用
                        → 轨迹差异 +6,388 tok/调用（+23.3%）
```

**倒挂全部来自轨迹长度，与 A9 无关，而且它（+6,388）是 A9 那一项（−3,305）
的约 2 倍、方向相反。** 两个采集批次之间"每调用上下文涨了 23%"这种量级的
摆动，在这个基准上比 A9 的效应还大 —— 所以 4 题 × 3 批的聚合读不出 A9，
是**必然**，不是运气不好。

#### 四、把量搬到 A9 真正确定的那一格上

A9 改的是**静态前缀**，那就不该用"整轮总 token"去测它 —— 整轮总 token 里
前缀只占一次，其余全是轨迹。`solver.log` 里本来就有那一格：

```
🔄 Making API call #1/30...
   📊 Request size: 2 messages, ~10,039 tokens
```

**第 1 次调用的上下文 ≈ 静态前缀 + 题面，里面没有任何轨迹。** 同题、同批序
配对（基线第 i 批 vs 对照第 i 批）：

| fixture | 基线（A9 在）首屏 | 对照（A9 撤）首屏 | Δ 逐批 |
|---|---|---|---|
| forensics-brutelog-01 | 6,714（3 批同值） | 10,007（3 批同值） | +3,293 ×3 |
| misc-bigscan-01 | 6,734 / 6,721 / 6,721 | 10,039 ×3 | +3,305 / +3,318 / +3,318 |
| misc-chunkconcat-01 | 6,735 / 6,722 / 6,722 | 10,040 ×3 | +3,305 / +3,318 / +3,318 |
| reverse-obfchain-01 | 6,743 / 6,729 / 6,711 | 10,026 ×3 | +3,283 / +3,297 / +3,315 |

**12/12 对全为正，均值 +3,305，跨度 3,283–3,318（35，即 1.1%）。**

这就是 A9 的效果，**确定性**地测到了。同一份数据，聚合指标说"分辨不了"，
配对量一个几乎无方差的格子一次就给出答案 —— 成本是 0，日志本来就在。

> **与 §1.6 记的 −3,186 差 119（3.7%）。** 这 119 归属未查：§1.6 是 21:09 的树、
> 3 道 easy 题；这里是当前树、4 道难题。它不影响任何结论（两种口径都是
> "每调用约 3.2–3.3k"），但**要精确报账就得在同一棵树上、同一题集上量**，
> 不能拿两次不同来源的读数相减。§1.6 那个数按新口径更新为 **≈3,305/调用**。

#### 五、结论（第 3、6 项结案）

- **第 6 项（A9 的 n≥3 复测）：完成。** A9 = **−3,305 tokens/调用**（配对，
  12/12，跨度 1.1%）。按实际调用数折算，一轮 4 题省 **214,825 – 240,935**。
  **原判据（合并 ×参考解，地板 0.07× 量级）选错了统计量** —— 它灵敏于
  **行为**差异（跑几轮、走什么路径），而 A9 的效应在**前缀**里，两者不在同一格。
- **第 3 项（A3 对照）：完成且维持原判。** 对照跑同样证实"A3 那一半是 0"
  —— 撤掉 A3 没有带来任何可分辨的变化，与 §9「A3 的账算错了」的代码级结论一致。
- **质量无损：** 两侧都 12/12、flag 逐字全对。A9 没有让 agent 变笨。

#### 六、教训（比这次的答案重要）

1. **先问"效果落在哪个统计量上"，再决定跑多少轮。** 一个确定性的 3.3k 效应，
   用整轮聚合去测是一枚硬币；用它真正改的那一格（首屏前缀）去测，一次就够了。
   **选统计量比加样本便宜得多** —— 加样本只是把硬币抛更多次。
2. **合并指标灵敏一个数量级，但它不是万能的。** 它灵敏于行为差异；效应在
   固定开销里时，它照样看不见。别把"这套指标测不出 X"当成"X 无效"的通用结论。
3. **"分辨不了"必须与"无效"分开写。** 这次两者恰好指向同一结论（A3 真的省 0），
   但**理由完全不同**：A3 是代码级证明它跑不起来，不是"没测出来"。
   若把后者当前者用，下次就会在真有效的地方误判。
4. **配对（同一题目、同一批序）能把不可归因变成可归因。** 逐批配对后，12/12
   全为正、跨度 1.1% —— 而不配对时，同一批数据的 Δ 是 −0.42× ~ +1.07×。
   配对消掉的是"这一批恰好跑了多久"，那正是噪声的主成分。

### 2026-09-13 · 答案泄漏围堵第二轮 + 第三轮：`4d7067c` 与本次提交

**背景。** 天花板效应要修，前提是"基准自己不漏答案" —— 会漏时，后面所有关于
难度的结论都不成立。第一轮（`4d7067c`）把 `logs/`/`mirror/`/`proof/` 挪出 `$OUT`，
并给 `_gate()` 加了 `$OUT` 直属条目的**白名单**。那轮修的是"agent `ls ..` 能看见"。

**第二轮：位置不是边界。** 复核时按"agent 会怎么找"重做了一遍，发现挪位置只挡住了
`ls ..`，挡不住 `find /tmp`。实测三处仍在漏：

1. `$RUN_ROOT/logs/<id>.reference.log` —— 参考解 stdout，是**当前这道题**的明文
   flag，在它自己 solve 期间就躺在盘上，`find /tmp -name '*.reference.log'` 直接命中；
2. **跑批器自己的 stdout**：`flag=$(cat "$d/FLAG")` 那行，而批日志被重定向到
   `/tmp/ctf-n3.log` 之类 —— 同批后跑的题、以及后续每一批都读得到。实测五个历史批
   日志里共 **34 处**明文 flag，全部出自这一行；
3. 跑完那题的 **work_dir 原样留在盘上**，而 agent 自己写的 `ctf-notes.md` /
   `blackboard.json` 里就是明文 flag。

改法：判据从"放哪"换成"**跑批期间在不在盘上**"。参考解输出与源码自证通过后**立即
删除**（只留 sha256）；跑完那题的整棵 work_dir / 日志 / 镜像立刻收进 `$SEALED`，
等 agent 全部退出再还原 —— 还原是为了**不改采集器与归档格式**。

**第三轮：`/tmp` 之外还有一个固定路径。** 清完 `/tmp` 后按 manifest 里那四个**真**
flag 的字面量做全盘 grep（不是 `grep 'flag{'`，那样满屏误报），答案还在两处：

4. **agent 自己的产品家目录 `~/.fulilian/`**：`traces/<题名>.json`（文件名就是
   work_dir 名，agent 知道自己的名字，可以直接 `cat`）、`learning.json`（19 处明文
   flag，00:25 还在被写）、`cache/terminal-output/*.log`。这是 `mktemp` 隔离**碰不到**
   的固定路径，而且**它自己会长** —— 每跑一次写进新 flag 留给下一跑读，与 n3 那次
   "run1/run2 互为兄弟"同一个病，只是搬进了产品目录。
5. **编排者自己的会话记录** `~/.claude/projects/*.jsonl`、`file-history/`：agent 与
   编排者同用户，读得到；编排过程中把明文 flag 打到过工具输出，就在里面。

修法：每题给一个 `FULILIAN_HOME`（官方机制，`fulilian_constants.py` 明写 subprocess
spawner 应当显式传它；本机无 `active_profile`）。答案态给**空的新目录**，其余 symlink
（读得到、写不脏真身）。第 5 条跑批器**不删**（那是用户的对话记录与审计线索），只在
preflight 报出来。

**自测与证伪。**
- 真跑一次单题冒烟（`misc-bigscan-01`）：`rc=0`、flag 已写、trace 与 learning 落在
  隔离家里、**真身 `traces/` 指纹与 `learning.json` mtime 均未变**。
- 新增 6 条锁（共 16 条，全绿），并用**变异体**逐条证伪：把 `traces` 从"给空"名单拿掉、
  删掉传给 solve 的 `FULILIAN_HOME`、把"每题一个家"改回共用一个、把指纹比对改成假比对
  —— 四条各自红在该红的测试上。这里**不能**拿旧提交跑功能测试：旧版不认 `--seed-home`，
  会把它当成 `$OUT` 直接开跑一整批四道题。
- 变异体还抓出**本测试自己的一个洞**：`test_isolated_home_actually_hides_the_poison`
  最初只用 `grep -rlF`，而 `grep -r` 不跟进递归中遇到的目录符号链接（`-R` 才跟进），
  于是"traces 被 symlink 回真身"的变异体下它照样绿。可 agent 不做递归搜索 —— 它知道
  自己的题名，直接 `cat`。**断言方式弱于攻击方式时，锁就是装饰。**

**教训（比这三轮的具体改动重要）：**
1. **"换个位置"和"清掉某一处"都不是判据，"在不在它能读到的地方"才是。** 每修一处
   都要重新做一次全盘搜索，而不是假设"这回想全了" —— 第二轮以为修完了，第三轮又找出两处。
2. **残余边界要写出来，不要假装关上了。** `$SEALED` 里是 `.gz`，而 **gzip 不是加密**；
   同用户同文件系统下真正关上门只能换用户/容器。第 5 条同理。
3. **能自动化的验证就别靠"我读过源码"。** `_home_fp` 在开跑前后各取一次真身指纹并比对
   —— `FULILIAN_HOME` 哪天被改名或被 profile 覆盖，泄漏会**静默**回来，而"跑完才发现
   结果已被污染"是最贵的那种失败。
4. **同一个病会换地方复发。** n3 的"兄弟目录"、第二轮的"批日志"、第三轮的"产品家目录"，
   是同一个病（旧答案留在新 agent 读得到的地方）的三次复发。定位复发点的方法是固定的：
   问"它会从哪儿找"，然后照着它的找法去搜。

### 2026-09-13 · ②：P0.1 落盘接线（prune 侧）+ P3.3 frontmatter + P4.4 相关性闸门

**P0.1 的两半，一半本来就有，一半这次补上。**

1. **工具侧（截断 → 落盘 → 带路径）——核查发现已经在线。** 计划书 §2 末段写的
   "terminal_tool.py 在工具内截断且不带路径、Layer 2 永远拿不到超限输入"是**过时描述**：
   现行代码里 `_BoundedOutputCollector` 落盘全量流（5MB 上限、私有权限、独占创建），
   `terminal_tool.py` 在结果组装时把 spill **原位改写为 strip_ansi + redact 后的净化版**
   （lstat 检查 unlink + 独占重建，防符号链接转移），并在 JSON 结果里带
   `output_total_chars` / `full_output_path` / `truncation_note`（含路径与
   "用 search_files/read_file 找回，别重跑"的指引）。回归锁
   `tests/tools/test_terminal_truncation_spill.py`（5 项）全绿。**教训：这条计划
   项写于初版调研，实施前必须先 grep 现行代码——本次差点把已完成的事重做一遍。**
2. **prune 侧（压缩时摘要里有东西可指）——本次补上。** §2 修正后的定义"输出先落盘，
   摘要带上路径"的另一半：Phase-1 prune 把 >200 字符的旧工具结果换成一行摘要
   （命令/退出码/行数），但内容**从未落盘**，摘要无路可指——模型拿回内容的唯一办法
   是重跑，这正是重复调用循环的机制。salvage 路径（`salvage_grown_transcript`）
   更狠：裸占位符，连摘要都没有。
   **修复**：`agent/context_compressor.py` 新增 `_persist_pruned_tool_content()`——
   经由既有的 Layer-2 原语 `maybe_persist_tool_result`（threshold=0 强制落盘，
   env=None 即宿主侧）写入 `$FULILIAN_HOME/cache/spillover`，在 prune 摘要与
   salvage 占位符后追加 `Full output saved to: <path>`。该行格式**必须**匹配
   `tool_result_storage._PERSISTED_PATH_RE`（`extract_persisted_path` 相应放宽为
   "有 tag 走 tag 路径，无 tag 直接匹配行"——tag 路径行为不变），这样
   `tool_guardrails` 的 result-reference stubbing 也能从 prune 摘要里取回路径。
   落盘内容是**工具结果层**的文本（terminal 侧已经过 strip_ansi + redact），
   不引入新的泄漏面。
   **回归锁** `tests/agent/test_prune_persist_pointer.py`（5 项）：prune 摘要带
   存在的路径且 spill 含全文 / salvage 占位符带指针 / 小结果不 prune 也不落盘 /
   落盘失败仍照常 prune（best-effort 契约）/ 指针行可被 storage 正则取回。
   **已证伪**：在 HEAD worktree 上跑同一测试，3 项指针断言全红（无落盘、无指针）。

**P3.3 完成：** `skills/ctf-knowledge/SKILL.md` 补 YAML frontmatter
（name/description/category/version/author），仓库副本与已安装副本
（`~/.fulilian/skills/`）同步；`GitHubSource._parse_frontmatter_quick` 对两份
均能解析出 name 与 description——7.5 MB 卡片集从此在技能索引里有描述可渲染。

**P4.4 完成：** 两级相关性闸门 + 兜底排序（"噪声比沉默更贵"）。
- `knowledge.py`：① 特异性闸门——查询退化为裸分类词（题面缺失的回退形态，
  如 `"web"`）直接不检索；② 命中下限——结果的 title+snippet 须包含
  ≥ `_wp_refs_relevance_floor`（min(2, max(1, token 数))）个不同查询 token，
  全数不过线注入空。
- `knowledge_retriever.py` `_fallback_token_search`：LIKE OR 无相关性序、裸
  LIMIT 按 rowid 返回的 3 条约等于随机——改为多取候选（max(limit×20, 100)），
  Python 侧按"命中的不同 token 数"降序，附 `score`，title+snippet 零命中
  （只在 content 深处命中）的行过滤。
  **真库验证**（`~/.fulilian/knowledge.db`，2595 行）：`"web"` → 注入空（原先
  返回 cve-2022-21371 等无关篇目）；`"sql注入" OR "union" OR "sqli"` → 命中
  zentao-sqli 等真实相关 WP。**回归锁**
  `tests/fulilian_ctf/test_wp_refs_relevance_gate.py`（12 项），已用 HEAD
  worktree 证伪：HEAD 的 retriever 无评分无过滤，2 项排序/过滤断言全红；
  HEAD 的 knowledge.py 连 `_wp_query_tokens` 都不存在（import 即红）。

### 2026-09-13 · ③：加难 holdout —— 新增 crypto 维度题 crypto-keylayers-01

**动机：** 4 题 holdout 首跑全部一次通过（天花板效应），解出率饱和，
拿它验收任何优化都没有下降空间；且 4 题只覆盖 misc×2 / reverse / forensics，
**crypto·多层推导·逐级依赖**这一维度空缺。

**题面：** 出口网关截获 `vault.export`（341 KB，明文头 + 两份 material blob）与
同主机 `keyserver.dump`（4.8 MB，25,000 条 record）。三层嵌套 + 一条平行诱饵链：
真链 L1 钥 = 指纹命中 record 的 priv；L2 钥 = key2a + key2b 两半拼合（一半在
L1 明文、一半在导出尾部标记之后）；flag 在两层 xor 之后 60% 深度。与既有各题
的靶子不重复：

- **入口不能靠任何关键字定位** —— keyref 指纹 sha256(pub)[:16] 不在盘上任何
  地方，只能对 25,000 条 record 写脚本全量算（4.8 MB，整读必被截断）。
- **同 owner 诱饵 + 平行假链（v2 核心加难）** —— 目标 owner 名下 4 条 record；
  owner-grep 拿第一条会解开导出里**另一份 material blob**，那是一条完整的
  平行链（同样的三层结构、同样以 '# layer 3' 开头的明文），直通一个形似
  flag 的假 token——错误路径貌似成功。头部 `material-sha256-16` 是唯一
  验真锚：sha256(真明文)[:16]。规则全在数据里，不靠猜。
- **key2a 三选一** —— 文档给出可自验判据（与 key2b 组合解出来开头是
  '# layer 3'），不靠猜；断言锁死两条诱饵与 key2b 组合后真的解不开。
- **key2b 藏在导出尾部** —— 必须意识到看一个 341 KB 文件的尾巴；
  拼接口诀写在 L1 明文里。
- **语料无泄漏** —— 真 flag 的 "flag{" 字面在语料 0 次（诱饵 flag 也只在
  密文里），明文区段连 "flag" 都不出现。

诚实说明：xor-sha256 不是真实世界的强加密，考的是**多阶段纪律 + 验真纪律**
（每层的钥匙只在上一步的产物里显形；错误路径产出貌似成功的答案）。scheme
文档全部写在数据里，不靠猜格式——与 chunkconcat 固定 24 字节切块同一取舍：
确定性可复现优先于拟真度，因为它要当前后对照的基准。

**生成器自检含"假难度"防伪断言，且已变异体证伪：** ① flag 埋到 5% 浅处 →
深度断言点火；② 诱饵 priv 换成目标真实 priv → "同 owner 诱饵竟能解开真
blob"点火；③ 诱饵 blob 改用目标 priv 加密 → "目标 priv 竟能解开诱饵 blob"
点火（陷阱是假的）；④ 摘要算成诱饵明文的 → 摘要一致性断言点火。
**生成器字节级确定**（两次生成 sha256 一致）。参考解 9 步自证通过，flag 与
manifest 逐字一致。开发中自检还逮住自己三处错：base64 密文随机含 "flag"
三连字母（泄漏判据改为 flag{ 前缀 + 明文区段）、L1 判据与实际明文头不一致、
改断言时把 `continue` 弄丢导致"诱饵能解真 blob"误报——自检不是摆设。

**probe（真实 agent，各 1 次）：**
- **v1（无平行链）：** 18 次工具调用、约 2 分钟、路径完全正确、一次通过。
  结论：**确定性"诚难题"挡不住强模型**——每步都是自然路径，agent 顺流而下。
- **v2（平行假链 + 摘要验真）：** 诱饵链完整咬合——agent 把**两条链都解开**
  （"Both chains yield layer-3 plaintext"），拿到两个都可提交的 token，
  最后靠头部摘要验真把假链判出去。**30 次 API 打满上限**、36 次工具调用、
  1.04M tokens（prompt 侧 1.02M）、ref_multiple = 3.75×（30/8 步口径），
  耗时 14m40s（v1 的 7 倍）。仍然解出——解出率天花板没顶开——但
  **用满 30 步上限 + 1M token 的单题成本本身就是有效难度信号**：
  在这个题上，任何减少上下文冗余的优化（P0.1 等）都有充足的测量空间。
- 跑批注意：硬闸第 ③ 层会扫 `OUT` 父目录深度 ≤3 的 FLAG，/tmp 下历史一次性
  测试目录（fulilian-trace-test-* 等）会把它顶火——OUT 放到干净父目录
  （如 `~/bench-runs/`）即可；/tmp 的旧文件属其他会话/历史测试，不要去清。

### 2026-09-14 · ④：hard-solve-protocol 配对 A/B —— 送达已证明，经济性为负（结论：默认不启用）

**改了什么（本次提交）：**
- **P6 模型路由**：`resolve_solve_model()` 解析链（显式 `--model` >
  `FULILIAN_CTF_MODEL` > config `ctf.solve_model` > `model.default`），关键字
  `strong` → config `ctf.strong_model`；`strong` 被请求但未配置时**大声降级**。
  路由不做难度猜测（解之前没有可靠的硬度信号），只提供跑批方可拨动的解析链。
  回归锁 `tests/fulilian_ctf/test_resolve_solve_model.py`（8 项）。
- **P1.1 `run_script`**：一次调用串行跑 ≤12 条命令，复用 `terminal_tool`
  （沙箱/拦截/钩子与直调同一条路径），单命令 6K 字符截断、总预算 30K
  超限丢最老。回归锁 `tests/fulilian_ctf/test_run_script.py`（11 项）。
- **hard-solve-protocol 注入机制**：`run_agent._resolve_hard_solve_protocol()`，
  `FULILIAN_CTF_HARD_SOLVE_PROTOCOL=1` 门控，正文唯一来源
  `skills/hard-solve-protocol/SKILL.md`（仓库 + `~/.fulilian` 双副本），
  读不到时**大声报错**——「实验组静默变对照组」必须看得见。回归锁
  `tests/fulilian_ctf/test_ctf_hard_solve_protocol.py`（6 项）。
- **配对 A/B 驱动器** `benchmarks/ctf_hard_protocol_ab.sh` + `ctf_hard_run.sh`
  子集开关 `CTF_IDS` + solve 前硬闸双参调用修复。

**A/B 读数（`crypto-keylayers-01`，两侧各 3 批，归档
`~/bench-runs/protocol-ab-20260914/`）：**

| 量 | ctl | exp | 配对差 |
|---|---|---|---|
| 解出 | 3/3 | 3/3 | 无差 |
| api_calls | 27 / 26 / 20 | 29 / 30 / 23 | **+2 / +4 / +3（3/3 全正）** |
| 合并 ×参考解 | 2.7×（73/27） | 3.0×（82/27） | +0.3×（地板 0.77×，聚合不可归因） |
| 首屏 token | 4,727 / 4,675 / 4,727 | 5,384 / 5,384 / 5,336 | **+657 / +709 / +609（3/3 全正，均值 +658）** |
| 总 token | 956K / 632K / 602K | 1,200K / 998K / 714K | **+244K / +366K / +112K（3/3 全正）** |

**读法（与 A3/A9 结案同一套方法论）：**
- **送达已证明**：配对首屏 +658 tok/调用、3/3 全正、跨度 15% —— 2,777 字符
  正文 ÷ 4 字符/token ≈ 694，量级吻合；loud-error 路径零触发（隔离家 skills
  symlink 链路成立）。
- **经济性为负**：配对 api_calls 3/3 全正（+2~4），总 token 3/3 全正
  （均值 +24 万/solve）。首屏那 +658×~25 次调用只解释 ~1.6 万，**大头是轨迹
  变长** —— 协议让 agent 花了更多步数，没有换来解出率（两侧都 3/3，这道题
  本来就在能力圈内）。「证伪前置/收尾证伪」这类多一步的纪律，在**已经解得出**
  的题上是纯开销；它的目标场景应该是「直觉方向是错的」的题，而本基线
  5 题里 agent 尚未在这些题上反复失败过 —— **判据够不着协议的目标场景**。
- **结论：机制保留（env 默认关 = 零成本），协议正文保留待用，默认不启用。**
  它该被重新评估的时机：出现「聚合 3/3 → 反复解不出」的真难题批时，用同一
  驱动器重跑本 A/B。现在没有那样的题，别为它调协议。

### 2026-09-14 · ⑤：P0.2 solve-state 账本 —— 两轮 A/B 均无收益（结论：默认不启用，机制保留）

**实施形态与计划原文的偏差（有意的）：** 计划写的是「每次工具返回后抽取
事实、每次压缩后重注入」——实施为**只在压缩边界上从被压缩的 turns 一次性
确定性抽取**。理由：被压缩的 transcript 本身就是完整抽取源，省掉每轮 hook
与跨回合状态；与 `_reinject_pruned_skill_markers`（#32106 ghost-skill 防御）
同一条确定性重注入先例，两个 summary 生产点（`_build_static_fallback_summary`
/ `_generate_summary`）都已接线并有接线锁。

**抽取什么（`agent/context_compressor.py`）：**
- terminal：命令 + `exit=` + 首个有效输出行（160 字符）；
- run_script：批量 summary（ran/ok/failed/stopped_at）；
- write_file / edit_file：目标路径 → ok；
- **重复命令记 ×N 不丢** —— 重复本身就是 §3.B 要暴露的信号；
- 上限 40 条保最新（最新的更接近当前状态）。

**门控：** `FULILIAN_SOLVE_STATE_INJECT=1`，默认关 —— 与 hard-solve-protocol
同一条纪律：效果未 A/B 之前不给默认行为。块自带标题与"Do NOT re-run"提示，
走 `_redact_compaction_text`。

**回归锁 `tests/agent/test_solve_state_reinject.py`（10 项）：** env 关 =
summary 原样；命令/退出码/首行；重复 ×3；非零退出可见；上限保最新；
write_file / run_script 形态；无工具调用不追加空块；非 JSON 结果取首行；
**接线锁**（按函数体断言两个 summary 生产点都必须调用——镜像日志"测试绿
≠ 接上了线"的教训）。压缩器相关套件 543 passed，5 个失败**全部先存**
（stash 后同样失败：阈值 floor 3 项 + surrogate 1 项 + setter 一致性 1 项，
与本改动无关）。

**⑤(a) 效果 A/B 第一轮（2026-09-14，segment regime）——探测先于跑批，
一次差点白跑 40 分钟：** 跑批前 probe 发现**跑批根本不触发压缩**——
④ 归档 6 批的最大请求只有 ~32K tokens，离 600K 触发线 20 倍（§9 上一段
写的"crypto 题 1.2M tokens > 600K 线"是**错的**：1.2M 是 27 次调用的
累计 input，不是单请求上下文——累计量永远数倍于上下文，别拿累计量当
触发依据）。机制不触发 = exp 静默退化成对照 = 假实验。为此给
`ctf_hard_run.sh` 加 `CTF_CONFIG_EXTRA` 钩子：播种隔离家后把 config.yaml
符号链接实体化并**深合并** YAML（文本追加会因 YAML 顶层同名键整体覆盖
把真配置 compression 段的原子键顶丢）。两侧同设
`compression.threshold_tokens=20000` + `tail_mode=legacy`（lean tail 对
1M 窗口固定保 25K，比 20K 阈值还大，会结构性抖动；legacy tail = 40%×阈值
= 8K，压后 ~16K，无抖动）。中途验证：ctl-1 压缩触发 3 次、ctl 侧重注入
0 次、exp 侧 2 次（agent.log INFO 响亮日志，为此在 `_reinject_solve_state_section`
加了打点）——**机制在真实跑批里送达了**。exp-1 中途死过一次（上游 502），
补跑 `exp-3r` 修复（OUT 必须嵌套一层：直接放 /tmp 下会被硬闸扫到 /tmp
祖先链上历史残留 FLAG 顶火）。配对读数（usage.json）：

| 对 | ctl api/total | exp api/total | Δapi | Δtotal |
|---|---|---|---|---|
| 1 | 25 / 513,811 | 22 / 749,102 | −3 | +235,291 |
| 2 | 19 / 719,706 | 30 / 1,415,194 | +11 | +695,488 |
| 3 | 20 / 683,739 | 16 / 370,363 | −4 | −313,376 |
| 合 | | | +4 | +617,403 |

同题 total 方差 37 万 vs 141 万，方向不一致 —— **N=3 分辨不出效应**，
点估计偏负。归档 `~/bench-runs/solve-state-ab-20260914/`。

**结构性发现（本轮最重要的产出）：** 生产配置开着 `segment_mode`（每段
冻结摘要）——每次压缩只压**新增段**，重注入账本每次只有 2-3 条（本段
命令），累计态不随摘要滚动，而是分散在各个冻结段里。P0.2 的设计前提是
rolling-merge（每次压掉全部旧 turns，账本覆盖全部历史）。**segment_mode
是本实验的主要混淆** → ⑤(b)：两侧同关 segment_mode 再跑一轮。

**⑤(b) 效果 A/B 第二轮（2026-09-14，rolling-merge regime）——机制回到
设计 regime，结论仍为负：** `CTF_CONFIG_EXTRA` 两侧同设
`threshold_tokens=20000` + `tail_mode=legacy` + `segment_mode=false`
（合并核验过）。全部 6 批压缩触发 2 次、exp 侧重注入 2 次、ctl 侧 0
（响亮检查 ✅，归档 `~/bench-runs/solve-state-ab2-20260914/`）：

| 对 | ctl api/total | exp api/total | Δapi | Δtotal | 解题 |
|---|---|---|---|---|---|
| 1 | 24 / 743,117 | 23 / 972,255 | −1 | +229,138 | 双 ✓ |
| 2 | 18 / 338,425 | 30 / 1,214,582 | +12 | +876,157 | ctl ✓ **exp ✗（打满 30 步）** |
| 3 | 30 / 969,725 | 21 / 411,485 | −9 | −558,240 | 双 ✓ |

**⑤ 结论（两轮合并，默认不启用，机制保留）：** 6 个配对里 Δtotal 4 正
2 负、聚合 +116 万 tokens，exp 侧还多出一次打满步数上限的失败（roll 2
对 2：账本没有救回它，反而可能让它锚定在过期的状态上——无完整命令
轨迹，无法证实，记录为观察缺口）。两个 regime 都没有可辨识的收益，
点估计一致偏负。P0.2 的病（§3.B 压缩后重复推导）在这道题的可测 regime
里**要么不存在、要么账本治不了**——在拿到"压缩后确实发生重复推导"的
实锤轨迹（需要先补观测：solver.log 命令截断 ~20 字符，前缀碰撞让重复
计数不可用）之前，不再投入。代码与测试保留（env 默认关，零开销）；
重估条件 = 出现重复推导实锤 + 重复计数观测就位。

**方法学沉淀（本轮新增）：** ① probe 先行同样适用于"机制会不会触发"——
不只是"线上限够不够"（A9 教训的推广：累计用量 ≠ 上下文占用，差 20 倍）；
② CTF_CONFIG_EXTRA 深合并钩子让 A/B 能操纵**两侧共有**的环境变量
（阈值/tail/segment_mode），把"机制在真实跑批里是否触发"从祈祷变成
构造——但注意它改的是压缩行为本身，两侧必须同设，配对差分才干净；
③ `local a="$1" b="$a/..."` 一行多赋值是先用后赋（bash 踩坑记录）。

### 2026-09-14 · ⑥：P1.2 探针结案 —— 开销可忽略，修的是描述谎言与死旋钮（`022c04c`、`81962eb`）

**原假设（P1.2）：** 模型不知道 cwd/env 持久，每条命令都在重发
`cd X && T="http://..." &&` 前缀 → 持久 shell 能省可观 token。

**探针：** `FULILIAN_LOG_PREFIX_CHARS=600` 宽日志跑 1 题
crypto-keylayers-01（宽日志开关即 ⑤ 期落地的 `08343e0`），提取全部
terminal 命令逐条归类。

**踩坑一（接线锁锁错了对象）：** 首跑镜像仍是 20 字符截断 ——
`08343e0` 只把 `log_prefix_chars` 接进了 `fulilian_ctf/solver.py`
（dispatcher/solve-all 分支），而跑批器用的 `fulilian solve` 走
`fulilian_ctf/cli.py` 的**两处** `run_agent.main` 直调，参数从未传入。
`022c04c` 补接两处。与 2d 镜像"测试绿 ≠ 接上了线"同源：**同一个 env
开关有多条入口路径时，接线锁必须逐调用点锁，漏一条就是静默退化。**

**踩坑二（跑批残留顶火硬闸）：** 重跑时忘了带 `CTF_IDS` → 默认题集
起跑，且硬闸被**上一轮探针残留**在 `/tmp/.p12-out/b1/…/FLAG` 的明文
答案顶火中止。教训与 §10 第 6 条互为镜像：跑批 OUT 下的历史答案对
下一轮跑批是活泄漏，OUT 复用同前缀时必须先清场。

**实测（b3，8 条 terminal / 25 次工具调用，本题解出）：**

| 形态 | 条数 | 说明 |
|---|---|---|
| 自带绝对路径 | 5 | 对 cwd 不确定性天然免疫 |
| `cd <dir> && python3 -c` | 3 | 全是多行内联脚本（相对路径方便），非 env 补偿 |
| env 重导出（`T=… &&`） | **0** | 原假设的主要开销**没有发生** |
| 与上一条同目录的重复 cd | 1（42 字符） | 模型不信 cwd 持久，买保险 |

cd 前缀合计 84 字符 —— 比任何一项已测效应小三个量级，**无 A/B 价值**。
（早前"10/12 条复合命令"的印象出自 20 字符截断期的错误提取，作废。）

**顺带发现（比开销本身重要）：**
1. **`TERMINAL_LOCAL_PERSISTENT` 是死旋钮**：`terminal_tool.py` 收集进
   `local_config`，但 `_create_environment` 的 local 分支直接丢弃
   （`LocalEnvironment(cwd, timeout)` 无持久 shell 实现）—— 设 true
   什么都不改。
2. **工具描述在撒谎**：旧描述无条件承诺"exported environment variables
   persist between calls / activate a virtualenv once per session"，而
   local 后端每次调用都是新 shell —— 模型照做会拿到**空变量**（静默
   错误结果，正确性隐患，不只是开销）。环境说明段只报 OS/user/home/cwd，
   不报持久性，谎言没有任何对冲信息。

**改动（`81962eb`）：** ① 描述改为按后端如实区分：cwd 恒持久；env
持久仅限 ssh/container 后端，local 内联传参（`VAR=… cmd`）；② 死旋钮
与 local 分支各留注释标记诚实缺口；③ 描述回归锁从锁旧谎言改为锁新措辞
（原测试锁的正是假话 —— 回归锁锁措辞时，锁之前先核措辞本身对不对）。

**结案：** P1.2 不做持久 shell 实现 —— ⑤ 的 probe 先行纪律同样适用于
此：没观察到需要状态的轨迹（source venv、跨调用 export 复用）之前，
不建机制。重估条件 = 宽日志里出现状态依赖命令实锤。

**附带归因说明：** 全量 terminal 选集测试 5 failed，经 stash 复跑定位：
2 项分支预存、3 项与并发会话未提交改动/瞬时网络相关，与本提交无关
（22/22 直接相关用例全绿）。

### 2026-09-14 · ⑦：P4.5 金标重构 + P0.5.3 结案 —— 自证基准拆掉后，检索真实水平 20%

**P4.5（修 benchmark）：**

旧金标的自证链条：`build_query(title)` 从目标文档**自己的标题**抽 token 构造
query → 检索器只要不是全坏就必然 top-1 命中自己 → `hit@5 = 1.0（20/20，
18 条 rank=1）`全是对着镜子打分；且 `min_len=3` 把 2 字中文 query（trigram
分词器的真实短板，P4.1）结构性排除在样本外。

**重构（三档，`benchmarks/sampling/build_retrieval_golden.py` 全量重写 +
`benchmarks/eval_retrieval_golden.py` 新评估入口）：**

| 档 | 条数 | 标注依据 | 判定 |
|---|---|---|---|
| smoke | 5 | 仍由标题构造（seed 20260905） | 接线自检：索引在、search() 通。meta 明示 NOT relevance |
| realistic | 10 | **正文内容证据**：生成时逐条 `instr()` 核验期望文档正文确含标注词（如 tcache / 格式化字符串+libc / 维吉尼亚 / 共模 / volatility），核验失败大声退出拒绝生成 | hit@5 —— 标签来自语料，不来自被测系统 |
| robustness | 6 | 敌意 query：`2.31` / 引号注入形态 / 裸操作符词 / 2 字中文"注入" / `()` / 单字符 | 只要求 search() 不抛异常；P4.2 sanitize 下沉后即其回归 |

**诚实基线（`baselines/2026-09-14-retrieval.json`，旧 09-06 基线废弃）：**

- smoke **100%**（全 rank=1）—— 管线是通的；
- realistic **20%（2/10，rank 2 与 4）** —— 抽查证实返回的是同类文档
  （如 tcache query 返回 heap-exploitation 系），但标注文档进不了 top-5：
  这就是检索质量的真实水平，P4.1/P4.3 的改动从此有判据；
- robustness **6/6 不抛异常**（`AND OR NOT NEAR` 返 0 是 sanitize 外空匹配，
  非崩溃）。

**顺带踩坑（FTS5 trigram 表的 LIKE 陷阱）：** `writeups` 是 FTS5 虚拟表，
对 **UNINDEXED 列**（source_path）的裸 `LIKE` 依赖查询计划 —— 走
`VIRTUAL TABLE INDEX 0:L3` 模式时**对存在的匹配错返 0 行**（`+col` 强制
普通扫描或 `instr()` 才对）。生产代码的 LIKE 兜底全打在 `content`（有索引
列）上不受影响；但任何人在这张表上做人工核对都会被它"忽有忽无"地骗。

**P0.5.3（0.60 vs 0.75）结案 —— 本机制下不可测量，维持 0.60：**

- cap 语义是 `threshold_tokens = min(ratio-based, cap)` 的**绝对上限**；
  0.60→0.75 只把自然触发点 600K→700K 平移；
- 跑批峰值 ~32K，30 步 API 上限下轨迹增长永远到不了 600K —— 自然 regime
  里 A/B 没有可分辨项；
- CTF_CONFIG_EXTRA 强制 regime 里，绝对阈值被 `min()` 压成同一值，两侧等价；
- **结论：改了也证伪不了，维持 0.60**（无任何观测到的害处）。重估条件：
  出现 ≥600K 峰值请求的真实轨迹。

**涉及：** `benchmarks/sampling/build_retrieval_golden.py`（重写）、
`benchmarks/eval_retrieval_golden.py`（新增）、`fulilian_ctf/benchmark.py`
`run_retrieval_suite`（tier 感知）、`benchmarks/retrieval-golden.yaml`
（21 条三档）、`baselines/2026-09-14-retrieval.json`、`benchmarks/README.md`。
`tests/fulilian_ctf/test_benchmark.py` 14/14 绿。

**⑦ 附记 · P4.2 sanitize 下沉（2026-09-14 同日落地）：**

`search()` 曾把"传进来的 query 是干净的 MATCH 语法"当调用方契约 ——
docstring 甚至声称支持"短语和布尔操作符"，而实际上**所有**调用方
（knowledge.py 注入、cli 交互查询、benchmark）传的都是裸文本，靠各自的
sanitize 或运气不崩。下沉后：

- `knowledge_retriever.sanitize_match_query()` 在 `search()` 首行生效；
  清洗后为空（纯标点如 `()`）直接返回 `[]`，**不触发索引构建**；
- 对已清洗形态（`"tok1" OR "tok2"`）幂等 —— 先洗后传的调用方不受影响；
- `knowledge.py._sanitize_query` 变兼容壳（单点实现，消灭双份口径漂移）；
- 回归锁 `tests/fulilian_ctf/test_knowledge_retriever.py::TestSanitizeSink`
  6 项（payload 形态不抛 / 垃圾 query 不建索引 / 幂等 / 操作符词丢弃 /
  2 字中文走兜底 / 壳与实现同口径）。

**效果如实报：** realistic 档 20% 持平 —— 现有 miss 是 bm25 相关性问题
（返回同类文档但标注文档进不了 top-5），sanitize 救不了，那是 P4.1/P4.3
的领地。P4.2 的价值在 robustness 档：敌意 query 从"碰巧不崩"变成"结构上
不崩"，且垃圾 query 不再有机会触发索引重建。

**⑦ 附记二 · P4.1 顺势结案 + P8 文档修复（2026-09-14）：**

**P4.1** —— P4.2 落地后其可动半边已自动完成：sanitize 用 OR 连接，
2 字中文 token 在 FTS 层空命中**不再毒化**同查询里的其他项（旧裸文本
隐式 AND 时一个 2 字词能把整条查询打成 0）；纯短词 query 由 P4.4 的
`_fallback_token_search` 兜住（金标 robust-04"注入"返回 5 条实证）。
换分词器（unicode61+分词）是重索引级工程，其增量收益全在 bm25 排序 ——
与 P4.3（检索目标重构）合并看待，单独做无判据意义。**P4.1 就此关闭。**

**P8**（全部四处，逐条对过现行代码）：

| 处 | 旧谎言 | 修正 |
|---|---|---|
| `agent/iteration_budget.py` docstring | 父 "default 500" / 子 "default 50" | 父 `sys.maxsize`（调用方不传即无限）/ 子 250（`DEFAULT_MAX_ITERATIONS`） |
| `tools/delegate_tool.py:1762` 注释 | "default 50" | "default 250" |
| `agent/agent_init.py:627` docstring | "default: 90" | `sys.maxsize`（子代理 250） |
| `agent/context_compressor.py:3976,3978,1562` | "(15)"/"(20)"/"15 turns" | (45)/(50)/"45 turns"，与常量一致 |
| `agent/context_engine.py:121` 基类默认值 | 0.75/3/6 被当成实际运行值 | 加注记：ContextCompressor 覆盖为 0.60/3/7 |
| `fulilian_ctf/knowledge.py inject_ctf_context` | 参数名 `system_prompt`（调用方多传首个 user 消息） | 改名 `prompt` + docstring 如实说明两种实参形态；调用方全走位置传参，零破坏面 |

### 2026-09-14 · ⑧：P5.2 探针 + 机制盘点结案 —— 两个子项都已在，零代码改动

**计划书纪律的又一次兑现（⑤"跑批前先 probe 会不会触发"、④"先测经济性再建机制"）：
P5.2 在动手前先盘点，结果两个子项都不需要新建任何东西。**

**子项 1 · racer 并行假设扇出 —— 已建成、可用。**
`fulilian_ctf/racer.py`（F3-005/006）完整实现：多模型并行竞速、首 flag 停其余
（父进程哨兵轮询 + terminate）、败者死路并入黑板免疫集、Coordinator LLM 降级链
（显式模型 > config `ctf.race_models` > 默认模型，单模型退化为普通求解）。
接线两处：`fulilian solve <id> --race`（`fulilian_ctf/cli.py` 非默认模式统一分流
`SOLVE_MODE_RACE`）与 dispatcher `switch_model` 升级路由（`dispatcher.py:653`
`resolve_race_models()` 排除当前模型取备选，取不到退化为现状重试）。
回归：`tests/fulilian_ctf/test_racer.py` **14 passed**（3.1s）。

**子项 2 · "同一攻击 N 次变体失败交给 runtime 计算" —— 机制已在，计划书该行过时。**
`fulilian_ctf/stopper.py`（F2-004/F2-011）`count_variant_failures(board)` 每轮从
黑板统计同一攻击类变体失败次数（`dispatcher.py:1120` 喂给止损器 `:1136`），
超 `max_variant_failures` 返回 `HYPOTHESIS_REPEATED`，dispatcher 映射为
`switch_attack_class` 强制换攻击类并注入"禁止重复已证死路"块（`dispatcher.py:626`）。
这正是计划书要的"runtime 计算、不让模型回忆"，且带"临门不弃"豁免（已有 flag 不止损）。
回归：`test_stopper.py` + `test_stop_loss.py` **34 passed**（82s）。

**探针 · 失效模式在现有数据中零观测（证据，非直觉）：**
扫描 `~/bench-runs/` 四个存档（protocol-ab / solve-state-ab / solve-state-ab2 /
ctf-hard-crypto）共 270 个日志（12 个不可读）：
- 全部为 **20 字符截断期**日志（宽日志接线 2026-09-14 才落地，见 §9 ⑥）——
  156 个日志出现"完全相同命令"，逐条核验全是 `cd /hom...` / `cd /tmp...` 类
  **截断伪影**（18 条命令 max 长度 10 字符，唯一不同前缀 `find /h...` 1 条），
  不是真实的重复攻击；
- 唯一有数据的宽日志轨迹 = P1.2 探针那一次：8 条命令**全部互异**，无重复攻击。

**结论：** 不建任何新机制。计划书该行写于机制盘点之前——"racer 已有先确认能不能用"
的答案是能用，"交给 runtime 计算"的答案是早已交付。**重估条件**（与 ④⑤ 同款）：
宽日志时代的难题 holdout 轨迹中，观测到 runtime 止损漏掉的重复攻击
（同一攻击类 ≥3 次变体失败未被 `HYPOTHESIS_REPEATED` 拦截、最终时间盒耗尽），
届时再评估是调阈值还是补检测维度；在那之前这是无需求信号的机制。

### 2026-09-14 · ⑨：P2.1 探针结案 —— "为什么"的三重证据全被推翻，零代码改动

**P2.1（规则化自动委派）按 ⑥⑧ 的纪律先 probe 后动手，probe 结论 = 不建机制。
这也是"先 grep 现行代码"教训的第三次兑现（前两次：P0.1 工具侧早已在线、
P5.2 runtime 检测早已交付）。**

**证据一 · §3.F 的数字采错了路径。** `delegate_task` 不在 `ctf_solve` 工具面
（`toolsets.py:637`：verify_flag / checkpoint / generate_writeup / compile_check /
run_script + includes terminal/file/web/vision）—— CTF solver **物理上无法委派**。
§3.F 的 `15 / 13,018` 全部来自 chat 路径。原语缺席时"从未发生"是必然，
不是"模型不自觉"的行为证据。**一般化：没调用 ≠ 不自觉 —— 先确认原语在不在
目标路径的工具面上，再谈行为。**（"测试绿 ≠ 接上了线"的对偶命题。）

**证据二 · 失效模式的体量已被 P0.1 砍掉。** 工具内 20K 截断→落盘→指针
（用户配 20000）；全部 CTF 跑批 spillover 触发 **0 次**（`~/.fulilian/cache/spillover`
仅 2 个 09-04 chat 时代文件）；跑批峰值 ~32K tok/请求 vs 600K 压缩线（§9 ⑤⑦）。
当前 5 题 holdout 上不存在"噪声挤爆主上下文"可缓解。

**证据三 · runtime 强制版被经济性与正确性双否决。** 委派 = 第二 agent loop
（自带静态前缀 + 独立轨迹），在压缩从不触发的 workload 上是纯开销 —— 与 ④
"证伪前置纪律在已解出的题上是纯开销"同构。正确性侧，计划书自己的前置事实
成真：规则拦截无法为双向隔离的子代理构造充分任务上下文，"输出>N 行/耗时>T 秒"
分不清"过程长结论短"与"父代理下一步正需要这份完整输出"。

**附带发现（如实记录，不修）：** 用户 config 纪律第 3 条"嘈杂工作交给子代理"
经 A10 已**送达** CTF 路径，但工具面上没有 `delegate_task` —— **送达但不可
执行**，是 A2 死配置 / A10 静默失效同族的第三种形态（前两种：配置没人读 /
配置读了不生效；这一种：指令送达、原语缺席）。`delegate_task` 的 schema 是
动态拼装的（`_build_top_level_description` 541 字符 + tasks 参数 73 字符），
加回 `ctf_solve` 固定开销仅 ~200 tokens 且无 `valid_tool_names` 门控块连带
（`model_tools.py:603` 只做描述内提及过滤）—— 但无收益场景时它只是又一个
④ 式可选项，与 P2.1 一并挂起。

**重估条件（唯一能翻案的信号）：** 难题轨迹中压缩真实触发（≥600K 峰值）或
spillover 反复触发，且体量可归因于"过程长结论短"类命令 —— 届时先量
"把 delegate_task 加进 ctf_solve（模型可选）"这一档，runtime 强制版仍需先
解决任务上下文构造问题再评估。

### 2026-09-14 · ⑩：P4.3 专题段索引落地 —— 探针改了形状，评测守住诚实（`topic_segments.py`）

**探针先推翻了原设想的一半。** 计划书设想"代码去读 `.idx.md`"，动手前抽检
108 个行段：**35 段（32%）行号与实际文档不符**（如「宽字节」实际在 SQL.md
L928，idx 写 L450——读到的会是 sqlmap 配置）。idx 是与文档标题结构脱节的
手工缓存，"没有任何代码读它"反而救了这个库。**落地形状改为：运行时从文档
`#{1,3}` 标题自建索引**（13 专题文档 / 906 段，mtime 缓存自动失效），永不
漂移。语料库本体不动（那是手工维护内容，idx 陈旧问题如实记录于此）。

**实现要点（`fulilian_ctf/topic_segments.py` + `knowledge.py` 注入块）：**

- 匹配：内存 token 子串重叠（906 条规模不值得上 FTS5，避开 trigram 的
  2 字 CJK 坑——§3.E 教训直接沿用）；注入为「专题速查」块（lessons 之后、
  WP refs 之前），`Read <path> offset=<行号>` 直达指针，复用语料库自身的
  按需分段读取约定。
- 三重闸门（调试中各抓出一个真实误报）：① sanitize 后查询串里的**字面
  操作符**（`"or" OR "and"`）混进查询 token——首跑即复现（`过滤or and
  xor not 绕过` 靠 or 攒命中数压过真正的宽字节段）；② 资格规则 = ≥2 个
  不同 token 或单个 ≥3 字具体词，2 字泛词单独不入选；③ ASCII 词边界，
  `ida` 不得命中 `IDAT`。
- 特异性闸门与 `_format_wp_refs_block` 同形：裸分类词回退形态直接沉默。
  域外分类（pwn/crypto/reverse 无专题库）正确沉默。

**同源评测（P4.5 金标 realistic 档，判据不换库不换题）：** web 覆盖域
hit@2 = **3/4 = 75%**（miss 的一条"java 反序列化"命中 PHP 反序列化专题，
跨语言但思路相关）；域外 6 条全部沉默而非硬凑；全档 3/10 vs WP 检索基线
hit@5 = 20%。正文派生的敌意评测（query 抽自正文代码行）doc-level top2 仅
29% —— 如实记录：该索引匹配的是**技术名形态的查询**（题面/解题者视角），
不是任意正文片段。

**验证：** 15 项新测试绿（合成 KB，含缓存失效、闸门、指针格式、幂等）；
mutation 测试 3/3 变异被抓（资格闸门 / 操作符剔除 / 词边界——其中操作符
变异首测漏网，补了判别性 fixture 后复测抓获）；知识层既有 114 项测试绿；
golden 三档无回归（smoke 100% / realistic 20% 持平 / robustness 6/6）；
全量套件 814 passed + 1 failed，该失败（test_solve_modes JSON 解析）经
stash 对照确认为**既有失败**，与本条目无关。

**一般化教训：** 探针不仅验证"要不要做"，还会改"做成什么形状"——原设想
消费手工索引，探针证明手工索引本身不可信，改为结构自证（从标题重建）。
另外 idx 内容含文档里不存在的标题（凭空总结），提示人工索引与文档是
两个会各自漂移的事实源，能从结构重建的索引不要手工维护。

### 2026-09-14 · ⑪：P6 试水 A/B —— GLM-5.3 三题全解、token 减半，api 持平（试水级，n=1）

**规模（用户选定）：** 最难题 3 道（按 api_mean：crypto-keylayers-01 24.3 /
misc-chunkconcat-01 21.3 / reverse-obfchain-01 21.3）× 双臂 × n=1。
对照臂在**当前 HEAD 重跑**（P4.3 注入已在 HEAD，旧基线读数不同口径）；
实验臂 `FULILIAN_CTF_MODEL=strong` → GLM-5.3。双臂解析横幅均已验证
（ctl → DeepSeek-V4-Flash / exp → GLM-5.3），跑批器 env 自然传播。

**结果（baselines/2026-09-14-ctf-p6-ab-{ctl,strong}.json +
2026-09-14-ctf-p6-ab-strong-ark-obfchain.json）：**

| | ctl（DeepSeek-V4-Flash） | exp（GLM-5.3） |
|---|---|---|
| 解出 | 3/3 | **3/3** |
| api_calls | 28/21/15 = 64 | 30/16/22 = 68（+6%，噪声地板 1.40× 内，持平） |
| 总 token | 2,284,176 | 1,241,448（**−46%**） |
| 缓存命中 | 70–81% | 91–94% |
| 路径经济性 | 3.2× | 3.4×（持平） |

**中途的供应商切换（用户指示）：** scnet.cn 首跑 GLM-5.3 撑到第三题时
`Token Plan quota has been exceeded`（429，前两题烧 ~77 万 token 后额度
见底），当天补跑复测仍 429。用户改指 **ark（火山引擎
`ark.cn-beijing.volces.com/api/plan/v3`）**：probe 证实 ark 同时供
`GLM-5.3`（原名直通）与 `DeepSeek-V4-Flash`（服务端实际
`deepseek-v4-flash-ga-260731`），故顶层 `model:` 块全局切到 ark
（备份 `config.yaml.bak-provider-switch-20260914`；fulilian 供应商是全局
配置，无按模型路由机制），双臂模型名解析均不变。**可比性注记：** exp 的
crypto/chunkconcat 读数来自 scnet 供栈、obfchain 来自 ark 供栈——模型名
同、供栈不同，逐题对比时把这个混杂因素带上；ctl 将来若重跑，其 DeepSeek
服务端快照也已变成 ark 的 ga-260731，与 9-11 基线（scnet）跨供栈。

**试水结论：** GLM-5.3 三题全解、api_calls 持平（噪声地板内）、总 token
约省一半、缓存命中高 10–20 个百分点——**正向信号，但仍不足以支撑改默认
路由**（n=1 试水）。运营发现同样成立：scnet GLM-5.3 token plan 额度撑不满
一个 3 题 hard 批，扩量前要么解决额度要么就用 ark。

**方法注记：** 裸 curl 探配额会 401（鉴权构造与 fulilian 内部不同），探测
配额状态最可靠的方式就是直接补跑——429 会在自证通过后几秒内复现，代价
极小。不同模型的 token 数跨模型可比作成本代理，但 tokenizer/定价不同，
"减半"只作方向性读数。

### 2026-09-14 · ⑫：天花板效应破题 —— 第六维 web-tokenforge-01 把靶子拉回能力离散量

**任务（用户指定）：** 难题 holdout 一次通过的天花板效应——把题加难到
**会失败**，靶子从经济性连续量回到**能力离散量**（解出率/flag 正确率）。

**设计（`web-tokenforge-01`，category web，第六个能力维度：协议伪造 /
密码原语实现保真度）：** 对着一个不给你钥匙的验证器伪造凭据。
`sig = sha256(SECRET||msg)`，SECRET（16 字节）只在部署环境；hashlib
没有从中间状态续算的接口 → 唯一正路是自实现 SHA-256 压缩函数做 hash
长度扩展。失败模式是**实现保真度**（padding/位长/状态/glue 块界任何
一处错都通向乱码）——与既有 5 题（输出纪律×2/调用图/交叉判断/多层
推导）全部正交。scheme 全在数据里（policy.md + 流量里的未遂伪造记录），
不靠猜格式；防伪断言锁死：诱饵库 recovery.enc 用流量里现成的旧 sig
就能完整解开、内含形似 flag 的假答案。

**迭代纪律（诚实记录）：** v1（单层）n=1 试跑被默认模型 26/30 步解出
（931K tok）→ 按任务目标做**一次**注册前加难：v2 = 链式双层 + 跨块
（伪造 admin sig 只打开含 root 续签说明的 admin 层；root 会话要从
**自己伪造出的 admin sig** 注入续算，59 字节续写段强制 data+padding
跨两个 64 字节块）。只迭代这一次，corpus 随首次 commit 冻结，
`git log benchmarks/fixtures-hard/` 仍只有新增。

**v2 结果（n=3，默认模型 DeepSeek-V4-Flash@ark，
`baselines/2026-09-14-ctf-web-tokenforge-01-pilot.json`）：**

| 次 | 解出 | flag 对 | api（上限 30） | token |
|---|---|---|---|---|
| 1 | ✓ | ✓ | 29 | 1,345,637 |
| 2 | ✓ | ✓ | 30 | 1,199,606 |
| 3 | ✓ | **✗（吃了诱饵）** | 30 | 1,546,038 |

- **能力离散量恢复：flag 正确率 2/3** —— 六题里第一道真正"会失败"的题。
- **失败模式与设计完全对表**：第 3 次 agent 的扩展实现自检"verified
  correct"却打不开 root 层（~30 个候选 sig 全乱码——没吃透"注入态已把
  admin 消息自己的终 padding 吸收进块界"这一层），预算耗尽后向诱饵库
  投降，假 flag 还被 `verify_flag` 确认。两道独立保真度闸门 + 30 步上限
  的联合作用，正是"会失败"想要的结构。
- 三遍全部贴 29–30/30 上限、token 均值 1.36M（六题最重，第二名
  keylayers 约一半）——本题同时是 P0.1 效果重估（峰值 ≥600K）的首个
  真实触发源候选。
- 噪声地板 0.09×（n=3 自身摆动）；×参考解 2.64–2.73×。

**方法发现：** ① runner 契约要求 `make_data.py --out <dir>`（初版漏了，
语料误写进 fixture 目录，自证 `FileNotFoundError` 提醒）；② 参考解
自证的价值再次兑现——v2 参考解自己在 `absorbed2` 上踩出 struct.error
（把 88 当块界，正确值 128），与第 3 次 agent 的失败点同源，修参考解的
过程就是验题过程；③ 采数纪律：同一父目录下复用 OUT 会被硬闸拦（上一轮
FLAG 在下一轮 work_dir 的祖先链上）——换独立父目录即过，硬闸工作正常。

**结论：** ⑪ 遗留的"靶子回到离散量"落账。manifest/IDS 已同步
（crypto-keylayers-01 此前漏登记 IDS 一并补上）；该题验收从此以
flag 正确率为主指标、路径经济性为辅。P7（降级项）若复启用，本题是
现成的判据载体。

## 10. 当前状态

**分支 `ctf-opt` 已推送 origin 至 `567ad3e`（①-⑪ 全部落账）。**

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
| 基准 | **答案围堵二轮：跑批期间答案不在盘上（暂存/还原 + stdout 只打哈希）** | `benchmarks/ctf_hard_run.sh` `_seal`/`_seal_tree`/`_unseal*` |
| 基准 | **答案围堵三轮：`FULILIAN_HOME` 每题一个家 + 真身指纹不变量** | `benchmarks/ctf_hard_run.sh` `_seed_home`/`_home_fp`、`--seed-home` 自检模式 |
| 测试 | **答案泄漏围堵回归锁（16 项；含变异体逐条证伪）** | `tests/fulilian_ctf/test_ctf_holdout_isolation.py` |
| 基准 | **难题 holdout 干净基线** | `benchmarks/baselines/2026-09-11-ctf-hard-holdout.json` |
| 基准 | **路径经济性指标（C1b，消费 `solve_reference_steps`）** | `benchmarks/ctf_path_baseline.py` `analyze()` / `print_aggregate()` |
| 基准 | **探针题 `misc-chunkconcat-01`**（4 题 holdout） | `benchmarks/fixtures-hard/misc-chunkconcat-01/` |
| 基准 | **v2 跑批基线（4 题，含经济性）** | `benchmarks/baselines/2026-09-11-ctf-hard-holdout-v2.json` |
| 基准 | **③ 加难题 crypto-keylayers-01（crypto·多层推导维度，4→5 题；生成器自检已变异体证伪）** | `benchmarks/fixtures-hard/crypto-keylayers-01/`、`manifest-ctf-hard.yaml` |
| 代码 | **P6 模型路由 `resolve_solve_model`（解析链 + `strong` 关键字 + 大声降级）** | `fulilian_ctf/solver.py`、`fulilian_ctf/cli.py`、`fulilian_ctf/__init__.py` |
| 测试 | P6 路由回归锁（8 项） | `tests/fulilian_ctf/test_resolve_solve_model.py` |
| 代码 | **P1.1 `run_script` 批量命令工具（复用 terminal_tool 同一路径）** | `tools/ctf_solve.py`、`toolsets.py` |
| 测试 | run_script 回归锁（11 项） | `tests/fulilian_ctf/test_run_script.py` |
| 代码 | **hard-solve-protocol env 门控注入（读不到大声报错）** | `run_agent.py` `_resolve_hard_solve_protocol()` |
| 文档 | **hard-solve-protocol SKILL.md（仓库 + `~/.fulilian` 双副本）** | `skills/hard-solve-protocol/SKILL.md`、`~/.fulilian/skills/hard-solve-protocol/SKILL.md` |
| 基准 | **协议配对 A/B 驱动器 + `CTF_IDS` 子集跑批 + 硬闸双参修复** | `benchmarks/ctf_hard_protocol_ab.sh`、`benchmarks/ctf_hard_run.sh` |
| 基准 | **④ 协议 A/B 归档（ctl 2.7× / exp 3.0×，经济性为负，默认不启用）** | `~/bench-runs/protocol-ab-20260914/`、`baselines/2026-09-14-ctf-protocol-ab-ctl.json`、`baselines/2026-09-14-ctf-protocol-ab-exp.json` |
| 基准 | **⑪ P6 试水 A/B（GLM-5.3 vs ctl，n=1，2/2 有效题 token −55%）** | `baselines/2026-09-14-ctf-p6-ab-ctl.json`、`baselines/2026-09-14-ctf-p6-ab-strong.json` |
| 代码 | **P0.2 solve-state 账本（压缩边界确定性抽取 + 重注入，env 门控默认关）** | `agent/context_compressor.py` `_extract_solve_state_entries` / `_reinject_solve_state_section`（两个 summary 生产点接线） |
| 测试 | P0.2 回归锁（10 项，含双生产点接线锁） | `tests/agent/test_solve_state_reinject.py` |
| 代码 | **P1.2 `FULILIAN_LOG_PREFIX_CHARS` 镜像日志参数预览宽度（全调用点接线）** | `fulilian_ctf/solver.py` `_log_prefix_chars_from_env` + `fulilian_ctf/cli.py` 两处 `run_agent.main` 直调补接（`08343e0`+`022c04c`） |
| 测试 | log_prefix_chars 回归锁（4 项） | `tests/fulilian_ctf/test_log_prefix_chars.py` |
| 代码 | **P1.2 terminal 描述按后端如实声明 env 持久性 + 死旋钮标记** | `tools/terminal_tool.py` `TERMINAL_TOOL_DESCRIPTION` + `local_persistent`/`_create_environment` local 分支注释（`81962eb`） |
| 测试 | 描述回归锁（锁新措辞，原锁锁的正是旧谎言） | `tests/tools/test_terminal_tool.py` `test_terminal_schema_advertises_persistent_env_state` |
| 代码 | **CTF_CONFIG_EXTRA 深合并钩子 + solve-state 重注入响亮日志（⑤ 基础设施）** | `benchmarks/ctf_hard_run.sh` `_apply_config_extra`、`agent/context_compressor.py` reinject INFO 日志（`0704f4b`） |
| 基准 | **运行日志可信性检测（`log_issue`）** | `benchmarks/ctf_path_baseline.py` `analyze()` / `print_table()` |
| 代码 | **运行日志镜像（根治 §10 第 3 条）** | `fulilian_ctf/solver.py` `solver_evidence_stream` / `_TeeStream`；接线于 `cli.py:_run_solve_once`、`solver.py:_default_solver_impl` |
| 测试 | 镜像日志回归锁（8 项，含"agent 覆盖后镜像仍完整"与接线锁） | `tests/fulilian_ctf/test_solver_log_tee.py` |
| 基准 | **对照模式 `--compare`**（把噪声地板真正用起来） | `benchmarks/ctf_path_baseline.py` `compare_archives()`；档案 `baselines/2026-09-12-ctf-a9-compare.json` |
| 基准 | **A3+A9 对照跑（n=3，8ada9e6 + 两个 revert）** | `baselines/2026-09-12-ctf-ctl-a3a9-revert-n3.json` |
| 代码 | **P0.1 prune 侧落盘 + 指针** | `agent/context_compressor.py` `_persist_pruned_tool_content`（prune + salvage 两处接线）、`tools/tool_result_storage.py` `extract_persisted_path` 放宽 |
| 测试 | P0.1 prune 指针回归锁（5 项，已对 HEAD 证伪） | `tests/agent/test_prune_persist_pointer.py` |
| 代码 | **P4.4 相关性闸门 + 兜底排序** | `fulilian_ctf/knowledge.py`（特异性闸门 + 命中下限）、`fulilian_ctf/knowledge_retriever.py`（`_fallback_token_search` 评分） |
| 测试 | P4.4 闸门回归锁（12 项，已对 HEAD 证伪） | `tests/fulilian_ctf/test_wp_refs_relevance_gate.py` |
| 文档 | **P3.3 ctf-knowledge frontmatter（仓库 + 已安装双副本）** | `skills/ctf-knowledge/SKILL.md`、`~/.fulilian/skills/ctf-knowledge/SKILL.md` |
| 代码 | **① API 客户端默认读超时收口** | `agent/process_bootstrap.py` `_client_default_read_timeout`（`8f90789`） |
| 测试 | 读超时回归锁（7 项，含 SDK 采纳端到端 pin） | `tests/agent/test_keepalive_client_read_timeout.py` |
| 基准 | **P4.5 检索金标 v2（三档：smoke/realistic/robustness）+ 诚实基线（realistic 20%）** | `benchmarks/sampling/build_retrieval_golden.py`（重写）、`benchmarks/eval_retrieval_golden.py`、`retrieval-golden.yaml`、`baselines/2026-09-14-retrieval.json` |
| 代码 | **P4.2 sanitize 下沉（search() 内不变量 + 空 query 不建索引）** | `fulilian_ctf/knowledge_retriever.py` `sanitize_match_query`、`fulilian_ctf/knowledge.py`（兼容壳） |
| 测试 | P4.2 sanitize 回归锁（6 项） | `tests/fulilian_ctf/test_knowledge_retriever.py` `TestSanitizeSink` |
| 文档 | **P8 文档谎言清理（迭代预算/压缩器注释/注入参数名）+ P4.1 结案** | `agent/iteration_budget.py`、`tools/delegate_tool.py`、`agent/agent_init.py`、`agent/context_compressor.py`、`agent/context_engine.py`、`fulilian_ctf/knowledge.py` |
| 代码 | **P4.3 专题段索引（运行时标题自建，不消费手工 idx）** | `fulilian_ctf/topic_segments.py`、`fulilian_ctf/knowledge.py`（`_format_topic_segments_block`） |
| 测试 | P4.3 回归锁（15 项；mutation 3/3 被抓，含操作符变异的判别 fixture） | `tests/fulilian_ctf/test_topic_segments.py` |
| 文档 | 本计划书 | `docs/ctf-agent-optimization-plan.md` |

**已验证：** A5 —— 修复前 3/3 瞬间失败（HTTP 400，退出码 0）；修复后
**3/3 解出、3/3 flag 与 manifest 逐字一致**（§1.3）。

**已验证：** **A9/P0.5.4** —— 对照跑 3/3 解出、flag 逐字一致，
**首屏 prompt 每题一致地降 3,160–3,235 tokens**（§1.6）。
n=3 配对复测 **−3,305 tokens/调用**（12/12，跨度 1.1%），难题 holdout 两侧
**12/12 解出、flag 逐字全对**；**质量无损**（§9「A3+A9 对照跑结案」）。
`tests/test_toolsets.py` 29 项、`tests/agent/test_skip_background_review.py`
+ `tests/fulilian_ctf/` 683 项全绿。

**已验证：** **A10**（`5ec2cc5`）—— 合并 prompt 1,466 字符；真跑
`misc-morse-01` 解出且 flag 正确，首屏 +395 tokens 证实 overlay 送达（§9 A10）。
**送达与遵守均已证明** —— 难题 holdout 上 **3/3 生成 `ctf-notes.md`**
（easy 单点上曾是 0/1，现已被 n=3 覆盖）。缓存代价也已排除：runs 命中
81.6/81.4/72.8%，与无 overlay 基线同量级。

**已验证：** **答案泄漏围堵（`4d7067c` + 本次提交）** —— 第二轮修掉的三处
（参考解 stdout / 跑批器自己 stdout 的 34 处明文 / 跑完那题的 work_dir）与第三轮修掉的
两处（产品家目录 `~/.fulilian` 的 traces+learning+cache / 编排者会话记录）见 §9。
第三轮做了**真实冒烟**：单题 `misc-bigscan-01` 带 `FULILIAN_HOME` 跑通（`rc=0`、
flag 已写），trace 与 learning 落在隔离家，**真身 `traces/` 指纹与 `learning.json`
mtime 均未变**。回归锁 16 项全绿，并用四个变异体逐条证伪。
**尚未关上的（写出来，不假装）：** `$SEALED` 用 gzip 而 **gzip 不是加密**；
`~/.claude/projects/*.jsonl` 里的 flag 由 preflight 报出但不清除；fixture 是确定性的，
flag 明文本来就在仓库里（`manifest-ctf-hard.yaml`）。这三条都要靠"别让 agent 够到"解决，
不是靠跑批器。

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

**A3 的效果：已查清，结论是「省 0，且测不到」。** 见 §9「A3 的账算错了」。
`solve -p` 上那条 fork 被创建后在发出任何 API 调用前就随进程退出销毁，
日志里开始行与结束行**成对缺失**；而它的消耗即使发生也只走
`session_model_usage`，不进 `usage.json`。**不要再为 A3 安排对照跑** ——
按原设计跑（只翻 `skip_background_review`）会得到假的 0（A9 已把门控拆了），
按修正设计跑（同时回退 A3+A9）测到的也全是 A9 的分量。
> **已照修正设计跑完（2026-09-12，n=3）：** 撤掉 A3 无可分辨变化，与上述
> 代码级结论一致。而这一跑顺带说明**判据本身要选对**：A9 的分量在整轮聚合
> 里也读不出来（Δ 落在逐批地板以内），却能被配对量首屏前缀一次性测出
> **−3,305 tok/调用**（12/12，跨度 1.1%）。见 §9「A3+A9 对照跑结案」。

**仍未验证：** A2（删死配置）的效果。它删的是一个**没有读取点**的键，
按定义效果为 0 —— 剩余价值只是不再误导读者。

**阻断性发现已清除：** §3.D2 的 argparse `dest` 冲突（`bbf054d`）。
在此之前，"CTF 层是否存在缺陷"这个问题在观测上无法回答——每次
`solve -p` 都在无声地跑另一条路径并以退出码 0 结束。

**已知未处理（按优先级）：**
1. ~~**CTF API 路径无读超时**~~ —— **已修复（2026-09-13）**。复查发现主循环流式路径
   本就有三层防护（120s httpx 读超时 + 180–300s stale 看门狗 + 熔断，
   `chat_completion_helpers.py` `_open_stream` / stale 轮询）；真正无界的层在
   **客户端默认层**：`build_keepalive_http_client` 造的 httpx 客户端 `read=None`，
   而 openai SDK 在调用方未显式传 `timeout` 时**整体采纳** `http_client.timeout`
   （`SyncAPIClient.__init__`）→ 一切不带 per-request timeout 的调用点
   （aux 调用、async 压缩客户端、未来新增点）都是无限读。
   **修复**：`_client_default_read_timeout()` + `FULILIAN_CLIENT_READ_TIMEOUT`
   （默认 600s = SDK 自身读预算；`<=0` 还原无限读）。
   主循环 120s / aux 120s 等 per-request 预算逐请求覆盖，不受影响；
   回归锁 `tests/agent/test_keepalive_client_read_timeout.py`（7 项，含 SDK 采纳
   端到端 pin；已对改动前源码证伪：旧码 read=None 确实会红）。
2. `test_json_mode_emits_start_and_result` **先存的失败**（HEAD 上同样失败）。
3. **运行日志落在 agent 可写的地盘里，被 agent 自己覆盖** —— 原描述
   「跑完不立刻采集就丢数据」**低估了它**。真实形态在
   `misc-chunkconcat-01` 上实测到了：agent 用 `write_file` 把 `solver.log`
   覆盖成解题报告，**就发生在跑的过程中**，跑批完立刻采集也拿不到。
   → 检测（`5d55fe7`）：采集器出 `log_issue`，不可信行工具面置 `—` 并打 ⚠️，
   汇总把工具总数标注为下界 —— 不再把"数据没了"静默读成"零浪费"。
   → **根治（镜像日志）**：`solver_evidence_stream` 认
   `FULILIAN_SOLVER_LOG_MIRROR`，同一份字节额外写一份到指定路径；跑批器把它
   指到 `$OUT/_mirror/`（solve 目录之外）。**刻意只增不改**：
   `work_dir/solver.log` 原地保留，dispatcher 的增量扫描、replay/writeup、
   racer / multi_agent 的子目录证据全部不受影响 —— 移动日志会打断这些消费者
   （`dispatcher.py:1005,1096` 按字节偏移追增长）。
   采集器加 `--mirror-dir`，有镜像就优先采信，并**单独**报 work_dir 那份是否
   被扰动（测量有效、产物损坏，两件事分开说）。
   → **第一次改错了地方，值得记下来**：镜像最初只加在 `tee_solver_log` 上，
   而**它没有生产调用点**（grep 全仓只有测试引用）。默认 solve 路径实际走的是
   `cli._run_solve_once`（`solve -p`，即 holdout 路线）与
   `solver._default_solver_impl`（`solver_worker`/race 路线），两者各自裸开
   `open(log_path, "w")`。当时测试 4 项全绿、机制却一次都不会触发 ——
   **测试绿不等于接上了线**。现已抽出 `solver_evidence_stream` 供两处共用，
   并加一条**接线回归锁**（按函数体断言两处不许再裸开日志；已用改动前的源码
   验证过它确实会红）。
   → **仍存在的边界**：`--race` / `--multi-agent` 的多 agent 子目录日志
   （`multi_agent.py:338` 等）未接镜像；环境变量不设时行为完全不变。
4. ~~**没有难题 holdout**~~ —— **已解除**（`9f1caf1`），**2b 已实施**
   （`c0746cd` 经济性指标 + `ce3cb11` 第 4 题 + `5d55fe7` 日志可信性）。
   当前 **5 题**（2026-09-13 新增 crypto·多层推导维度 `crypto-keylayers-01`，
   `solve_reference_steps: 8`，生成器自检含假难度防伪断言且已变异体证伪），
   旧 4 题 v2 跑批 4/4 一次通过 → **天花板效应仍在**，但可用信号已经落地：
   `ref_multiple = api_calls / solve_reference_steps`，v2 为 **2.9×**。
   → 新题是否真的把天花板顶开，以 probe 结果为准（别推算）。
   → ~~**剩余待办是 n≥3 采样**~~ —— **已做（2c 的 n3 基线 + A3+A9 对照跑，
   两侧各 3 批）。** 得到两个结论：① 逐题 ×参考解 的地板 **1.40×**（最差题），
   合并指标地板 **0.07× 量级**；② **n≥3 也不够** —— 4 题 × 3 批仍分辨不了
   A9 的效应（Δ +0.40× vs 地板 0.80×）。**加样本不是万能解，选统计量才是。**
   A9 最终靠**配对量首屏前缀**一次测出（−3,305/调用，跨度 1.1%）。
   → **当前真正的边界**：`--compare` 的合并判据要求**每侧 ≥2 个跑批**，
   否则报"采样不足"而不是 0；逐题判据另要求该题两侧各 ≥2 次。跑批成本
   是主要约束（4 题 × 3 批 ≈ 30 分钟/侧）。
5. **`--compare` 的「改动前/改动后」是人工标注，工具查不出你标反了。**
   已加 `_chronology_warning`：`generated_at` 显示「后」早于「前」时报警
   （本次真实对照就触发了 —— 基线的日期比对照早，我按 A9 的方向传参，
   字面上确实"反"了）。但**两侧代码到底差了什么，归档记不下**，必须自己
   `git diff` 核对后写进结论；报告里已把这句话印出来。
   → 顺带记一个未查项：§1.6 的 −3,186 与复测的 −3,305 **差 119（3.7%），
   归属未查**。两种口径都不影响结论，但要精确报账得同树同题集量。
6. **跑批目录也在 agent 的可写范围内**（与第 3 条同源）。`misc-chunkconcat-01`
   上实测：agent 把分通道中间产物写到 work_dir 的**上一级** `$OUT/out/chan*.bin`，
   采集器按目录名当成第 5 道题，把解出率从 12/12 拉成 12/13。
   → 有 `--manifest` 就按 manifest 认题，排除项**点名报出**（"被排除"极易
   被读成"这题没跑"），并落档 `excluded_non_fixture`。**做对照跑必须给
   manifest**，否则明说"分不出题目与杂物"。
7. ~~**`config.yaml` 规则 1 的「并同步 memory」不可执行**~~ —— **已关闭**
   （用户 2026-09-11 选择改 config 文字）。「，并同步 memory」已删，
   overlay 429→418 字符，备份 `~/.fulilian/config.yaml.bak-20260911-rule1`。
   A10 的遵守率也已在难题 holdout 上证明（3/3 生成 `ctf-notes.md`）。

**下一步（已按 §1.4 重排）：**

| 顺序 | 项 | 理由 | 状态 |
|---|---|---|---|
| 1 | ~~**P0.5.4** 删 `memory`+`skill_manage`~~ | 实测 **−3,186 tok/次调用**（比预估的 1,408 大一倍多，见 §1.6）；n=3 配对复测 **−3,305**（12/12，跨度 1.1%），两种口径都不改变结论 | **✅ 完成** |
| 0 | ~~**A10** config overlay 接入 CTF 路径~~ | 用户手写的纪律此前静默失效；已在用户选择下实施 | **✅ 完成** |
| 2 | ~~**难题 holdout（长扫描 / 反编译转储 / 爆破日志）**~~ | 已建成并跑通（`9f1caf1`）；A10 遵守率据此证明 3/3 | **✅ 完成** |
| 2b | ~~**路径经济性提为主指标 + 加更硬的探针题**~~ | 已实施：`c0746cd` 指标 + `ce3cb11` 第 4 题 + `5d55fe7` 日志可信性；v2 4/4 解出、经济性 2.9× | **✅ 完成** |
| 2c | ~~**经济性采样 n≥3**~~ | 已跑 4 题 × 3 次：**12/12 解出、经济性 3.6×、噪声地板 1.40×** —— 从此"有没有效果"有判据；n=2 时那个 2.00× 地板是高估 | **✅ 完成** |
| 2d | ~~**`solver.log` 移出 work_dir**~~ | 已实施为**镜像日志**（只增不改）：`FULILIAN_SOLVER_LOG_MIRROR` + 采集器 `--mirror-dir`。移动会打断 dispatcher 按偏移追增长的消费者，故取镜像 | **✅ 完成** |
| 3 | ~~**A3 对照跑**~~ | **已回答，且答案推翻了 A3 的收益主张**：`solve -p` 上 fork 被创建后**在发出任何 API 调用前**就随进程退出被销毁（日志证据成对缺失），省 0 不是 ~30K/次；且它的消耗本来就走 `session_model_usage`，进不了 `usage.json` —— **这条路径上 A3 既无效又可测不到**。A3 保留（对 TUI/gateway 无影响），撤回收益主张。n=3 对照跑（`b4f14cf` 撤销 A3）**另行证实**：撤掉 A3 无可分辨变化，与代码级结论一致。见 §9「A3 的账算错了」「A3+A9 对照跑结案」 | **✅ 完成** |
| 4 | ~~**P3/P7** 砍固定开销（terminal schema 3,281 字符最肥）~~ | **降级**：静态前缀在缓存命中区间内，砍它省的是命中价不是面值 —— 实测 1,964 字符 ≈ 每次调用 12 tokens 量级，见 §9「静态前缀的 token 数被当成了花费」 | 降级 |
| 5 | ~~**P0.1** 工具输出落盘~~ | **代码已完成（2026-09-13）**：工具侧本就在线（截断→spill→带路径，5 项回归锁），prune 侧本次补上（`_persist_pruned_tool_content`，摘要带 `Full output saved to: <path>` 指针，5 项回归锁已证伪）。**效果未测** —— 机制只在难题（长扫描/转储）上触发，验收依赖加难后的 holdout | 代码 ✅ / 效果待测 |
| 6 | ~~**重跑 P0.5.4 对照（n≥3）**~~ | **完成，A9 = −3,305 tok/调用**（配对量首屏前缀，12/12 全为正，跨度 35 即 1.1%）；一轮 4 题省 214,825–240,935。两侧均 12/12、flag 逐字全对 —— A9 没让 agent 变笨。**原判据选错了统计量**：合并 ×参考解 灵敏于**行为**差异，而 A9 的效应在**前缀**里，两者不在同一格，所以 4 题×3 批全部"分辨不了"（Δ +0.40× vs 地板 0.80×）。见 §9「A3+A9 对照跑结案」 | **✅ 完成** |
| 7 | ~~**P1.2 持久 shell + 持久 cwd**~~ | **探针结案（2026-09-14）**：cwd 机制早已工作；宽日志实测 8 条 terminal 命令 5 条绝对路径、cd 前缀仅多行脚本用、env 重导出 0 次 —— 84 字符开销无 A/B 价值。顺带修掉**描述谎言**（旧描述承诺 env 持久，local 静默违约，正确性隐患）与死旋钮标记。持久 shell 推迟：没观察到状态依赖轨迹（source venv / 跨调用 export）之前不建机制。见 §9 ⑥ | **✅ 完成** |
| 8 | ~~**④ hard-solve-protocol A/B**~~ | 送达已证明（exp 侧 5/5 轨迹出现协议段），经济性为负：ctl 2.7× / exp 3.0×（合并 4 题）→ **默认不启用**，env 门控保留 | **✅ 完成** |
| 9 | ~~**⑤ P0.2 solve-state A/B**~~ | 两轮（segment / rolling-merge regime）共 6 对均无收益，点估计为负；probe 揭示跑批峰值 ~32K 远低于压缩线，机制靠 CTF_CONFIG_EXTRA 强制触发 → **默认不启用，机制保留**，重估需重复推导实锤 + 重复计数观测 | **✅ 完成** |
| 10 | ~~**P4.5 修 benchmark + P0.5.3 重估压缩阈值**~~ | 金标重构为三档拆掉自证：smoke 100%（接线自检）/ **realistic 20%**（正文标注，检索真实水平，P4.1/P4.3 从此有判据）/ robustness 6/6 不崩（P4.2 回归锁）。P0.5.3 结案：cap 是 min 上限、跑批永远到不了 600K、强制 regime 被压平 —— **改了证伪不了，维持 0.60**，重估条件 = ≥600K 峰值轨迹。见 §9 ⑦ | **✅ 完成** |
| 11 | ~~**P5.2 假设扇出 + runtime 重复攻击检测**~~ | **零代码改动结案**：racer 已建成可用（14 测试绿，`solve --race` + dispatcher `switch_model` 双接线）；runtime 重复检测机制已在（`stopper.count_variant_failures` → `HYPOTHESIS_REPEATED` → 强制换攻击类，34 测试绿）——计划书该行写于机制盘点前，已过时。探针另证：存档日志全为截断期，重复攻击失效模式零观测。重估条件 = 宽日志轨迹中出现止损漏掉的重复攻击。见 §9 ⑧ | **✅ 完成** |
| 12 | ~~**P2.1 规则化自动委派**~~ | **零代码改动结案**：三重证据推翻"为什么"——① `delegate_task` 不在 `ctf_solve` 工具面，§3.F 的 15 次调用全是 chat 路径（没调用 ≠ 不自觉，先查原语在不在）；② P0.1 后失效体量已砍掉（spillover 全程 0 触发，峰值 32K vs 600K）；③ runtime 强制版经济性（④ 同构纯开销）与正确性（规则无法构造子代理任务上下文）双否决。附带发现：用户 config 纪律 3"嘈杂工作交给子代理"**送达但不可执行**（A2/A10 同族第三形态）。重估条件 = 压缩/spillover 真实触发且可归因。见 §9 ⑨ | **✅ 完成** |
| 13 | ~~**P4.3 检索目标换成技术卡**~~ | **探针改形状后落地 v1**：手工 `.idx.md` 行号漂移 32% 且含文档不存在的标题——不可消费，改为运行时从专题文档标题自建段索引（13 文档/906 段，mtime 缓存）；「专题速查」注入块给 `Read offset=` 直达指针。三重闸门（操作符剔除/资格规则/ASCII 词边界，调试各抓一个真实误报）+ 裸分类词与域外沉默。同源金标：web 覆盖域 hit@2 = 75%，全档 3/10 vs WP 基线 20%。mutation 3/3 被抓（操作符变异首测漏网，补判别 fixture 后抓获），15 项新测试 + 114 项知识层测试绿，golden 三档无回归。见 §9 ⑩ | **✅ 完成** |
| 14 | ~~**P6 模型路由效果验证**~~ | **试水 A/B 定稿**：3 最难题 × 双臂 × n=1（用户选定规模）。GLM-5.3 三题全解、api 68 vs 64（噪声地板内持平）、token −46%、缓存 91–94% vs 70–81%——正向信号但 n=1 不足以改默认路由。中途 scnet GLM 额度 429 → 供应商全局切 ark（用户指示）。见 §9 ⑪ | **✅ 完成（试水级）** |
| 15 | ~~**天花板效应：把题加难到会失败**~~ | **第六维 `web-tokenforge-01` 落地**（协议伪造/实现保真度，链式双层扩展+跨块）：n=3 全部贴 29–30/30 上限，**flag 正确率 2/3**——失败模式与设计对表（root 层链式续算块界语义没吃透→预算耗尽→诱饵假 flag）。离散量恢复，corpus 随 commit 冻结。见 §9 ⑫ | **✅ 完成** |
| 5b | **P0.1 效果验证（唯一挂着的表格行）** | 机制触发依赖难题峰值——⑦ probe 实测 spillover 0 触发、峰值 ~32K tok vs 600K 压缩线，当前判据测不出效果。**重估条件与 P0.5.3/P2.1 同源：峰值 ≥600K 的真实轨迹**（届时机制自然触发，效果可测） | 挂起（有明确重估条件） |

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

> **P3/P7 已按 §9 的新证据降级**，下面这段一般化教训仍然成立、但适用面变窄：
> 它讲的是**连带消失**（删一个名字会带走被它门控的整块内容），这在
> 静态前缀整体降级之后依然是唯一值得看的部分 —— 因为真正大的是那些
> 门控块（技能索引 10,192 字符），不是几十字符的 schema 尾巴。
>
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
>
> **实施时核查（2026-09-13）：上段的"不带路径"已是过时描述** —— 工具侧
> （截断 → spill 落盘 → 净化改写 → truncation_note 带路径）**早已在线**且自带
> 回归锁（5 项全绿，见 §9 ②）。真正缺的是 **prune 侧**：压缩时 >200 字符的
> 旧工具结果被换成一行摘要，内容从未落盘、摘要无路可指 —— 已补
> （`_persist_pruned_tool_content` + 指针行，5 项回归锁，已证伪）。
