# Xiaohongshu authenticated CDP card fallback

Use only after the Bazhuayu task path has been sampled and shown a structural runner failure (for example, navigation succeeds but the generated list loop produces zero rows), and the user has authorized collection from their logged-in browser.

## Purpose and limits

- Attach only to a user-maintained Chrome DevTools endpoint bound to localhost (the host used `127.0.0.1:9222`).
- Operate the existing signed-in tab; do not close the browser or bypass login/CAPTCHA.
- Navigate one keyword at a time to the official `search_result_ai` URL with the user-selected type parameter. Verify the tab remains on a search-result URL before extracting.
- **Known limitation:** Xiaohongshu search returns only ~20 unique notes per keyword. `has_more: true` is returned but subsequent pages cannot be loaded. Plan for multiple keywords to reach higher counts.
- **Known limitation:** Detail pages (`/explore/<noteId>`) show "当前笔记无法浏览" even with valid login cookies. Full body content, author bio, and detail-level engagement numbers are unavailable.

## API interception (preferred)

**This is the recommended approach.** Instead of parsing the DOM, intercept the page's own API call to `so.xiaohongshu.com/api/sns/web/v2/search/notes` via CDP `Network.enable` + `Network.getResponseBody`. This returns the full JSON response including comments, favorites, and shares — fields the DOM does not expose.

**CDP interception workflow:**
1. Before navigation, send `Network.enable`.
2. Navigate to the search URL.
3. Listen for `Network.responseReceived` events where `params.response.url.includes('search/notes')` — save the `requestId`.
4. On `Network.loadingFinished` for that `requestId`, call `Network.getResponseBody({requestId})`.
5. Parse the JSON body — `data.items[].note_card.interact_info` contains `liked_count`, `comment_count`, `collected_count`, `shared_count`; `corner_tag_info[0].text` contains the publish time.

**Example API response:**
```json
{
  "success": true, "data": {
    "has_more": true,
    "items": [{
      "id": "69a70912000000002800b144",
      "note_card": {
        "display_title": "灵感分享·抹茶",
        "user": { "nickname": "小北" },
        "interact_info": {
          "liked_count": "1029", "comment_count": "4",
          "collected_count": "374", "shared_count": "32"
        },
        "corner_tag_info": [{"text": "03-04"}]
      }
    }]
  }
}
```

**Node.js CDP implementation pattern:**
```javascript
const ws = new WebSocket(tab.webSocketDebuggerUrl);
let apiRequestId = '';
ws.on('message', msg => {
  const m = JSON.parse(msg.toString());
  if (m.method === 'Network.responseReceived' && m.params.response.url.includes('search/notes')) {
    apiRequestId = m.params.requestId;
  }
  if (m.method === 'Network.loadingFinished' && m.params.requestId === apiRequestId) {
    send('Network.getResponseBody', {requestId: apiRequestId}).then(r => {
      const data = JSON.parse(r.result.body);
      // data.data.items contains all fields
    });
  }
});
await send('Network.enable');
await send('Page.navigate', {url: searchUrl});
await sleep(8000);
```

## DOM extraction (fallback)

When API interception is unavailable, extract from the DOM. See `references/xiaohongshu-collection.md` section "Search card DOM structure" for the accurate selectors.

## Reliable loop

1. Discover the page through `/json` and require a URL matching `xiaohongshu.com/search_result`.

1. Discover the page through `/json` and require a URL matching `xiaohongshu.com/search_result`.
2. Extract current `section.note-item` cards with stable card URL as deduplication key, append JSONL immediately, then scroll.
3. Stop only after multiple consecutive no-new-card rounds. Record round count, unique rows, and last added count in `state.json`.
4. Parse the final JSONL defensively and verify: total rows, malformed lines, distinct links, and field fill rates.
5. If the site redirects to `/explore`, inspect visible page text/DOM for an active login form. Pause and ask the user to reauthenticate; do not collect the unauthenticated recommendation stream.

## Scope caveat

A UI “图文” filter parameter may still yield heterogeneous cards. Preserve visible `content_type` evidence and document the filter state; do not claim a pure content-type dataset without record-level verification.
