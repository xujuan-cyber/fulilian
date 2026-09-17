# Zhihu keyword-search content expansion

## Trigger
Use when exact-keyword answer-only collection yields too few rows and the user authorizes all public content returned by the keyword search.

## Verified result-card pattern
On an authenticated Zhihu search page (`https://www.zhihu.com/search?type=content&q=...`), result cards were observed under `.List-item`. Stable content links included:

- `https://www.zhihu.com/question/<qid>/answer/<aid>` — answer
- `https://zhuanlan.zhihu.com/p/<pid>` — column/article
- `/zvideo/` — video when present
- `/pin/` — idea/pin when present

A card can expose title, an author-prefixed summary, `赞同`, `评论`, and a date. Do not treat the AI search/“直答” panel or “全部来源 N” as ordinary records.

## Collection recipe
1. Preserve the answer-only run and create a new run directory for expansion.
2. For each exact and semantically adjacent query, navigate the logged-in browser search page and wait for results.
3. Extract every authorized `.List-item` containing a stable content link. Record `content_type`, query provenance, and card fields.
4. Scroll the page's custom scroller and document when repeated passes stop adding URLs.
5. Deduplicate globally by canonical content URL, retaining all matching queries in a list.
6. Open a sample of every content type in a new detail tab. Extract rendered rich text from type-appropriate containers; if unavailable, retain the card summary and mark it as a fallback.
7. Only then run the bounded bulk detail pass and verify rows, headers, unique URLs, and missing-field rates.

## Delivery mapping
If the user requested legacy columns `回答链接` and `回答正文`, use those columns for the generic content URL/body while adding `内容类型` and documenting the mapping. Filename and Markdown report must distinguish exact original keywords from expansion queries and state the final deduplicated count.

## Pitfalls
- Exact terms can return only dozens of answers even when the page visibly contains many article results; answer selectors alone undercount.
- A search card's summary is not a full detail body. Do not silently label it as full text.
- The same content can match multiple queries; never count query hits as final rows without URL deduplication.
- Do not blindly add unrelated broad terms merely to reach a target; each expansion query must remain semantically tied to the research scope.
