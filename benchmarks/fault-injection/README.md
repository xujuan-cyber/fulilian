# 故障注入 4 场景（P1-4）

场景实现集中在 `fulilian_ctf/benchmark.py` 的 `FAULT_SCENARIOS`（每个场景一个
`_FaultScenario` 子类），通过 runner 子命令触发：

```bash
python3 -m fulilian_ctf.benchmark --fault empty-model
python3 -m fulilian_ctf.benchmark --fault corrupt-blackboard
python3 -m fulilian_ctf.benchmark --fault missing-fts5
python3 -m fulilian_ctf.benchmark --fault remote-down
python3 -m fulilian_ctf.benchmark --all-faults          # 全部 4 个
```

统一骨架（`_run_two_challenge_scenario`）：对挑战 A 注入故障 → 断言降级不崩
（无未捕获异常逃逸出 solver_worker）→ 告警行打到 stderr（前缀
`[benchmark-fault][WARN]`）→ 挑战 B（正常）继续跑且解出 → 全部满足则
`"passed": true`、退出码 0；任一不满足退出码非 0。

| 场景 | 注入方式 | 期望降级行为（断言点） |
|---|---|---|
| `empty-model` | `resolve_default_model` 临时改为返回 `""`（模拟 config 未配 model.default），mock 求解实现遇到空模型名即抛错（模拟 run_agent 空模型名请求 API 得 400，见 `solver.resolve_default_model` 文档） | solver_worker 把失败装回 `SolverResult(ok=False, error=...)`，进程不崩；告警 2 条；后续题继续 |
| `corrupt-blackboard` | 挑战 A 的 `blackboard.json` 预置非法 JSON（`{"facts": [BROKEN!!!`） | `load_blackboard` 抛 JSONDecodeError 被 solver_worker 黑板接线吞成降级（只损失止损精度），解题照常解出；告警可见 |
| `missing-fts5` | `knowledge_retriever.DB_PATH/KB_PATH` 临时指向空临时位置（**真实 knowledge.db 不被触碰**）；并断言 `search(auto_build=False)` 对缺失库返回 `[]` 不抛 | `build_solve_query → inject_ctf_context` 全程 best-effort 静默降级，无 WP 参考也能解出；告警可见 |
| `remote-down` | 求解侧对 `127.0.0.1:1` 做真实 socket 探测（本机保留端口，必然 ConnectionRefused） | 探测失败告警后降级到本地静态信息收集路径，题照常解出；后续题继续 |

每个场景的落库结果（checks / warnings）见 `baselines/<date>-faults.json`。
