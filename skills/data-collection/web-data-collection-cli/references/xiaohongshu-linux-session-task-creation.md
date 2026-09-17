# Xiaohongshu Linux session handoff and task-quality gate

Use for Bazhuayu local task creation on Linux when the user has completed login in a persistent Chrome/Win-KeX browser but Bazhuayu's independent detector opens an unsigned-in temporary profile.

## Problem boundary

A cookie-only session saved under `~/.octopus/browser-sessions/<name>.json` is normally consumed by `bazhuayu run` only after a task exists. It does not, by itself, authenticate the independent **detect** browser. Do not infer that a visible signed-in persistent browser means a newly launched detector is authenticated.

## `--manual` detect interruption pitfall

`bazhuayu detect <url> --manual` opens a Chrome window and waits for the user to press Enter after completing login. When run via an agent terminal tool, this command is **easily interrupted** (exit code 130 = SIGINT) because:
- The terminal tool may timeout or kill the process group
- The user pressing Ctrl+C in the terminal interrupts the wait
- Each retry opens a **fresh Chrome** with no saved session, so the login wall reappears

**Do not endlessly retry `--manual` when it keeps getting interrupted.** Instead, fall back to manual task file creation (see below).

## Manual task file creation fallback

When `--manual` detect repeatedly fails, create a local task `.json` file directly with the correct structure and a `detection.session` reference to an existing cookie session. The resulting file can be validated and run with `--task-file`, bypassing the detect flow entirely.

### Task file format

```json
{
  "taskId": "my-task-id",
  "taskName": "小红书关键词搜索_AI",
  "xml": "<ns0:RootAction ...><ns0:NavigateAction URL=\"https://www.xiaohongshu.com/search_result?keyword=AI&amp;source=web_search_result_notes\" .../><ns0:ExtractDataAction .../></ns0:RootAction>",
  "fieldNames": ["title", "author", "time", "likes", "url"],
  "detection": {
    "url": "https://www.xiaohongshu.com/search_result?keyword=AI&source=web_search_result_notes",
    "session": "xhs-login-ai",
    "search": {
      "keyword": "AI",
      "type": "search_result"
    }
  }
}
```

Key elements:
- **`taskId`**: Any unique string (UUID or human-readable)
- **`xml`**: XAML workflow with `NavigateAction` (set `URL` to the search page; use `&amp;` for `&` in URLs) and `ExtractDataAction`
- **`detection.session`**: Name of a saved session under `~/.octopus/browser-sessions/<name>.json`. The Bazhuayu runner injects these cookies before navigation.
- **`detection.search`**: Optional metadata indicating this is a search-type task

### Validation and usage

```bash
# Validate the task file
bazhuayu task validate <taskId> --task-file <path.json> --json

# Run locally (injects session cookies)
bazhuayu run <taskId> --task-file <path.json> --max-rows 20 --json
```

### Changing keywords

Edit the `URL` field in the XML's `NavigateAction` to change the search keyword. The URL-encoded `keyword=` parameter controls the search term. String-replace it to spawn keyword variants.

### When this approach is appropriate

- `--manual` detect keeps getting interrupted by terminal tool timeouts/SIGINT
- A valid session file already exists under `~/.octopus/browser-sessions/`
- The user only needs search-card data (not detail pages, which are blocked by Xiaohongshu)
- The task XML does not need sophisticated extraction logic — a basic Navigate + Extract is sufficient

### Cloud task list visibility (important)

A manually created local task file is **not** visible in `bazhuayu task list`. The list command queries the cloud API, not the local filesystem. When the user asks "why isn't it in the task list", explain:

- The task is a local file, not a cloud-saved task
- It can still be run with `bazhuayu run <taskId> --task-file <path.json>`
- The `--task-file` flag bypasses the cloud API, so it also avoids the free-plan 100-task limit
- To save it to the cloud, the user would need to use `detect` (auto/manual/agent) or `template-task create` -- which requires interactive terminal input for login-gated sites

## Safe handoff pattern

1. Export only same-site cookies from the user-authorized browser CDP session; never print values. Store a cookie-only session with `0600` permissions and verify name, count, and allowed hosts.
   - **CDP cookie extraction:** Use `Storage.getCookies` method (not `Network.getAllCookies`). Prefer Node.js `ws` module over Python `websockets` library — `websockets` v17+ frequently fails with HTTP 500/404 on Chrome 147+. See `references/browser-cookie-extraction.md` for both approaches.
   - **Bazhuayu session file format:** `{"kind": "cookie", "name": "<name>", "cookies": [{"domain": "...", "name": "...", "value": "...", "path": "/", "secure": bool, "httpOnly": bool, "expires": 0}]}`
   - **Xiaohongshu login state** requires ~18 cookies including `a1`, `web_session`, `id_token`, `websectiga`, `sec_poison_id`, `abRequestId`. A session file with only 5-10 cookies (missing `a1` or `web_session`) is not authenticated — verify count before proceeding.
2. **Cookie injection via CDP (user-provided cookies):** When the user provides cookies directly, inject them via `Storage.setCookie` instead of requiring a login flow. Clear existing cookies first with `Storage.deleteCookies`, then set each cookie. Cookies set this way are ephemeral — they work for the current CDP session but may not persist across Chrome restarts. Always also save the session file under `~/.octopus/browser-sessions/` for `bazhuayu run` usage.
3. For a CLI runtime that lacks a documented detector-session input, use a narrowly scoped local compatibility patch or an upstream-supported equivalent that loads only the named cookie session before navigating the detector target. The patch must be generic (session-name based), must not hard-code cookie values, and must be documented/reversible.
4. Run `detect --prepare-agent` on the exact filtered search URL. Verify the resulting `finalUrl` still carries the content-type filter (for this session, the platform used `type=51`).
5. Open the candidate crop and choose the repeated main result-card candidate, not a whole-page/detail-shell candidate merely because it has a higher detector score.

## Non-negotiable quality gate

`detect --preview-agent-plan` returning `pass: false` is a hard stop. Do **not** apply or run that plan. Repair the plan first, particularly when it reports a list URL field with no detail plan while the requested schema requires full post body, comments, or favourites.

A `bazhuayu run` result with `status: completed` and `total: 0` is an unsuccessful sample, not evidence that collection began. Inspect the run artifacts and repair authentication, navigation/filter state, or selectors before any bulk run.

## Field coverage

The Xiaohongshu search-card candidate observed here reliably exposed note URL, author, relative time, and likes. It did not establish title/body, comment count, or favourite count. For a schema requiring those fields, validate a list-with-detail plan on representative notes before bulk collection. Do not fill missing fields from guesses or describe a list-card summary as full body.
