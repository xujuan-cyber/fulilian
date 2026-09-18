# Xiaohongshu CDP Cookie Injection

**⚠️ CRITICAL LIMITATION (2026-08-25): Cookie injection via CDP does NOT work on Xiaohongshu.** The anti-bot system (`acw_tc` challenge) clears injected cookies on page load. `Network.setCookie` returns `success: true` but cookies are not persisted in the browser's cookie jar. The only reliable authentication path is real browser login via `bazhuayu detect --manual`.

## When to use (documented despite limitation)

- User provides cookies from their browser (via EditThisCookie, browser developer tools, or browser extension)
- Bazhuayu `detect --manual` cannot reuse the session
- You have a running Chrome with `--remote-debugging-port` and need to authenticate the page

## Correct CDP methods (Chrome 147+)

**`Storage.setCookie` / `Storage.getCookies` / `Storage.deleteCookies` are NOT available in Chrome 147+ (return error code -32601 "wasn't found").** Use the `Network.*` equivalents instead:

| Obsolete (Chrome 147+) | Replacement |
|---|---|
| `Storage.setCookie` | `Network.setCookie` |
| `Storage.getCookies` | `Network.getCookies` |
| `Storage.deleteCookies` | `Network.deleteCookies` |

**However**, even `Network.setCookie` returns `success: true` without actually persisting cookies when the Xiaohongshu anti-bot system is active. See Limitations below.

## Known blockers (Xiaohongshu anti-bot `acw_tc` challenge)

The `acw_tc` (Anti-Crawler Web) challenge is the root cause of cookie injection failure:

1. **`acw_tc` cookie expires ~24h** — even though `a1`/`web_session`/`id_token` show 1-year expiry, the `acw_tc` cookie is short-lived. When it expires, the entire session is invalidated.
2. **Page load triggers fresh challenge** — navigating to any Xiaohongshu page triggers the anti-bot system, which overwrites ALL cookies with server-issued ones. Injected cookies are discarded.
3. **`Network.setCookie` returns success but doesn't persist** — the CDP method reports `success: true` but the cookie never enters the browser's actual cookie jar. `Network.getCookies` returns 0 xiaohongshu-domain cookies after injection.
4. **`document.cookie` can't set HttpOnly cookies** — `web_session` and `id_token` are HttpOnly, so JS injection via `Page.addScriptToEvaluateOnNewDocument` is ineffective.
5. **Direct API calls blocked** — `so.xiaohongshu.com/api/sns/web/v2/search/notes` returns HTTP 406 without the X-s/X-t/X-S-Common/x-rap-param anti-bot headers. These headers are computed from the request body by the frontend framework and cannot be forged externally. Only the page's internal Pinia store can make valid API calls.

## Diagnostic: session expiry detection

When collection returns 0 rows, check session health:

```bash
# Check cookie expiry times
cat ~/.octopus/browser-sessions/xhs-login.json | python3 -c "
import sys, json, time
d = json.load(sys.stdin)
cookies = d.get('cookies', [])
now = time.time()
print(f'Cookies: {len(cookies)}个')
for c in cookies:
    exp = c.get('expirationDate', 0)
    remaining = (exp - now) / 86400
    print(f'  {\"✓\" if remaining > 7 else \"⚠\" if remaining > 0 else \"✗\"} {c[\"name\"]:20s} {remaining:.1f}天')
"

# Check for acw_tc specifically
cat ~/.octopus/browser-sessions/xhs-login.json | python3 -c "
import sys, json, time
d = json.load(sys.stdin)
cookies = {c['name']: c for c in d.get('cookies', [])}
now = time.time()
for name in ['acw_tc', 'a1', 'web_session', 'id_token', 'websectiga']:
    c = cookies.get(name)
    if c:
        exp = c.get('expirationDate', 0)
        print(f'  {name:20s} {\"OK\" if exp > now else \"EXPIRED\"} ({exp - now:.0f}s left)')
    else:
        print(f'  {name:20s} MISSING')
"

# Test via HTTP (will show login wall if expired)
curl -s -o /dev/null -w '%{http_code}' \
  --cookie ~/.octopus/browser-sessions/xhs-cookies.txt \
  'https://www.xiaohongshu.com/search_result?keyword=AI&source=web_search_result_notes'
# 200 = cookies valid; 302/redirect = login wall
```

## Workflow

### 1. Start Chrome with remote debugging

```bash
# Use terminal(background=true) — NEVER foreground pkill
# IMPORTANT: add --remote-allow-origins=* for Chrome 147+
/home/xujuan/.cache/octorunner/chrome/.../chrome \
  --user-data-dir=/home/xujuan/bazhuayu_output/xhs_browser_profile \
  --remote-debugging-port=9444 \
  --remote-allow-origins=* \
  --no-first-run \
  --new-window "about:blank"
```

### 2. Get the tab WebSocket URL (Node.js)

```javascript
const http = require('http');
const WebSocket = require('ws');  // npm install ws

async function main() {
  const tabs = await httpGet('http://localhost:9444/json');
  const tab = tabs.find(t => t.type === 'page');
  // tab.webSocketDebuggerUrl is the WS URL
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
}
```

### 3. Cookie management via CDP (correct methods for Chrome 147+)

```javascript
let msgId = 1;

function cdpCall(method, params = {}, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    const t = setTimeout(() => reject(new Error('Timeout: ' + method)), timeout);
    const handler = (data) => {
      const resp = JSON.parse(data.toString());
      if (resp.id === id) { clearTimeout(t); ws.removeListener('message', handler); resolve(resp); }
    };
    ws.on('message', handler);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function injectCookies(ws, cookies) {
  // 1. Delete existing cookies — use Network.deleteCookies with domain+path
  const existing = await cdpCall('Network.getCookies');
  for (const c of (existing.result.cookies || []).filter(c => c.domain.includes('xiaohongshu'))) {
    await cdpCall('Network.deleteCookies', {
      name: c.name,
      domain: c.domain,
      path: c.path || '/'
    });
  }

  // 2. Set cookies — use Network.setCookie (NOT Storage.setCookie)
  for (const c of cookies) {
    const domain = c.domain.startsWith('.') ? c.domain.substring(1) : c.domain;
    const url = (c.secure ? 'https://' : 'https://') + domain + (c.path || '/');
    const params = {
      name: c.name,
      value: c.value,
      url: url,
      domain: domain,
      path: c.path || '/',
      secure: c.secure || false,
      httpOnly: c.httpOnly || false,
    };
    if (c.expirationDate) params.expires = Math.floor(c.expirationDate);
    const resp = await cdpCall('Network.setCookie', params, 5000);
    // resp.result.success may be true even when cookie doesn't actually persist
    console.log(`${c.name}: ${resp.result?.success ? 'OK' : 'FAIL'}`);
  }
}
```

### 4. User cookie JSON format

The user typically provides cookies in this format (from EditThisCookie or browser dev tools export):

```json
[
  {
    "domain": ".xiaohongshu.com",
    "expirationDate": 1819095891,
    "hostOnly": false,
    "httpOnly": false,
    "name": "a1",
    "path": "/",
    "secure": false,
    "session": false,
    "value": "1a032df53ddf905zuy..."
  },
  {
    "domain": ".xiaohongshu.com",
    "expirationDate": 1819095918,
    "hostOnly": false,
    "httpOnly": true,
    "name": "web_session",
    "path": "/",
    "secure": true,
    "value": "040069b23cb7bf..."
  }
]
```

Key cookies for Xiaohongshu login: `a1`, `web_session`, `id_token`, `websectiga`.

## Limitations

- **⚠️ Cookie injection is BLOCKED by Xiaohongshu anti-bot:** The `acw_tc` challenge system clears injected cookies on page load. `Network.setCookie` returns `success: true` but cookies are NOT persisted. The only reliable way to authenticate is real browser login via `bazhuayu detect --manual`.
- **`acw_tc` cookie expires ~24h:** Even when `a1`/`web_session`/`id_token` show 1-year expiry, the short-lived `acw_tc` anti-crawler cookie invalidates the entire session when it expires.
- **HttpOnly cookies:** `document.cookie` does NOT expose HttpOnly cookies. `web_session` and `id_token` are HttpOnly. `Page.addScriptToEvaluateOnNewDocument` with `document.cookie` cannot set these.
- **Chrome 147+ API changes:** `Storage.setCookie` / `Storage.getCookies` / `Storage.deleteCookies` are gone (error -32601). Use `Network.setCookie` / `Network.getCookies` / `Network.deleteCookies` instead.
- **`--remote-allow-origins=*` required:** Chrome 147+ blocks WebSocket connections from non-matching origins. Without this flag, CDP connections get HTTP 403.
- **Python websocket libraries unreliable:** `websockets` (v17+) frequently fails with HTTP 500/404. `websocket-client` (import as `websocket`) works but the `send()` method needs a retry loop with `WebSocketTimeoutException` handling. **Node.js `ws` module is the most reliable** for Chrome 147+ CDP connections.
- **Detail pages still blocked:** Even with valid cookies injected, `/explore/<noteId>` detail pages may show "当前笔记无法浏览". Full body content, author bio, and detail-level engagement numbers are unavailable on the web version.
- **Search API only returns ~20 results:** The API endpoint `so.xiaohongshu.com/api/sns/web/v2/search/notes` returns `has_more: true` but the web page cannot load subsequent pages. Direct API calls with `page=2` fail with "create invoker failed, service: jarvis-gateway-default". **However**, pagination IS possible via the Vue 3 Pinia store's `searchNotes({page: N})` action — see `references/xiaohongshu-collection.md` section "Pagination via Pinia store actions". The `scripts/xhs-pinia-pagination.js` script implements a complete paginated collection workflow. Yield per additional page is only 1–2 new unique items, so use multiple keywords for large targets.