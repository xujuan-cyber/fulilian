---
name: blocked-page-recovery
description: "Recover blocked/paywalled/WAF'd pages via fallbacks."
version: 1.0.0
author: FuLiLian
license: MIT
platforms: [linux, macos, windows]
metadata:
  fulilian:
    tags: [Research, Archives, Wayback, Paywall, WAF, Fallback]
    related_skills: [grounded-citations]
---

# Blocked-Page Recovery

When a page won't fetch — 403/429, Cloudflare "Just a moment...", a paywall,
or a bot-detection interstitial — don't give up and don't loop on the same
URL. Third-party services often hold a **copy** of the page. Work down this
ladder, cheapest first.

## The ladder

```
1. Wayback Machine  — archive.org "available" API  (snapshot + timestamp)
2. archive.today    — domain rotation: archive.ph → .md → .li → .is
3. Relay services   — markdown.new / r.jina.ai / defuddle.md  (markdown.new verified
                      working from this env; the other two are egress-blocked here)
4. API-first pivot  — look for /api/, /graphql, .json, or RSS on the same host
5. Local stealth    — Scrapling get → fetch → stealthy-fetch (--solve-cloudflare);
                      plain Playwright stealth as the fallback
6. Real browser     — browser tool as the last, most expensive resort
```

Rungs 3 and 5 are detailed in
[references/fetch-relays-and-stealth.md](references/fetch-relays-and-stealth.md)
— including which relay is actually reachable, the fact that **no relay solves
a Cloudflare challenge**, and the `--ai-targeted` flag that sanitizes
page content before it reaches an agent's context.

Run it in one shot with the bundled script:

```bash
python3 scripts/recover_page.py "https://example.com/blocked-article" --json
```

The script tries each route in order, validates every body (see "Fake
successes" below), and prints the first genuine hit with its provenance.

## Provenance discipline (non-negotiable)

Every recovered copy carries a provenance you MUST preserve when citing:

| Route | Provenance | How to cite |
|-------|-----------|-------------|
| Wayback / archive.today | `snapshot` | Cite WITH the snapshot date: "as archived 2026-08-06". Never present a snapshot as the live page — it may be stale. |
| Jina Reader | `live` | Server-side re-render of the live page; cite normally. |
| Live fetch / browser | `live` | Cite normally. |

If the user needs *current* data (prices, availability, breaking news), a
snapshot is context, not an answer — say so explicitly and note its age.

## Manual routes

### 1. Wayback Machine (best provenance, try first)

```bash
# Discovery: returns closest snapshot URL + timestamp as JSON
curl -sL "https://archive.org/wayback/available?url={URL}"
# Then fetch archived_snapshots.closest.url
```

For enumerating many snapshots (or recovering deleted pages), the CDX index:

```bash
curl -sL "https://web.archive.org/cdx/search/cdx?url={URL}&output=json&limit=10"
```

CDX intermittently returns 503 under load — if it does, fall back to the
`available` API; don't retry-hammer it.

Works for: any publicly crawled URL. Fails for: robots-blocked sites,
never-crawled URLs, JS-only SPAs (snapshots don't render).

### 2. archive.today (paywalls, deleted content)

User-submitted archives — often has paywalled news articles Wayback lacks.
Rate-limits aggressively (429) and rotates domains, so iterate:

```bash
for d in archive.ph archive.md archive.li archive.is; do
  curl -sL --max-time 20 "https://$d/newest/{URL}" -o /tmp/page.html \
    -w "%{http_code}" && break
done
```

**Validate the body, not the status code** — a 429 still ships several KB of
rate-limit HTML that looks like a success to a size check alone.

### 3. Jina Reader (requires JINA_API_KEY)

`r.jina.ai` re-renders the live page in a real browser server-side and
returns markdown. Anonymous access is dead (401 → Turnstile); a key is
required:

```bash
curl -s -H "Authorization: Bearer $JINA_API_KEY" "https://r.jina.ai/{URL}"
```

Handles JS SPAs that archives can't. Skip this route entirely when the env
var is unset.

**Status check 2026-09-14:** from this environment `r.jina.ai` did not resolve
to a usable service at all — every attempt was reset at the TCP layer
(`HTTP 000`), key or no key. `markdown.new` was the only relay that worked.
See [references/fetch-relays-and-stealth.md](references/fetch-relays-and-stealth.md)
before spending time on this rung.

### 4. API-first pivot

WAFs protect the HTML surface far more aggressively than the data endpoints
behind it. After 2-3 blocked attempts on a site, stop fighting the HTML and
look for:

- `/api/...`, `/graphql`, or `.json` variants of the page URL
- An RSS/Atom feed (`/feed`, `/rss`, `<link rel="alternate">` in any copy
  you did recover)
- A sitemap (`/sitemap.xml`) revealing canonical URLs that may not be gated

## Fake successes — routes that LIE

These return HTTP 200 with a plausible body that is NOT the page. The script
rejects them automatically; reject them manually too:

- **Google Cache is dead** (since mid-2024). `webcache.googleusercontent.com`
  returns 200 + tens of KB, but it's a Google Search interstitial with a JS
  redirect, not a cache. Never use it.
- **AMP caches** (`*.cdn.ampproject.org`) mostly return a ~300-byte
  `<title>Redirecting</title>` meta-refresh stub pointing back at the
  original (blocked) URL. Treating that as success creates a fetch loop.
- **Rate-limit bodies**: archive.today 429 pages are multi-KB HTML. Check for
  the target's actual content (title words, expected strings), not just size.
- **Relay interstitials**: a relay service returns `200` with the Cloudflare
  challenge stub (`Just a moment...`, ~125 bytes) when it cannot get past the
  challenge. It is not a solver — treat the stub as a failure and go to rung 5.

Detection heuristics the script applies: body under a per-route byte floor;
meta-refresh/JS-redirect stubs whose target is the original host; interstitial
titles ("Just a moment", "Redirecting", "Google Search", "Attention Required").

## Proxy relays: don't

Generic "web proxy" relays are man-in-the-middle by construction. Never send
cookies or Authorization headers through one, and don't use them for anything
the user will rely on — provenance is unverifiable. Prefer archives, which at
least timestamp their copies.

The same rule applies to the **relay services** in rung 3: they are
unauthenticated, public-page-only routes. For anything session-gated, go to
rung 5 (local stealth) and drive the browser/HTTP client yourself.

## References

- [references/fetch-relays-and-stealth.md](references/fetch-relays-and-stealth.md)
  — relay services (`markdown.new` / `r.jina.ai` / `defuddle.md`) with local
  reachability test results; the Scrapling CLI ladder (`get` → `fetch` →
  `stealthy-fetch`) and its options; `--ai-targeted` prompt-injection
  sanitization; Playwright stealth baseline; Playwright MCP hardening flags.
  Absorbed 2026-09-14 from the CocoLoop store skills *Web Content Fetcher*
  and *Scrapling Official*, then locally re-tested.
