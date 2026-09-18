# Bazhuayu CLI: verified operating notes

## Minimal preflight
```bash
bazhuayu auth status
bazhuayu capabilities --json
bazhuayu doctor
```

The capability payload is the authoritative CLI workflow contract. For agent-created URL tasks, use its prepare → visual review/plan → preview → apply → validate flow rather than assuming a hand-written task definition or defaulting to automatic selection.

## Template checks
```bash
bazhuayu template search 微博 --json
bazhuayu template view <templateId> --json
bazhuayu template-task create <templateId> --name '<name>' --dry-run --json
bazhuayu template-task create <templateId> --name '<name>' --json
bazhuayu task list --keyword '<name>' --json
```

A creation response with `ok: true` but `data: {}` is not sufficient evidence. Require a task ID or a subsequent `task list`/`task show` match before telling the user a task was created.

## Existing task verification
```bash
bazhuayu task inspect <taskId> --json
bazhuayu task validate <taskId> --json
bazhuayu schedule cloud get <taskId> --json
```

Inspect shows expected field names/action types; validate confirms the task is structurally readable. Neither proves its search term is configurable.

## Template parameters vs hard-coded workflow
- `template view` returning `parameters: []` means the template has no declared CLI-editable input parameters.
- A workflow may still contain a fixed `EnterTextAction` search term. Do not use `template-task update` as a way to mutate that embedded action unless the template exposes a matching parameter.
- If search terms must vary, build a URL-driven task or use a properly parameterized template.

## WSL/Linux considerations
- Independent-browser workflows need a runnable browser runtime; headless Linux commonly needs `Xvfb` and browser libraries. Re-run `bazhuayu doctor` after installing prerequisites.
- Browser-profile reuse (`--browser user`) is platform-dependent; WSL/Linux should not be assumed to access the Windows Chrome/Edge signed-in profile.
- `doctor` errors distinguish environment prerequisites from API authentication. Report them separately.

## Cloud task limit (free plan)
- The free plan has a **100-task cloud limit**. When `detect` creates a task and cloud save fails with `"云端任务数量已达上限，无法保存任务。当前任务数 100，上限 100"`, the local task file is still written to disk.
- **Workaround:** Run the local file directly with `bazhuayu run <name> --task-file <path.json> [--max-rows N] [--output <dir>]`. The `--task-file` flag bypasses the cloud API and runs the task from the local definition.
- This also means `bazhuayu task list` and `bazhuayu task show <id>` will not find locally-saved tasks — they only query the cloud API. Always verify the local file exists on disk as evidence of creation.

## Douyin/SPA collection notes
- **SPA detection:** `bazhuayu detect --prepare-agent` on dynamic SPA pages (e.g. douyin.com/jingxuan) produces two candidates: a `detail_1` (navigation/page shell) and a `fallback_repeated_card_1` (video feed). Choose the `fallback_repeated_card_1` for feed/list collection.
- **Preview warning:** The preview may warn "list candidate rejected for detail goal" when the user goal mentions detail fields. This is a soft warning — `--apply-agent-plan` still works. Update the plan's `visualReview.evidence` to clarify the intent is feed/list, not detail.
- **XPath yield on dynamic pages:** SPA feeds like Douyin's 精选 may only populate the first card's XPath, leaving 4/5+ rows empty. Inspect `rows.jsonl` directly — a `stopReason: max_rows` confirms the runner saved rows, but their field content may be blank. Core fields may also capture wrong data (e.g. video duration `00:08` mapped to the `author` field). Always verify field semantics against the visible page before bulk collection.

## Batch collection evidence checklist
For every keyword: task identity, sample run status, sampled row count, representative field quality, final run/lot ID, final count, raw export path. Only then merge and write the Excel workbook.
