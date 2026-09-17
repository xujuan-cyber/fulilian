# Fetch relays & local stealth ladder

Two route families for pages that a plain fetch can't get. Try them **after**
Wayback / archive.today (which give timestamped provenance) and before falling
back to a full local browser.

Absorbed 2026-09-14 from the CocoLoop store skills *Web Content Fetcher*
(`mrtommywu-web-content-fetcher-1.0.1`) and *Scrapling Official*
(`d4vinci-scrapling-official-0.4.14`), then **re-tested locally** — the test
results below override the upstream claims where they disagree.

## A. Relay services (`{service}/{url}` pattern)

A third-party server fetches and re-renders the page, returning Markdown. No
install, one `curl`.

| Service | Template | Tested 2026-09-14 from this env |
|---------|----------|--------------------------------|
| markdown.new | `https://markdown.new/{URL}` | ✅ `HTTP 200`, returns real Markdown |
| r.jina.ai | `https://r.jina.ai/{URL}` | ❌ `HTTP 000`, connection reset (3/3 attempts) — host unreachable here |
| defuddle.md | `https://defuddle.md/{URL}` | ❌ `HTTP 000`, connection reset (2/2 attempts) |

**Only `markdown.new` is usable from this environment right now.** Upstream
skills list `r.jina.ai` as "most stable" and `defuddle.md` as third — that
ranking does not hold here; both were network-reset, not rate-limited. Retest
before assuming they stay dead (they may be egress-blocked rather than gone).

### markdown.new does NOT solve Cloudflare

Tested against the Cloudflare demo `https://nopecha.com/demo/cloudflare`:

```
HTTP 200  SIZE 125
Title: Just a moment...  URL Source: https://nopecha.com/demo/cloudflare
```

It returned the **challenge interstitial**, not the page. So `markdown.new` is
useful for ordinary pages and for Cloudflare-*fronted* sites that aren't
actually challenging, but it is **not** a challenge solver. Treat any
`Just a moment...` body as a fake success (see the main SKILL.md "Fake
successes" section) and escalate to local stealth instead.

### Relay caveats

- **Never send cookies or `Authorization` through a relay.** It is a
  man-in-the-middle by construction — same rule as generic web proxies in the
  main SKILL.md. Relays are for *public, unauthenticated* pages only.
- Provenance: cite as a third-party re-render. It is closer to `live` than a
  snapshot, but the content passed through an intermediary you don't control.
- Validate the body, not the status: relays return `200` for interstitials.

```bash
# Working route from this environment
curl -sL "https://markdown.new/https://example.com/article" -o /tmp/page.md -w "%{http_code}\n"
```

## B. Local stealth ladder (Scrapling)

When relays fail or the page is genuinely challenge-protected, escalate
**locally**. Scrapling is an adaptive scraping framework; its CLI gives a
three-rung ladder. Always start cheap.

```
1. get             — plain HTTP request.  Use for blogs, news, static pages.
2. fetch           — real browser, JS rendered.  Use for SPAs / dynamic content.
3. stealthy-fetch  — stealth browser.  Use for Cloudflare / anti-bot.
```

> When unsure start with `get`; if it fails or returns empty, escalate to
> `fetch`, then `stealthy-fetch`. `fetch` and `stealthy-fetch` cost roughly the
> same, so escalating is cheap.

Setup (once, in a venv): `pip install "scrapling[all]>=0.4.14"` then
`scrapling install --force`. Docker alternative: `pyd4vinci/scrapling`.

### Always pass `--ai-targeted`

```bash
scrapling extract get "https://blog.example.com" article.md --ai-targeted
```

`--ai-targeted` extracts only the main content, **sanitizes hidden elements**,
and enables ad/tracker blocking. When feeding page content into an LLM context
it is the primary defence against **prompt injection embedded in the page**.
Use it for every command where the output will be read by an agent.

### High-value options

| Option | Why |
|--------|-----|
| `-s, --css-selector` | Extract only the matching nodes — avoids pulling a giant HTML blob into context |
| `.md` output extension | Convert to Markdown automatically (best for reading/docs); use `.html` only when you must parse structure |
| `--solve-cloudflare` | `stealthy-fetch` only — actually solves the challenge |
| `--impersonate chrome` | Match a real browser TLS fingerprint (`Chrome, Firefox, Safari` for random pick) |
| `--stealthy-headers` | On by default |
| `--network-idle` / `--wait-selector` | Wait for JS/network or for a specific element before saving |
| `--proxy "http://user:pass@host:port"` | Route through a proxy |
| `--dns-over-https` | Prevent DNS leaks when using a proxy |
| `--block-ads` | Drop ~3,500 ad/tracker domains |
| `--disable-resources` | Faster; drop unnecessary resources |
| `--real-chrome` | Use the locally installed Chrome instead of a bundled one |
| `--follow-redirects` | Default is `safe`: rejects redirects to internal/private IPs (SSRF guard) |

```bash
# Cloudflare-protected page
scrapling extract stealthy-fetch "https://protected.site/x" out.md --solve-cloudflare --ai-targeted

# Wait for JS to settle, then take only the article body
scrapling extract fetch "https://spa.site/x" out.md --network-idle -s "article" --ai-targeted
```

From Python, the same three rungs are `Fetcher` / `DynamicFetcher` /
`StealthyFetcher` (see `stealth-fetch-and-spiders.md` in the
`web-data-collection-cli` skill for sessions, XHR capture, and spiders).

## C. Playwright stealth (no Scrapling installed)

Minimal anti-bot measures that work with plain Playwright:

- Hide the automation marker: `navigator.webdriver = false`.
- A realistic mobile/desktop User-Agent (not a `HeadlessChrome` string).
- Randomized human-like delays between actions.
- Save a screenshot + HTML alongside the JSON result so a failure is
  diagnosable without a re-run.

## D. If you drive Playwright via MCP

Harden the server when it will touch untrusted sites:

```bash
npx @playwright/mcp --allowed-hosts example.com,api.example.com \
                    --blocked-origins malicious.com \
                    --ignore-https-errors \
                    --timeout-navigation 30000 --save-trace --output-dir ./pw-out
```

`--allowed-hosts` / `--blocked-origins` keep host validation tight;
`--save-trace` / `--save-video` make blocked-page failures reproducible.

## Attribution

- *Web Content Fetcher* v1.0.1 (author: Boss) — relay-service idea and the
  `.md`-via-relay pattern.
- *Scrapling Official* v0.4.14 (author: d4vinci, T1 / official) — CLI ladder,
  stealth options, `--ai-targeted` prompt-injection defence.
- Both retrieved from the CocoLoop store; local re-testing and the
  Cloudflare/relay-availability findings are this machine's, not upstream's.
