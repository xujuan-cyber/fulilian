# Xiaohongshu collection (Bazhuayu)

Use when the user asks to collect Xiaohongshu (小红书) notes by keyword with Bazhuayu CLI.

## Do not invent a login window

On this WSL host, `bazhuayu detect --manual` does **not** open a window the user can see if `DISPLAY` is empty. `doctor` can still say Chrome is ready because non-manual runs use Xvfb. Treat these as separate:

- `DISPLAY` unset + `Missing X server or $DISPLAY` → no login UI was shown. Stop. Do not paste a command and ask the user to log in.
- A leftover `/tmp/.X11-unix/X1` socket is not proof a desktop is running. Check `echo $DISPLAY`, `ls /tmp/.X11-unix`, and whether a VNC/KeX process exists.

## Visible login path that already worked (Zhihu, same host)

1. Tell the user the Chrome window appears on the **Win-KeX / TigerVNC desktop**, not in the Windows browser and not in the CLI terminal.
2. Launch independent Chrome on a real display (`DISPLAY=:1` when KeX/TigerVNC is up) with a **persistent** `--user-data-dir` plus `--remote-debugging-port=<port>` (use a unique port like 9333 to avoid conflicts with Edge/other Chrome instances). Example used: `/home/xujuan/bazhuayu_output/xhs_browser_profile`.
3. After the user says they logged in, verify that the rendered page is authenticated (account navigation plus ordinary content cards), not merely that Chrome launched. Do not infer login from process start.
4. If Bazhuayu cannot reuse that profile, keep the signed-in Chrome on localhost-only CDP, extract **same-site cookies only** via the `Storage.getCookies` CDP method, write `~/.octopus/browser-sessions/<name>.json` (`kind: cookie`, mode `0600`), then sample.
   - **CDP extraction:** Node.js `ws` module is more reliable than Python `websockets` for Chrome 147+ CDP connections (Python `websockets` v17+ frequently returns HTTP 500/404). See `references/browser-cookie-extraction.md` for both approaches.
   - **Verify the session file:** check `name`, cookie count (Xiaohongshu needs ~18 cookies including `a1`, `web_session`, `id_token`, `websectiga`), allowed hosts, and `0600` mode. A session with <10 cookies is likely not authenticated.
   - Prefer CDP `Storage.getCookies`; modern Chrome may not expose legacy `Network.getAllCookies`. Filter domains to `(^|.)xiaohongshu.com`, never print cookie values.

See `references/zhihu-authenticated-fallback.md` for the CDP/cookie handoff.

## Task path

- `template search 小红书` returned **zero** templates (2026-08-14). Do not wait on a marketplace template.
- Build from a search/explore URL via `detect` **after** a verified session, or clone a validated local task JSON and swap the keyword in Navigate/EnterText XAML.
- User-browser mode (`bazhuayu browser use user`) is **unsupported on Linux**; stay on independent Chrome + saved session.
- A signed-in persistent Chrome and a cookie-only session file do **not** prove that Bazhuayu's separate manual-detector window is authenticated. If that window is redirected to `/explore` or presents a login modal, pause for the user to complete login there and save a session from that browser before claiming search readiness.

## Search filters and content type

When the user requests 图文 (image-and-text) notes, selecting the content type is a required collection-state step, not an optional UI preference:

1. In the authenticated **manual detector browser**, enter the intended keyword through the site search field and submit it. Confirm the visible URL/result heading is a search-result page; an `/explore` recommendation page is not evidence that the query was applied.
2. On the current `/search_result_ai?keyword=...` page, the result tabs (`笔记` / `用户` / `问点点`) are distinct from the content-type filter. Open the visible `已筛选` control (commonly DOM class `filter active`); in its `filter-panel`, select `笔记类型 → 图文`. Check the 图文 tag state first: it commonly has class `tags active` when already selected. Do **not** click an already-active tag, because this can remove the required restriction. The filter applies immediately (the observed panel uses `重置` and `收起`, not a separate confirmation button). Verify the active state and that result cards remain/refresh before detection or selector recording.
3. If a localhost-only Chrome DevTools Protocol connection is available for the signed-in native browser, use DOM inspection of `filter`, `filter-panel`, and `tags` as a coordinate-independent verification fallback. Never print or expose cookie values.
4. Preserve the filtered result URL/state in the generated task. If a detector starts from a generic explore URL, do not assume it retained the filter; re-check it during the sample run.
5. If a login, SMS, QR, CAPTCHA, or other account challenge overlays the page, do not click through it or enter credentials. Request the user to complete it, then resume from step 1.

## Fields for this research schema

Map extractor output to:

| 字段名 | 来源 |
|---|---|
| 关键词或板块 | search keyword / note topic |
| 发帖链接 | note URL (canonical, drop query) |
| 发帖人 | author nickname |
| 发布时间 | note-page time |
| 帖子正文 | title + body |
| 评论数 / 点赞数 / 收藏数 | note engagement |
| 平台 | fixed `小红书` |

Deduplicate globally by canonical note URL. Keep keyword on every row. Target counts (e.g. 8000) stay **in progress** until the verified unique-URL count hits the number or every keyword route has an evidence-based blocker.

## Parallel runs

User asked to run several Xiaohongshu keywords in parallel after login. Cap concurrent browsers at 2–3 on a laptop-class host. Sample one keyword first; only then fan out.

## Linux detector-session handoff and task-quality gate

A cookie-only session is usually injected only by `bazhuayu run` after a task exists; it does not automatically authenticate a fresh independent detector. After user-authorized login in persistent Win-KeX Chrome, export only same-site cookies (never values), verify a `0600` session record, and use an upstream-supported detector handoff—or a narrow, reversible session-name-based compatibility patch—before detecting the filtered URL.

**Hard gate:** do not apply or run an agent plan when `detect --preview-agent-plan` reports `pass: false`. A list-only plan cannot meet a requested full-body/comments/favourites schema. Likewise, `status: completed` with `total: 0` is an unsuccessful sample, not collection progress. Repair and revalidate before bulk collection. See `references/xiaohongshu-linux-session-task-creation.md`.

## Search page limitations

- **~20 results per page, but pagination is possible via Pinia store.** Xiaohongshu search returns ~20 notes per API call. Scrolling the DOM does NOT trigger page 2. However, the page's internal state management (Vue 3 + Pinia) exposes actions that can load subsequent pages. See "Pagination via Pinia store actions" below.
- **Detail pages blocked.** Even with valid login cookies, navigating to a note detail page (`/explore/<noteId>`) shows "当前笔记暂时无法浏览" (this note cannot be viewed temporarily). The page's bottom navigation bar replaces the actual note content. Do not infer a login failure from this — the restriction is a platform-level access control. Content fields (full body, author bio, engagement numbers beyond the card) are unavailable even with a valid session.

## API interception (preferred over DOM extraction)

When the browser is already authenticated and a search page is open, intercept the page's own API call to `so.xiaohongshu.com/api/sns/web/v2/search/notes` via CDP `Network.enable` + `Network.getResponseBody`. This returns the full structured JSON response including fields the DOM does not expose:

**API response structure:**
```json
{
  "success": true,
  "data": {
    "has_more": true,
    "items": [
      {
        "id": "<noteId>",
        "note_card": {
          "display_title": "...",
          "user": { "nickname": "...", "nick_name": "..." },
          "interact_info": {
            "liked_count": "1029",
            "comment_count": "4",
            "collected_count": "374",
            "shared_count": "32"
          },
          "corner_tag_info": [{ "text": "03-04" }]
        }
      }
    ]
  }
}
```

**CDP interception workflow:**
1. Launch Chrome with `--remote-debugging-port=<port>` and `--user-data-dir=<persistent profile>`.
2. Navigate to the search URL (e.g. `https://www.xiaohongshu.com/search_result?keyword=AI%E7%94%9F%E6%88%90&type=51`).
3. Before navigation, send `Network.enable` to start capturing.
4. On `Network.responseReceived` where `params.response.url` includes `search/notes`, save the `requestId`.
5. On `Network.loadingFinished` for that `requestId`, call `Network.getResponseBody({requestId})`.
6. Parse the JSON body — it contains all items with `interact_info` (likes, comments, collections, shares) and `corner_tag_info` (time).

**Why API interception over DOM:**
- DOM extraction from `.note-item` cards only yields title, author, time, and likes.
- API interception yields **comments, favorites, and shares** which the DOM does not expose.
- API data is structured JSON, no parsing ambiguity.

## Pagination via Pinia store actions (Vue 3)

Xiaohongshu search uses Vue 3 + Pinia for state management. The API call (`POST` to `so.xiaohongshu.com/api/sns/web/v2/search/notes`) is signed with anti-bot headers (`X-s`, `X-S-Common`, `x-rap-param`, `X-t`) that are computed from the request body. This means:
- `fetch()` / `XMLHttpRequest` from injected JS **fails** — the gateway returns 404 because the signature doesn't match.
- Modifying the URL and resending via Node.js `https` **fails** — same signature mismatch.
- **Calling the Pinia store's actions directly works** — the framework computes the correct signature internally.

### Pinia store structure

The app has a `search` Pinia store with these key actions:

| Action | Purpose |
|--------|---------|
| `searchNotes(params)` | Full search with pagination. Pass `{keyword, page, pageSize, sort, noteType, extFlags, imageFormats}` |
| `loadMore()` | Incremental load (next page) |
| `fetchNotePageData({page, pageSize})` | Fetch specific page data |
| `setNotes(notes)` | Manually set note data |

### CDP access pattern

```javascript
// 1. Find the Vue app
const appEl = document.querySelector('#app');
const vueApp = appEl.__vue_app__;
const pinia = vueApp.config.globalProperties.$pinia;

// 2. Get the search store
const searchStore = pinia._s.get('search');

// 3. Call searchNotes with page parameter
await searchStore.searchNotes({
  keyword: 'AI生成',
  page: 2,                   // increment this for each page
  pageSize: 20,
  sort: 'general',
  noteType: 0,
  extFlags: [],
  imageFormats: ['jpg', 'webp', 'avif']
});
```

### Full pagination workflow

1. Launch Chrome with `--remote-debugging-port=<port>` and `--user-data-dir=<persistent profile>`.
2. Navigate to the search URL (e.g. `https://www.xiaohongshu.com/search_result?keyword=AI%E7%94%9F%E6%88%90&type=51`).
3. Enable `Network.enable` to capture API responses.
4. Wait for page 1 to load (the initial API call returns ~20 items).
5. Loop through pages 2..N, calling `searchStore.searchNotes({page: N, ...})` via `Runtime.evaluate`.
6. Capture each API response via `Network.getResponseBody` (listen for `Network.responseReceived` where URL includes `search/notes`, then `Network.loadingFinished`).
7. Parse JSON bodies — each returns `data.items[]` with complete `interact_info`.
8. Deduplicate globally by `item.id` (note ID).

### POST request body structure

```json
{
  "keyword": "AI生成",
  "page": 1,
  "page_size": 20,
  "search_id": "2gsyiumx2y5n6wdio1cin",
  "sort": "general",
  "note_type": 0,
  "ext_flags": [],
  "image_formats": ["jpg", "webp", "avif"],
  "session_id": "59814403-4118-46e3-9045-795933cdde2a"
}
```

The `search_id` and `session_id` are generated by the page on first load and available in the Pinia store (`searchStore.searchContext.searchId` and `searchStore.sessionId`). The page's own framework handles these automatically when calling store actions.

### API response structure

```json
{
  "success": true,
  "data": {
    "has_more": true,
    "items": [{
      "id": "69a70912000000002800b144",
      "xsec_token": "AB7ob1Ye66...",
      "note_card": {
        "display_title": "灵感分享·抹茶",
        "user": { "nickname": "小北" },
        "interact_info": {
          "liked_count": "1029",
          "comment_count": "4",
          "collected_count": "374",
          "shared_count": "32"
        },
        "corner_tag_info": [{ "text": "03-04" }]
      }
    }]
  }
}
```

### Key anti-bot headers (context, not forgeable)

```
X-t: 1787566867724           (timestamp)
X-s: XYS_2UQhPsHCH0c1+...   (body signature)
X-S-Common: 2UQAPsHC+sI...  (common signature)
x-rap-param: ByQBBgAAAA...  (encrypted request params)
x-b3-traceid: 0b52d0d4a...  (trace ID)
x-xray-traceid: d019a4e2... (xray trace ID)
```

These headers are computed by the framework's internal HTTP client and CANNOT be replicated from outside. Always use the Pinia store actions to make paginated requests.

### Yield estimation (IMPORTANT — pagination is very inefficient)

- **Page 1** returns ~20–22 unique items with full data.
- **Subsequent pages** (2..N) each return ~20 items, but **only 1–2 are new unique items** — the rest are duplicates from page 1. This means single-keyword pagination is very inefficient. After 30 pages you may only get ~50 unique items, with ~30 having incomplete data because they come from later pages where the API response structure is sparser.
- `has_more: true` is returned reliably through at least 30 pages.
- **For 5000 items:** single-keyword pagination is NOT viable. Use **multiple keywords** instead (e.g. `AI生成`, `AI绘画`, `AI写作`, `AIGC`, `AI工具`, `人工智能`). Each keyword yields ~20 unique items. 250 keywords × 20 = 5000.
- Rate limit: add 500ms–1s delay between page calls to avoid triggering rate limiting.
- Deduplication: use `item.id` as the canonical key. Some items may appear across pages (observed in testing); filter with a Set.

## Search card DOM structure (for DOM extraction fallback)

When API interception fails, extract from the rendered `.note-item` cards:

```
.note-item
  ├── a.cover.mask > img
  └── .footer
       └── .card-bottom-wrapper
            ├── a.author
            │    └── .name-time-wrapper
            │         ├── .name   (author nickname)
            │         └── .time   (relative time, e.g. "5小时前", "03-04")
            └── .like-wrapper
                 └── .count       (likes count)
```

**CSS selectors:**
```javascript
const nameEl = card.querySelector('.name-time-wrapper .name');
const timeEl = card.querySelector('.name-time-wrapper .time');
const countEl = card.querySelector('.like-wrapper .count');
const title = card.querySelector('[class*="title"]')?.textContent || img?.alt || '';
```

The `author` field is the `.name` text (pure nickname, NOT combined with time). The `.time` field is separate. Likes come from `.count` inside `.like-wrapper`. The `like-wrapper` may have class `like-active` when the current user has liked it — the selector `.like-wrapper .count` works regardless.

## Cookie injection via CDP (user-provided cookies)

When the user provides cookies directly (as JSON array), inject them into the browser via CDP instead of requiring a login flow:

1. Convert user's cookie format to CDP-compatible: `{domain, name, value, path, secure, httpOnly, expires}`.
2. Clear existing cookies first: `Storage.deleteCookies({name, url})` for each xiaohongshu.com cookie.
3. Set each cookie: `Storage.setCookie({name, value, url, domain, path, secure, httpOnly, expires})`.
4. Navigate to the search page and verify the page loads with authenticated content.
5. **Important:** Cookies set via CDP `Storage.setCookie` are ephemeral in the CDP session — they work for the current page loads but may not persist across Chrome restarts. Always save the session file under `~/.octopus/browser-sessions/` for `bazhuayu run` usage.

**Required cookies for Xiaohongshu login:** The platform requires ~18 cookies including `a1`, `web_session`, `id_token`, `websectiga`, `sec_poison_id`, `abRequestId`, `webId`, `gid`, `loadts`, `xsecappid`. A session with <10 cookies or missing `a1`/`web_session` is not authenticated.

## Authenticated search-card fallback

If the Bazhuayu task route remains structurally unable to enumerate rows after a verified, session-injected sample, do not bulk-run it. With explicit user authorization, a localhost-only CDP connection to the user's already logged-in browser may collect the visible search-card stream while keeping the browser open. Verify the tab is still a search-result URL before every keyword; a redirect to `/explore` accompanied by login text is an authentication checkpoint, not a valid data page. This fallback is card-level only: record exposed title/summary, URL, author, displayed time, likes, query, and platform, while leaving unavailable comments/favourites blank and labeling the body source. See `references/xiaohongshu-cdp-card-fallback.md`.