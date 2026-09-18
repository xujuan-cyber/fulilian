# Weibo local-task repair: homepage placeholder rows

## Symptom
A local `bazhuayu run` can exit successfully with `status: stopped`, `stopReason: max_rows`, and the requested row count, yet every saved row has only the query and empty author/time/content/link/engagement fields.

## Diagnosis
Check the sample `rows.jsonl` directly. Logs commonly include `Click.Error.NotFound`. In this session, legacy task files navigated to `https://weibo.com/`, which presented a login wall rather than search results.

## Repair pattern
1. Find a known-good local Weibo task that enters the search endpoint directly, e.g. `https://s.weibo.com/weibo?q=Deepfake`, and has the target extraction schema plus valid embedded cookie configuration.
2. Copy that task definition locally; do not alter remote tasks unless the user explicitly asks.
3. Set a distinct local `taskId` and task name.
4. Replace the source keyword everywhere it occurs in plaintext XAML, especially the `NavigateAction` URL and `EnterTextAction` input values. URL-encode the term in the navigation URL.
5. Run `bazhuayu task validate <taskId> --task-file <file> --json`.
6. Run a 5-row sample and require nonempty `博主昵称`, `发布时间`, `详情链接`, `博文内容`, `评论数`, and `点赞数` before the bulk run.

## Batch allocation example
For a user request of 50 pages total across six queries, estimate 20 results per page = 1,000 rows. A balanced cap of 167 rows per query yields 1,002 rows. Preserve all raw rows for the declared page snapshot; report duplicate detail links separately in `data_quality` rather than silently changing the requested collection volume.
