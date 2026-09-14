# FuLiLian CTF mini-corpus 与回归基线（P1-4）

这是修复计划 09 号卡的产出：一条命令可跑的题型回归 corpus + 故障注入用例 +
FTS5 检索金标 + 首跑基线。目的：**锁住"优化后解题能力不退化"**——P2 调参
（hard 保底槽位、EV 因子）落地前后各跑一次，对比基线即可量化行为变化。

## 目录结构

```
benchmarks/
  README.md               # 本文件
  manifest-unit.yaml      # unit 层：25 题型用例（5 类 × 5 题，全离线）
  manifest-smoke.yaml     # smoke 层：真题清单骨架（默认拒绝运行）
  fixtures/               # 本地构造题面与附件（每题含 solve_reference.py 参考解）
  fault-injection/        # 4 个故障注入场景说明（场景实现在 fulilian_ctf/benchmark.py）
  sampling/               # 检索金标抽样脚本（种子固定，可复现）
  retrieval-golden.yaml   # 21 条三档金标（P4.5）：smoke 5 / realistic 10 / robustness 6
  baselines/              # 首跑与历次基线 JSON
fulilian_ctf/benchmark.py # runner
```

## Suite 定义

| suite / 命令 | 内容 | 开销 | 网络/API |
|---|---|---|---|
| `--suite unit` | 25 个 fixture 走完整 solver_worker → verify 三重校验门 → FLAG 文件声明式提交链路（mock solver = 参考解脚本化；flag 提取/三门/落盘全是真实代码） | 秒级 | 无 |
| `--suite retrieval` | 21 条三档金标 query 对 `~/.fulilian/knowledge.db` 做 FTS5 top-5 检索（只读，`auto_build=False`，绝不写库）；结论看 realistic 档 | 秒级 | 无 |
| `--fault <scenario>` | empty-model / corrupt-blackboard / missing-fts5 / remote-down | 秒级 | 无（remote-down 只连本机保留端口 127.0.0.1:1） |
| `--all-faults` | 上面 4 个全跑 | 秒级 | 无 |
| `--suite smoke` | 真题真 API 冒烟（3 题） | — | **默认拒绝（exit 2）**，见 manifest-smoke.yaml 头部说明 |

## 一条命令出基线

```bash
cd ~/.fulilian/fulilian-agent

# unit 层（--validate-fixtures 额外打印每个 fixture 参考解自证明细；
# 不加该 flag 也始终内置自证，跑不通的题目如实标 skipped: fixture-invalid）
python3 -m fulilian_ctf.benchmark --suite unit --validate-fixtures

# 检索金标（只读 knowledge.db）
python3 -m fulilian_ctf.benchmark --suite retrieval

# 故障注入
python3 -m fulilian_ctf.benchmark --fault empty-model
python3 -m fulilian_ctf.benchmark --all-faults
```

输出：stdout 先 JSON（含每用例明细 + 每题型汇总），后 Markdown 汇总表。
每题型指标：**通过率 / 平均耗时 / 平均 token（mock 层恒为 None）/ 平均工具调用数**。

## 当前基线（首跑：2026-09-06，分支 feat/p1-4-corpus）

**unit（25/25，pass_rate=100%）**，基线文件 `baselines/2026-09-06-unit.json`：

| 题型 | 通过 | 通过率 | 平均耗时(s) | 平均token | 平均工具调用 |
|---|---|---|---|---|---|
| web     | 5/5 | 100% | 0.0655 | None (mock) | 3.4 |
| crypto  | 5/5 | 100% | 0.0324 | None (mock) | 3.6 |
| pwn     | 5/5 | 100% | 0.0406 | None (mock) | 3.2 |
| reverse | 5/5 | 100% | 0.0331 | None (mock) | 3.2 |
| misc    | 5/5 | 100% | 0.0254 | None (mock) | 3.0 |

**retrieval（P4.5 重构后的诚实基线，2026-09-14）**：基线文件
`baselines/2026-09-14-retrieval.json`。三档结果：

| 档 | 条数 | 结果 | 含义 |
|---|---|---|---|
| smoke | 5 | hit@5 = 100%（全 rank=1） | 接线自检：索引在、search() 通。**高分≠检索好**（query 由目标文档标题构造） |
| realistic | 10 | hit@5 = **20%**（2/10，rank 2 与 4） | 人工标注的解题者视角 query（标签经正文证据词 instr 核验）——这才是检索质量的真实水平 |
| robustness | 6 | 全部不抛异常 | 敌意 query（FTS 语法字符 / 操作符词 / 2 字中文"注入" / 单字符）；P4.2 sanitize 下沉后此档即其回归 |

旧基线 `2026-09-06-retrieval.json` 的 hit@5=1.0 是**自证**（P4.5 结论）：
query 由目标文档自己的标题构造，且 min_len=3 把 2 字中文结构性排除，
测不出检索质量，已废弃；对照数据见计划书 §9⑦。

**fault-injection**：4/4 passed（empty-model / corrupt-blackboard /
missing-fts5 / remote-down 均降级不崩 + 告警可见 + 后续题继续跑），基线文件
`baselines/2026-09-06-faults.json`。

## 如何对比（基线即锁）

任何架构/调度/verify 语义改动后，重跑并对比：

```bash
python3 -m fulilian_ctf.benchmark --suite unit \
    --baseline benchmarks/baselines/2026-09-06-unit.json
python3 benchmarks/eval_retrieval_golden.py \
    --baseline benchmarks/baselines/2026-09-14-retrieval.json
python3 -m fulilian_ctf.benchmark --all-faults \
    --baseline benchmarks/baselines/2026-09-06-faults.json
```

默认退化阈值（`fulilian_ctf/benchmark.py` 常量，可按需调整）：

- unit：每题型通过率降幅 > 5%（`PASS_RATE_DROP_LIMIT`）或平均耗时超过基线 3 倍
  （`TIME_FACTOR_LIMIT`）→ 退出码 1 并列出退化项；
- retrieval：hit@5 降幅 > 10%（`HIT_AT_5_DROP_LIMIT`）→ 退出码 1。

通过/耗时显著退化的判定输出在 stderr，JSON/MD 摘要在 stdout，便于 CI 抓取。

## fixture 契约（如何添加题目）

1. 新建 `benchmarks/fixtures/<id>/`，放题面（README.md / challenge 材料），
   并**必须**提供 `solve_reference.py`：

   ```python
   SOLUTION_STEPS = 2            # 参考解的工具步数（mock 层统计用）

   def solve(work_dir: str) -> str:
       """在 work_dir 内执行正确解题流程，返回"工具输出"文本。"""
   ```

2. 在 `manifest-unit.yaml` 增加条目（id/category/fixture/expected_flag/expect）。
3. 参考解红线：
   - 必须真的可解——runner 先在干净临时目录跑参考解过**真实** flag 门比对
     `expected_flag`；跑不通的题目在汇总里如实标 `skipped: fixture-invalid`
     并计入分母（不造假通过率）；
   - 参考解的输出里**不得出现真 flag 之外的 flag 形状字符串**（如原样密文、
     编码串）——flag 门按"首个被确认候选"提交，诱饵必须以非 flag 形状
     （截断 / hex / …）呈现；
   - flag 前缀覆盖多平台（NSSCTF{} / CTFshow{} / DASCTF{} / flag{} / ISCC{}…）
     ——这是 P0-1 flag 门修复的回归锁，新增题请继续扩展前缀多样性；
   - pwn 允许 `level: static` 静态档（strings / 反编译层可解），当前 5 道 pwn
     fixture 均为真实编译的 x86-64 ELF（gcc -O0 -no-pie，含 1 道编码 rodata）。

## 检索金标再生成

```bash
python3 benchmarks/sampling/build_retrieval_golden.py            # smoke 种子 20260905
python3 benchmarks/sampling/build_retrieval_golden.py --seed N --out ...
python3 benchmarks/eval_retrieval_golden.py --save-baseline      # 跑分并落新基线
```

P4.5 起金标三档：**smoke**（标题构造，接线自检）/ **realistic**（人工标注，
标注词经正文证据核验，语料与标注脱节会大声报错拒生成）/ **robustness**
（敌意 query，只测 search() 不抛异常）。换语料/换库后 realistic 档的
`REALISTIC_PAIRS` 标注要在 `build_retrieval_golden.py` 里人工维护。
重新生成会覆盖 `retrieval-golden.yaml`，须同步落新基线并在本文档记录
变更原因。脚本对 knowledge.db 以 URI 只读模式连接，绝不写库。

踩坑提醒：`writeups` 是 FTS5 trigram 虚拟表，其 **UNINDEXED 列**（如
source_path）上的 `LIKE` 依赖查询计划（L3 模式会错返 0 行）——库内过滤
用 `instr()` 或 `+col` 强制普通扫描，别信裸 LIKE。

## 已知边界 / 如实声明

- unit 层测的是**行为锁**（链路接线、flag 门语义、声明式提交），不是模型能力；
  真实解题能力由 smoke 层（真 API，待用户配置后启用）衡量。
- 故障注入 4 场景中，empty-model 用 stub 求解实现模拟 run_agent 的空模型
  400 失败（见 `solver.resolve_default_model` 文档），检验的是 solver_worker
  的故障隔离；remote-down 在求解侧做真实 socket 探测（本机 127.0.0.1:1，
  必然拒绝）后降级到本地静态路径。
