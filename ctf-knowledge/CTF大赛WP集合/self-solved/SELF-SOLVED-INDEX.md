# 自建 WP 区（self-solved）

本目录存放**我自己解出并复盘过的难题 WP**（source: self），与 articles/ 下 1156 篇公共 WP 区分。
可信度高于公共 WP：全部经本机实际解题验证。

## 写入规则（写入端执行 task-retrospective Step 4）
- 触发：中上/难题解出后复盘时自动判断，满足任一：>=3 轮假设-验证、链式/非常规技巧、赛后自评 medium+、用户明示
- 简单题（教科书级单发命中）不写入，宁缺毋滥
- 文件名：`赛事_年份_题名.md`（对齐 articles/ 惯例，如 DASCTF_2026_p21_q17_d低300位泄露_CoppersmithLSB.md；不用 YYYY-MM-DD 前缀，禁用 = ^ + 空格等 shell 不友好字符）
- md 只写正文（标题+内容），**不放 frontmatter**：全部元数据（title/tags/date/event/category/difficulty/flag/exp）统一登记到 wp_technique_index.json，单源不双写
- json 条目必含 source_path 绝对路径（similar_by_technique 依赖）+ tags 技术标签数组
- 写入后 kr.build_index(force=True)，search + similar_by_technique 双路径哨兵词验证

## 检索方式（读取端，解题无思路时优先查这里）
- FTS5：fulilian_ctf.knowledge_retriever.search("<考点关键词>")
- 按考点找相似题：similar_by_technique(["tag1", ...])
- 文件名搜索：ls CTF大赛WP集合/self-solved/ | grep -i 关键词
