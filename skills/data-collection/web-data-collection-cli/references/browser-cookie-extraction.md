# Browser Cookie Extraction via CDP

Generic technique to extract authenticated cookies from a Chromium-based browser (Edge, Chrome, Brave) using the Chrome DevTools Protocol (CDP). Use when a web data collection task needs a logged-in session for curl or a CLI tool.

## When to use

- User has an active authenticated session in a browser (Edge/Chrome)
- You need cookies for curl, wget, or a CLI tool that supports `-b cookies.txt`
- Bazhuayu or other collection tools cannot reuse the browser's profile directly
- The site requires login and the user doesn't want to enter credentials again

## Workflow

### 1. Start browser with remote debugging

```bash
# Kill existing browser process first
kill $(pgrep -f microsoft-edge | head -5) 2>/dev/null

# Start with CDP flags
microsoft-edge \
  --remote-debugging-port=9222 \
  --remote-allow-origins=* \
  --no-sandbox \
  --disable-gpu \
  --user-data-dir=/tmp/edge-debug-profile \
  "https://target-site.com/" &
```

**Key flags:**
- `--remote-debugging-port=9222` — enables CDP HTTP/WS endpoint
- `--remote-allow-origins=*` — allows WebSocket connections from any origin (without this, `ws://` gets 403 Forbidden)
- `--user-data-dir=/tmp/...` — uses a fresh profile; omit to reuse the default profile (which has existing cookies)
- `--no-sandbox` — needed on WSL/Linux

### 2. Discover page target

```bash
# Get browser version and WebSocket URL
curl -s http://127.0.0.1:9222/json/version

# List all pages/tabs
curl -s http://127.0.0.1:9222/json | python3 -m json.tool
```

Note the page ID (e.g. `586D7651368A572E0E90907062B00102`) and its `webSocketDebuggerUrl`. Page IDs change on every browser restart.

### 3. Extract cookies via CDP

#### Option A: Python (websocket-client library — recommended for simplicity)

```python
from websocket import create_connection
import json

ws = create_connection("ws://127.0.0.1:9222/devtools/page/<PAGE_ID>", timeout=10)

# Enable Network domain
ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
ws.recv()

# Get all cookies
ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
resp = json.loads(ws.recv())
cookies = resp["result"]["cookies"]

# Filter by domain
target_cookies = [c for c in cookies if "example.com" in c.get("domain", "")]
ws.close()
```

Install: `pip install websocket-client` (NOT `websockets` — see pitfall below).

#### Option B: Node.js (ws module — reliable fallback when Python fails)

```javascript
const WebSocket = require('ws');
const http = require('http');

http.get('http://localhost:9222/json', (res) => {
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => {
    const tabs = JSON.parse(data);
    const tab = tabs.find(t => t.title.includes('目标站点'));
    if (!tab) { console.log('Tab not found'); process.exit(1); }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    ws.on('open', () => {
      ws.send(JSON.stringify({id: 1, method: 'Storage.getCookies', params: {}}));
    });
    ws.on('message', (data) => {
      const resp = JSON.parse(data.toString());
      if (resp.id === 1) {
        const cookies = resp.result?.cookies || [];
        console.log(JSON.stringify(cookies, null, 2));
        ws.close();
      }
    });
    ws.on('error', (err) => { console.log('WS error:', err.message); process.exit(1); });
  });
});
```

The `ws` module is a Node.js built-in compatible package. Install: `npm install ws`.

### 4. Export formats

**Netscape format** (for `curl -b`):

```
# Netscape HTTP Cookie File
domain<TAB>flag<TAB>path<TAB>secure<TAB>expiry<TAB>name<TAB>value
.weibo.com	TRUE	/	TRUE	1819092298	SUB	_2AkMd...
```

Usage:
```bash
curl -b cookies.txt "https://weibo.com/ajax/..."
```

**JSON format** (for programmatic use):

```python
import json
with open("cookies.json") as f:
    cookies = json.load(f)
sub = cookies["SUB"]
```

## Pitfalls

- **Page ID changes on restart:** After killing and restarting the browser, always re-discover page IDs via `/json` endpoint.
- **WebSocket 403:** Caused by missing `--remote-allow-origins=*`. The error message tells you the exact flag to add.
- **No cookies returned:** The browser may have started a new profile (`--user-data-dir`). Omit this flag to reuse the default profile, or ask the user to log in again.
- **Sandbox error on Linux:** Add `--no-sandbox` when running inside WSL or containers.
- **Browser window not visible:** The browser process may be running without a window (headless behavior). It still processes pages and cookies — CDP works regardless.
- **Multiple target pages:** If the same URL opened multiple tabs, use the first one. Any page in the same browser instance shares the same cookie jar — `Network.getAllCookies` returns all cookies for the entire browser.
- **Session cookies vs. persistent:** Cookies with `expires: -1` or `session: true` are session cookies. They're valid for the current browser session but won't survive a restart. Extract them before closing the browser.
- **Python `websockets` v17+ vs `websocket-client`:** The `websockets` library (v17+, package name `websockets`) frequently fails to connect to Chrome CDP with HTTP 500 (page-level WS) or 404 (browser-level WS). Use `websocket-client` (package name `websocket-client`, import as `websocket`) instead. If both Python libraries fail, fall back to Node.js with the `ws` module (Option B above) — it reliably connects to Chrome/Edge CDP.

## Cookie injection (reverse operation)

When a user provides cookies as JSON (from EditThisCookie, browser extension, or manual export), inject them into a running browser via CDP:

1. **Clear existing cookies** for the target domain via `Storage.deleteCookies` so the new ones take effect.
2. **Set each cookie** via `Storage.setCookie` — the `url` parameter must be a full URL like `https://www.xiaohongshu.com/`; do NOT use a bare domain.
3. **Navigate** to the target page — the cookie jar is now populated.

Critical: `Storage.setCookie` expects `url` (full URL), not just `domain`. The domain in the cookie's `domain` field should start with `.` for subdomain-wide cookies (e.g., `.xiaohongshu.com`). Session cookies (no `expires`) are set by omitting the `expires` parameter.

See `references/xiaohongshu-cdp-cookie-injection.md` for the complete Node.js implementation with all edge cases handled.