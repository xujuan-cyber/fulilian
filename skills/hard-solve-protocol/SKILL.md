---
name: hard-solve-protocol
description: "难题解题协议：状态卡四段落盘、平行低价探针、强制证伪 pass、检查点分解。供 solve 时注入 CTF system prompt；与 fulilian-ctf-rules 互补，后者是行为/交付政策，本技能是解题认知结构。"
category: ctf
version: 0.1.0
author: xujuan
license: MIT
platforms: [linux, macos, windows]
# 维护注记：本文件正文（frontmatter 之后）就是 solve 路径注入 CTF system
# prompt 的那一节 —— run_agent._resolve_hard_solve_protocol() 在
# FULILIAN_CTF_HARD_SOLVE_PROTOCOL=1 时读取它。改正文 = 改运行时行为，
# 所以正文里不要写仅供人类阅读的长篇说明。
# 同族技能（仅在运行时库，不在本仓库，故不列入 related_skills）：
# fulilian-ctf-rules、ctf-dispatcher。
metadata:
  fulilian:
    tags: [ctf, methodology, hard-problems, falsification, state-card, probes]
    related_skills: []
---

# 难题解题协议（hard-solve-protocol）

以下协议仅当题目呈现"难题"特征时启用：解法方向多但大部分是死路、存在诱饵
或干扰项、必须沿唯一入口追到出口、或按直觉推进已反复偏离目标。简单题不要
套用，套用是噪音。

1. **状态卡落盘**：开局在 ctf-notes.md 建四段——「事实 / 假设 / 已排除 /
   证据」。每个工具结果归入一段，一行一条注明来源；换方向前先更新卡。卡是
   上下文压缩后唯一可恢复的状态（与"压缩后自检"同一条纪律，这里把笔记
   结构化）。**「已排除」段是新增的关键**：一个方向一旦被证据排除，记下来，
   不再回头，也不让它继续干扰剩余假设。

2. **平行低价探针**：深挖任何方向前，先并行跑 2-3 个**能分辨方向**的便宜
   检查——一次 grep、读文件头、跑一步最小验证。只深挖证据最硬的分支；探针
   把某分支判死就记入「已排除」。别用一整轮深潜去确认一个方向，那是把硬币
   抛更多次，不是找证据。

3. **证伪前置**：对当前最可能的方向，先问"什么观察能证明它是错的？"，把
   那个观察当作探针去跑。命中即放弃该方向，不恋战。**诱饵题的特征是最显眼、
   最符合直觉的方向恰恰是错的**——把直觉方向列成待证伪对象，而不是直接采信。

4. **检查点分解**：多步链式解法把每一步拆成可独立验证的中间结果（中间文件、
   一次可复现的命令、中间 flag 片段），每步先验证再进下一步。错误只烧一步，
   不顺着链滚到底。

5. **收尾证伪**：写出候选 flag 前，强制跑一遍"什么会让这个答案错"——格式、
   来源、是否存在更可能的分支尚未排除。难题的答案往往"看起来对"。自证通过
   不等于答案正确，除非你跑过反方向。
