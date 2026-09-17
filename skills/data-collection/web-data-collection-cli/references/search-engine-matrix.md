# Search-engine matrix (keyless)

URL-template search across many engines with **no API keys** — useful when the
configured web-search tool is down, rate-limited, or returns nothing for a
niche query, and as a second source when corroborating a finding.

Absorbed 2026-09-14 from the CocoLoop store skill *Multi Search Engine*
v2.1.3 (`gpyangyoujun-multi-search-engine-2.1.3.zip`), then **locally
re-tested**. The reachability column below is this machine's measured result,
not upstream's claim — **upstream lists 9 international engines as usable; from
this environment almost none are.**

## Engine URLs and measured reachability

Probe: 2026-09-14, desktop Chrome UA, `curl -L --max-time 20`, 1.5 s spacing.

### Domestic

| Engine | Template | Reachable here |
|--------|----------|----------------|
| Bing CN | `https://cn.bing.com/search?q={kw}&ensearch=0` | ✅ 200, ~99 KB — **primary** |
| Sogou | `https://sogou.com/web?query={kw}` | ✅ 200, ~995 KB |
| Shenma | `https://m.sm.cn/s?q={kw}` | ✅ 200, ~524 KB |
| WeChat articles | `https://wx.sogou.com/weixin?type=2&query={kw}` | ✅ 200, ~31 KB |
| Baidu | `https://www.baidu.com/s?wd={kw}` | ⚠️ 200 but only ~1.5 KB — JS/anti-bot stub, **not usable via curl** |
| 360 | `https://www.so.com/s?q={kw}` | ⚠️ 302, no body |
| Bing INT | `https://cn.bing.com/search?q={kw}&ensearch=1` | use the same host as Bing CN |

### International

| Engine | Template | Reachable here |
|--------|----------|----------------|
| WolframAlpha | `https://www.wolframalpha.com/input?i={kw}` | ✅ 200, ~50 KB |
| Ecosia | `https://www.ecosia.org/search?q={kw}` | ⚠️ 200 but ~15 KB — likely consent/bot page, verify body |
| Google | `https://www.google.com/search?q={kw}` | ❌ not tested / assume blocked |
| Google HK | `https://www.google.com.hk/search?q={kw}` | ❌ 000 |
| DuckDuckGo | `https://duckduckgo.com/html/?q={kw}` | ❌ 000 |
| Brave | `https://search.brave.com/search?q={kw}` | ❌ 000 |
| Startpage | `https://www.startpage.com/sp/search?query={kw}` | ❌ 000 |
| Yahoo | `https://search.yahoo.com/search?p={kw}` | ❌ 000 |
| Qwant | `https://www.qwant.com/?q={kw}` | ❌ 000 |

`000` = connection failed/reset at the network layer, the same pattern seen for
`r.jina.ai` and `defuddle.md`. These are egress-blocked, not broken — retest
before relying on them from a different network.

**Rule of thumb: use a content-size sanity check, not the status code.** Two
engines above return `200` with a stub body. Anything under a few KB is a
verification page, not results.

## Routing

- **Chinese query → domestic engines.** Start with Bing CN; add Sogou and
  Shenma; use the WeChat template specifically for 公众号/文章 content.
- **Non-Chinese query → international engines**, but from this environment
  expect to fall back to Bing INT or WolframAlpha.

## Execution discipline

- **1–2 s delay between requests.** Don't fan out.
- **Batch 3–4 engines, sequentially within a batch**, instead of firing all of
  them at once.
- Send a normal desktop browser User-Agent.
- **On 403/429:** fetch the engine's homepage to obtain a fresh session cookie,
  then retry **once** after a 2 s delay. Don't loop.
- **Cookies stay in memory for the request only** — acquired on demand, never
  written to `config.json` or any file, cleared after the search. Preserve this
  property; it's the reason the technique is safe.
- Consolidate only the engines that actually returned results, and summarise
  rather than dumping raw SERPs into context.

## Query operators

| Operator | Example | Meaning |
|----------|---------|---------|
| `site:` | `site:github.com python` | restrict to a domain |
| `filetype:` | `filetype:pdf report` | restrict to a file type |
| `""` | `"machine learning"` | exact phrase |
| `-` | `python -snake` | exclude a term |
| `OR` | `cat OR dog` | either term |

## Time filters (Google-family `tbs`)

| Parameter | Window |
|-----------|--------|
| `tbs=qdr:h` | past hour |
| `tbs=qdr:d` | past day |
| `tbs=qdr:w` | past week |
| `tbs=qdr:m` | past month |
| `tbs=qdr:y` | past year |

Example: `https://www.google.com/search?q=ai+news&tbs=qdr:w`

## DuckDuckGo bang shortcuts

`!g` Google · `!gh` GitHub · `!so` Stack Overflow · `!w` Wikipedia · `!yt` YouTube
— e.g. `https://duckduckgo.com/html/?q=!gh+tensorflow`. (DDG is unreachable
here; the syntax is recorded for networks where it works.)

## WolframAlpha (worked here)

- Math: `integrate x^2 dx`
- Conversion: `100 USD to CNY`
- Stocks: `AAPL stock`
- Weather: `weather in Beijing`

## How to call it

```
web_fetch({"url": "https://cn.bing.com/search?q=site%3Agithub.com+react"})
```

or, when the built-in fetch is the thing that's failing, `curl -L -A "<UA>"`
from Bash, or drive it through Playwright MCP / the Scrapling ladder in
`references/stealth-fetch-and-spiders.md`. If a whole engine is blocked,
`references/` in the `blocked-page-recovery` skill has the relay and stealth
routes.

## Attribution

*Multi Search Engine* v2.1.3 (author: gpyangyoujun) — engine list, routing,
operator/filter tables and the rate-limit + in-memory-cookie discipline.
Retrieved from the CocoLoop store
(`https://dl.cocoloop.cn/bss/skills/gpyangyoujun-multi-search-engine-2.1.3.zip`).
The reachability column is this machine's measurement and supersedes the
upstream assumption that all 16 engines are equally available.
