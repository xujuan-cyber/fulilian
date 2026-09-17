# Zhihu authenticated-browser fallback

Use this reference when Bazhuayu can launch Chrome but Zhihu home/search is classified as `DETECT_PAGE_BLOCKED` / `security_challenge`.

## Evidence-first sequence

1. Run `bazhuayu capabilities --json`, `bazhuayu auth status`, and `bazhuayu doctor`; preserve the detector error and exact URL.
2. Do not assume `--manual` means an indefinite login wait. The detector may perform its access check first and exit before the manual prompt.
3. Ensure `DISPLAY`/VNC or another visible display is actually reachable. A successful Chrome readiness check is not proof that the user can see the window.
4. If using an independent Chrome profile, launch it visibly with a dedicated persistent `--user-data-dir`; after the user logs in, restart that same profile with `--remote-debugging-address=127.0.0.1 --remote-debugging-port=<local-port>` so CDP can inspect the current tab.
5. Read `/json/version` and `/json/list` from the local CDP endpoint. Use `Network.getAllCookies` against the browser or the Zhihu search tab, retain only `.zhihu.com` / `www.zhihu.com` cookies, and write a `kind: cookie`, `compatibility: cookies-only` record under `~/.octopus/browser-sessions/<name>.json` with mode 0600.
6. Independently evaluate the logged-in tab: title, URL, and a bounded body snippet must show the requested result page rather than a login/challenge page.
7. For task creation, inspect template parameters. A template with `parameters: []` is fixed; a successful-looking create response with `data: {}` must be rechecked with `task list --template-id` and `task show` before use.
8. Validate Zhihu cards using `.ContentItem.AnswerItem`; collect answer links from `a[href*="/question/"][href*="/answer/"]`. Use the card for author/date/likes/comments, then open several answer URLs in rendered tabs and extract the longest non-style rich-text node from `.RichContent-inner`, `.Post-RichTextContainer`, `.RichText.ztext`, or `[itemprop="text"]`.
9. Only after sample fill rates pass should the bulk route scroll each keyword. Keep a keyword array per URL, deduplicate globally by canonical answer URL, retain `rows.jsonl`, and report raw/discovered/final counts plus any shortfall.

## Known session-specific observations

- In the validated run, the browser was reachable on `DISPLAY=:1.0` through TigerVNC/Win-KeX and the local CDP endpoint returned a Zhihu search tab.
- The rendered Zhihu search page exposed repeated `ContentItem AnswerItem` cards. Example card text included author, `赞同`, `条评论`, and date; detail pages exposed the author via `.AuthorInfo-name` and full text in rendered rich-text containers.
- The first Zhihu keyword page visibly contained only a small result set, so a target such as 8,000 must remain an open gap until all requested keywords and scroll routes are exhausted.

## Safety and quality

- This is session reuse, not CAPTCHA bypass: the user must complete the login/verification in the visible browser.
- Do not export cookies for unrelated domains, print cookie values, or claim a session was saved without reading back the file.
- Do not treat search snippets or AI-generated search panels as answer bodies; prefer the answer detail page and label any missing or truncated body explicitly.
