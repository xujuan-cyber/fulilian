# Zhihu keyword-matrix expansion (session recipe)

Use after exact search terms and a small adjacent-query batch remain below a user-specified volume target.

## Objective

Collect publicly visible ordinary content cards from Zhihu keyword search across answers, columns/articles, videos, and ideas/pins. Exclude navigation, user profiles, ads, question-only links, and platform AI-generated answer panels unless explicitly requested.

## Discovery pattern

1. Keep the user-authenticated Chrome profile open on a visible WSL display and expose CDP only on `127.0.0.1`.
2. For each query navigate to:
   `https://www.zhihu.com/search?type=content&q=<urlencoded query>`
3. From repeated `.List-item` cards select a stable ordinary content anchor:
   - answer: `/question/<id>/answer/<id>`
   - column/article: `zhuanlan.zhihu.com/p/<id>`
   - video: `/zvideo/<id>`
   - idea: `/pin/<id>`
4. Scroll the page’s `[data-custom-scroller=true]` (fall back to `document.scrollingElement`), stop after several no-growth passes, and record the exact query on each row.
5. Immediately store visible card fields: URL, title, author, result summary, likes, comment count, displayed date, and type. Use details only to upgrade the body; mark result-card summaries as such.

## Query-matrix design

Use semantic intersections rather than repeatedly retrying sparse exact terms. A useful pattern is `technical_prefix × harm/governance_topic`.

Examples of prefixes: AI, 人工智能, AIGC, 生成式人工智能, 大模型, 语言模型, 深度伪造, 深度合成, 合成内容, 算法推荐, 数字人, 虚拟人.

Examples of topics: 谣言, 虚假信息, 造假, 伪造, 编造, 捏造, 洗稿, 内容农场, 低质内容, 信息污染, 虚假视频, 虚假图片, 虚假宣传, AI幻觉, 虚构事实, 伪造证据, 仿冒, 钓鱼, 诈骗, 内容标识, 水印, 溯源, 检测, 识别, 内容审核, 内容治理, 网络治理, 辟谣.

Avoid claiming that every combination is equally relevant: retain the query provenance and document expansion logic. If broad-topic queries are used, require an AI-related term in the card/title/summary before accepting the record.

## Merge and target delivery

- Canonicalize content URLs by removing query strings and trailing slash variants.
- Merge all raw runs by canonical URL; union the keyword lists rather than duplicating rows.
- Validate final row count, unique URL count, headers, type counts, and field-missing counts after writing the CSV.
- When user requested exactly N records but the verified topic-relevant universe exceeds N, preserve the complete deduplicated audit set and create a separate N-row primary CSV. State a deterministic selection order (e.g., original-term hit, number of original/expanded query hits, nonempty body, author/engagement completeness). Do not silently discard the full set.
- Filename must include source, original user keyword group, and final delivered record count; use UTF-8 BOM CSV.
