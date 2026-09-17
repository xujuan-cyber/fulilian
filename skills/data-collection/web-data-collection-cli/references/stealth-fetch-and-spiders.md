# Stealth fetch, sessions, and spiders (Scrapling)

A **code-level** collection layer that complements the Bazhuayu-CLI path in the
main SKILL.md. Reach for it when a target is out of reach for the CLI: dynamic
JS rendering, a Cloudflare/anti-bot wall, an authenticated session that must be
driven programmatically, or a crawl big enough to need resume.

Absorbed 2026-09-14 from the CocoLoop store skill *Scrapling Official* v0.4.14
(author d4vinci, **T1 / maintained by the library author**). Requires
Python 3.10+.

Setup (once, inside a venv): `pip install "scrapling[all]>=0.4.14"`, then
`scrapling install --force`. Note the binary path if `scrapling` isn't on
`$PATH`.

## 1. Pick the lightest fetcher

Escalate only as needed — the same ladder documented in the
`blocked-page-recovery` skill, here in code form:

| Need | Fetcher |
|------|---------|
| Static page, blog, news | `Fetcher` / `FetcherSession` |
| JS-rendered page, SPA | `DynamicFetcher` / `DynamicSession` |
| Cloudflare / anti-bot | `StealthyFetcher` / `StealthySession` |

```python
from scrapling.fetchers import Fetcher, FetcherSession

# Session: reuse one browser/TLS context across many requests
with FetcherSession(impersonate='chrome') as session:   # real Chrome TLS fingerprint
    page = session.get('https://quotes.toscrape.com/', stealthy_headers=True)
    quotes = page.css('.quote .text::text').getall()

# One-off
page = Fetcher.get('https://quotes.toscrape.com/')
```

```python
from scrapling.fetchers import StealthyFetcher, StealthySession

# Cloudflare challenge
with StealthySession(headless=True, solve_cloudflare=True) as session:
    page = session.fetch('https://protected.site/', google_search=False)
    data = page.css('#content a').getall()
```

```python
from scrapling.fetchers import DynamicSession

with DynamicSession(headless=True, network_idle=True) as session:
    page = session.fetch('https://spa.site/', load_dom=False)
    items = page.xpath('//span[@class="text"]/text()').getall()
```

Async pools (bounded concurrency):

```python
async with AsyncStealthySession(max_pages=2) as session:
    results = await asyncio.gather(*[session.fetch(u) for u in urls])
    print(session.get_pool_stats())   # busy / free / error tabs
```

## 2. XHR / API capture — generalises the CDP interception approach

The existing Xiaohongshu work intercepts XHR through Edge CDP
(`browser-cookie-extraction.md`, `xiaohongshu-cdp-*` references). Scrapling
offers the same capability **without** binding to a specific browser/CDP
setup, which makes it a good fallback when Edge CDP is unavailable:

```python
from scrapling.fetchers import AsyncDynamicSession

async with AsyncDynamicSession(capture_xhr=r"https://api\.example\.com/.*") as session:
    page = await session.fetch('https://example.com')
    for xhr in page.captured_xhr:      # each is a full Response object
        print(xhr.url, xhr.status, xhr.body)
```

Use it to find the JSON endpoint behind a rendered page, then pivot to calling
that endpoint directly — the same "data endpoints are less protected than the
HTML surface" tactic as the API-first pivot.

## 3. Parsing

```python
quotes = page.css('.quote')                     # CSS
quotes = page.xpath('//div[@class="quote"]')    # XPath
quotes = page.find_all('div', {'class': 'quote'})   # BeautifulSoup-style
quotes = page.find_by_text('quote', tag='div')

quote = page.css('.quote')[0]
author = quote.next_sibling.css('.author::text')    # chained navigation
parent = quote.parent

similar = quote.find_similar()      # adaptive: relocates elements after markup changes
below   = quote.below_elements()
```

`Selector("<html>...</html>")` parses an already-fetched string the same way —
handy for re-parsing stored HTML without re-fetching.

## 4. Spiders — for multi-page / long crawls

```python
from scrapling.spiders import Spider, Response

class QuotesSpider(Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/"]
    concurrent_requests = 10
    robots_txt_obey = True          # enforce politeness automatically

    async def parse(self, response: Response):
        for q in response.css('.quote'):
            yield {"text": q.css('.text::text').get(),
                   "author": q.css('.author::text').get()}
        nxt = response.css('.next a')
        if nxt:
            yield response.follow(nxt[0].attrib['href'])

result = QuotesSpider().start()
result.items.to_json("quotes.json")
```

**Multi-session routing** — send protected URLs through a stealth session and
the rest through a fast one:

```python
def configure_sessions(self, manager):
    manager.add("fast", FetcherSession(impersonate="chrome"))
    manager.add("stealth", AsyncStealthySession(headless=True), lazy=True)

# in parse():
yield Request(link, sid="stealth")                      # protected
yield Request(link, sid="fast", callback=self.parse)    # normal
```

**Rules-driven crawling** — don't hand-write the link loop:

```python
from scrapling.spiders import CrawlSpider, CrawlRule, LinkExtractor

class BlogCrawler(CrawlSpider):
    name = "blog"
    start_urls = ["https://example.com"]

    def rules(self):
        return [
            CrawlRule(LinkExtractor(allow=r"/posts/"), callback=self.parse_post),
            CrawlRule(LinkExtractor(allow=r"/page/\d+/")),   # follow pagination
        ]
```

`LinkExtractor` also takes `deny`, `restrict_css`, `canonicalize`.
`SitemapSpider` uses the same `rules()` API and descends sitemap indexes — you
can hand it a `robots.txt` URL and it pulls the `Sitemap:` directives out.

Feed spiders: `XMLFeedSpider` (`itertag` + `parse_node`), `CSVFeedSpider`
(`parse_row`, with `headers`/`delimiter`/`quotechar`). Both gunzip
transparently. For Shopify stores, `ShopifySpider` pulls product variants from
the JSON API without touching HTML.

## 5. Long-run operations

**Pause/resume** — critical for crawls that will outlive one session:

```python
QuotesSpider(crawldir="./crawl_data").start()
```

Ctrl+C pauses gracefully and saves progress; restarting with the same
`crawldir` resumes where it stopped.

**Iterating without re-hitting the target** — cache responses to disk and
replay them while you tune `parse()`:

```python
class QuotesSpider(Spider):
    development_mode = True
    # development_cache_dir = ".custom_cache"   # default: .scrapling_cache/{name}/
```

Never ship a spider with `development_mode` on.

**Backoff**: set `download_delay`, or `autothrottle_enabled = True` to let the
spider pick a per-domain delay and back off when a site starts blocking.

## 6. Guardrails (non-negotiable)

- Only collect content you are authorised to access.
- Keep `robots_txt_obey = True` and use delays/throttling on large crawls.
- Don't bypass paywalls or authentication without permission.
- Never collect personal/sensitive data.

These mirror the standing collection constraints in the main SKILL.md — an
external skill's defaults never override the user's authorisation and scope.

## Attribution

*Scrapling Official* v0.4.14 (author: d4vinci; official skill for the Scrapling
library), retrieved from the CocoLoop store
(`https://dl.cocoloop.cn/bss/skills/d4vinci-scrapling-official-0.4.14.zip`).
Condensed to the parts that complement the existing Bazhuayu + CDP stack; the
library's full reference set (parsing, fetching, spiders, MCP server, Scrapy
integration, BeautifulSoup migration) is deliberately not copied here — fetch
it from `https://scrapling.readthedocs.io` when a detail is needed.
