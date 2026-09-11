#!/usr/bin/env python3
"""CTF 路径（``fulilian solve``）基线采集器：读 work_dir 产物，不碰 solver 一行代码。

与 ``process_metrics.py`` 的分工：
  * ``process_metrics.py`` 读 state.db，量的是 **chat 路径**（人工解题）的过程指标
    M1–M6。CTF 层在那条路径上不参与，所以它测不出 CTF 求解器本身。
  * 本脚本读 ``fulilian solve`` 落在 work_dir 里的两份产物：
      - ``usage.json``  —— token / api_calls / attempts / cost
      - ``solver.log``  —— 逐次 API 延迟、缓存命中、逐个工具调用
    量的是 **CTF 路径**的 C1–C9，用于改动前后对照。

为什么必须另起一套：``usage.json`` 在 2026-09-11 之前**从未存在过** —— 因为
``fulilian solve <id> -p`` 被 argparse dest 冲突劫持到通用一次性对话分支
（``fulilian_cli/_parser.py`` 的顶层 ``-z/--oneshot`` 与 solve 子命令
``-p/--print`` 的 ``dest="oneshot"`` 同名），CTF 求解器根本没启动。修复见
提交 bbf054d。因此本脚本也是"CTF 路径确实被执行过"的见证工具。

已知局限：
  * ``solver.log`` 的 ``Making API call`` 计数会**低于** ``usage.json`` 的
    ``api_calls``（实测 crypto-rsa-01: 10 vs 24）—— 重试与压缩轮不会逐条落进
    日志。跨字段比较时以 usage.json 为准，日志只用于拆解结构。
  * 只看过程，不看能力：本脚本无法回答"agent 变聪明了吗"，那需要 holdout 真题。
  * ``work_dir/solver.log`` 是 **agent 的地盘** —— 它可以用 write_file 把它
    覆盖成解题报告（实测发生过）。给 ``--mirror-dir`` 时优先采信 solve 目录
    之外那份镜像（跑批器设 ``FULILIAN_SOLVER_LOG_MIRROR``）；没有镜像则回落
    work_dir，并对被扰动的那份报 ⚠️ 而不是把 0 读成"高效"。

用法：
    # 采集若干 work_dir
    python3 benchmarks/ctf_path_baseline.py --dirs /tmp/ctf-baseline/misc-morse-01 ...

    # 带期望 flag 交叉校验（读 benchmark manifest）
    python3 benchmarks/ctf_path_baseline.py --dirs ... \
        --manifest benchmarks/manifest-unit.yaml

    # 落基线
    python3 benchmarks/ctf_path_baseline.py --dirs ... --manifest ... \
        --json benchmarks/baselines/2026-09-11-ctf-path.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── solver.log 行型 ─────────────────────────────────────────────────────
# 格式来自 run_agent 的 verbose 输出，实测样本见 /tmp/ctf-baseline/*/solver.log

RE_API_CALL = re.compile(r"🔄 Making API call #(\d+)/(\d+)")
RE_API_LATENCY = re.compile(r"⏱️\s*API call completed in ([\d.]+)s")
RE_CACHE = re.compile(r"💾 Cache: ([\d,]+)/([\d,]+) tokens \((\d+)% hit, (\d+) written\)")
RE_REQ_SIZE = re.compile(r"📊 Request size: (\d+) messages, ~([\d,]+) tokens")
RE_TOOL_CALL = re.compile(r"📞 Tool \d+: ([a-zA-Z_][\w]*)\((.*?)\) - (.*)$")
RE_TOOL_ERR = re.compile(r"✅ Tool \d+ completed in [\d.]+s - \{\"error\"")

# 工具发现开销：CTF 工具被推迟（不在 _FULILIAN_CORE_TOOLS 里）时，模型必须先用
# 这些元工具问出签名。这两项占工具调用总数的比例 = 纯浪费的往返。
DISCOVERY_TOOLS = frozenset({"tool_describe", "tool_search"})
# shell 型工具 vs 读文件型工具：CTF 解题本该是 shell 驱动，read_file 占优说明
# 模型在"看"而不是"打"。
SHELL_TOOLS = frozenset({"terminal", "execute_code", "process"})
READ_TOOLS = frozenset({"read_file", "read_many_files", "search_files"})

FLAG_FILE = "FLAG"
SOLVER_LOG = "solver.log"
USAGE_FILE = "usage.json"
# 镜像日志的命名后缀，与 ctf_hard_run.sh 的 FULILIAN_SOLVER_LOG_MIRROR 取值配对
MIRROR_SUFFIX = ".solver.log"


# ── 解析 ────────────────────────────────────────────────────────────────

def _num(s: str) -> int:
    return int(s.replace(",", ""))


def parse_usage(work_dir: Path) -> dict[str, Any]:
    """读 usage.json。字段：input/output/cost/total_tokens、api_calls、attempts。"""
    p = work_dir / USAGE_FILE
    if not p.is_file():
        return {"present": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"present": False, "corrupt": True}
    if not isinstance(data, dict):
        return {"present": False, "corrupt": True}
    data["present"] = True
    return data


def mirror_path_for(work_dir: Path, mirror_dir: Path) -> Path:
    """镜像日志的约定路径：``<mirror_dir>/<fixture>.solver.log``。

    与 ctf_hard_run.sh 给 ``FULILIAN_SOLVER_LOG_MIRROR`` 的取值一致。
    """
    return mirror_dir / f"{work_dir.name}{MIRROR_SUFFIX}"


def parse_solver_log(work_dir: Path, mirror_dir: Path | None = None) -> dict[str, Any]:
    """从 solver.log 拆出 API 节奏、缓存命中、工具调用序列。

    优先读 ``mirror_dir`` 下的镜像副本：work_dir 是 agent 的地盘，它可以用
    write_file 覆盖掉那份日志（实测发生过）。镜像由 solver 侧的 tee 同时写，
    落在 solve 目录之外。没有镜像时回落 work_dir —— 老跑批的目录照常可采。
    """
    mirror = mirror_path_for(work_dir, mirror_dir) if mirror_dir else None
    if mirror is not None and mirror.is_file():
        p, source = mirror, "mirror"
    else:
        p, source = work_dir / SOLVER_LOG, "work_dir"
    out: dict[str, Any] = {
        "log_source": source,
        "log_present": p.is_file(),
        "api_call_lines": 0,
        "latencies_s": [],
        "cache_hits": [],          # [(hit, total, pct)]
        "cache_written": [],
        "request_tokens": [],
        "tool_calls": [],          # [{"name":..., "arg_keys":..., "body":...}]
        "tool_errors": 0,
    }
    if not out["log_present"]:
        return out

    text = p.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if RE_API_CALL.search(line):
            out["api_call_lines"] += 1
        if m := RE_API_LATENCY.search(line):
            out["latencies_s"].append(float(m.group(1)))
        if m := RE_CACHE.search(line):
            hit, total, pct, written = m.groups()
            out["cache_hits"].append((_num(hit), _num(total), int(pct)))
            out["cache_written"].append(int(written))
        if m := RE_REQ_SIZE.search(line):
            out["request_tokens"].append(_num(m.group(2)))
        if m := RE_TOOL_CALL.search(line):
            name, arglist, body = m.groups()
            out["tool_calls"].append({
                "name": name,
                # 只留参数键名与命令体：同一条命令重复执行才可见，值本身不进基线
                "arg_keys": [a.strip().strip("'\"") for a in arglist.split(",") if a.strip()],
                "body": body.strip()[:300],
            })
        if RE_TOOL_ERR.search(line):
            out["tool_errors"] += 1
    return out


def tool_signature(call: dict[str, Any]) -> str:
    """工具调用的可比指纹：名字 + 参数键序 + 命令体。

    只按名字去重会把"同样的 ls 跑三遍"算成不同调用；CTF 里重复执行同一命令
    是最该被量到的浪费，所以 body 必须进指纹。
    """
    return f"{call['name']}|{','.join(call['arg_keys'])}|{call['body']}"


# ── 单题指标 ────────────────────────────────────────────────────────────

def analyze(work_dir: Path, expected_flag: str | None = None,
            ref_steps: int | None = None,
            mirror_dir: Path | None = None) -> dict[str, Any]:
    usage = parse_usage(work_dir)
    log = parse_solver_log(work_dir, mirror_dir)

    flag_path = work_dir / FLAG_FILE
    flag = flag_path.read_text(encoding="utf-8", errors="replace").strip() if flag_path.is_file() else ""

    calls = log["tool_calls"]
    sigs = [tool_signature(c) for c in calls]
    distinct = len(set(sigs))
    repeats = len(sigs) - distinct

    name_counts: dict[str, int] = {}
    for c in calls:
        name_counts[c["name"]] = name_counts.get(c["name"], 0) + 1

    discovery = sum(name_counts.get(t, 0) for t in DISCOVERY_TOOLS)
    shell = sum(name_counts.get(t, 0) for t in SHELL_TOOLS)
    reads = sum(name_counts.get(t, 0) for t in READ_TOOLS)

    lats = log["latencies_s"]
    hits = log["cache_hits"]

    if not log["log_present"]:
        log_issue = "missing"
    elif usage.get("api_calls") and not log["api_call_lines"]:
        log_issue = "overwritten"
    else:
        log_issue = None

    # 镜像在用时，单独看 work_dir 那份坏没坏 —— 读数取自镜像，但 work_dir
    # 那份是 replay/writeup 的证据源，坏了要报（不是本次测量的错，是产物的错）。
    workdir_log_issue = None
    if log["log_source"] == "mirror" and log_issue is None:
        wd = parse_solver_log(work_dir, None)
        if not wd["log_present"]:
            workdir_log_issue = "missing"
        elif usage.get("api_calls") and not wd["api_call_lines"]:
            workdir_log_issue = "overwritten"

    return {
        "fixture": work_dir.name,
        "work_dir": str(work_dir),
        # C1 解出与正确性
        "flag": flag,
        "expected_flag": expected_flag,
        "flag_matches": (flag == expected_flag) if expected_flag else None,
        "solved": bool(flag),
        # C1b 路径经济性 —— 「解出率」在难题上会饱和，这个不会。
        # ref_multiple = api_calls / 参考解最少步骤：题解得出，但绕了几倍远路。
        # 参考解步数取自 manifest 的 solve_reference_steps；老 manifest 没有该
        # 键则为 None，指标整体退化为不可用而不是报错。
        "ref_steps": ref_steps,
        "ref_multiple": (round(api_calls / ref_steps, 2)
                         if (ref_steps and (api_calls := usage.get("api_calls")))
                         else None),
        # C2–C4 代价
        "attempts": usage.get("attempts"),
        "api_calls": usage.get("api_calls"),
        "api_calls_in_log": log["api_call_lines"],
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost_usd": usage.get("cost_usd"),
        # C5–C8 工具面
        "tool_calls": len(calls),
        "tool_calls_distinct": distinct,
        "tool_repeat_rate": round(repeats / len(calls), 4) if calls else 0.0,
        "tool_errors": log["tool_errors"],
        # C5b 日志可信性 —— 这个字段是踩坑换来的，见 print_aggregate 的报警。
        # solver.log 落在 work_dir 里，而 work_dir 是 agent 的地盘：它可以用
        # write_file 把它覆盖成一份解题报告。实测发生过（misc-chunkconcat-01，
        # 2026-09-11）：那一跑 4/4 解出、看起来一切正常，唯独该题的工具面
        # 全是 0 —— 工具 0、重复率 0%、延迟 None。**0 被当成"高效"读了过去。**
        # 运行日志必然含 "Making API call" 行；一条都没有却又有 api_calls，
        # 就说明这份 solver.log 不是运行日志。
        # 日志根本不存在同样不可用 —— 没有日志就没有工具面数据，不是"零工具"。
        "log_source": log["log_source"],
        "log_issue": log_issue,
        "log_is_runtime": log_issue is None,
        "workdir_log_issue": workdir_log_issue,
        "tool_mix": dict(sorted(name_counts.items(), key=lambda kv: -kv[1])),
        "discovery_calls": discovery,
        "discovery_share": round(discovery / len(calls), 4) if calls else 0.0,
        "shell_calls": shell,
        "read_calls": reads,
        # C9 API 节奏
        "api_latency_avg_s": round(sum(lats) / len(lats), 2) if lats else None,
        "api_latency_max_s": max(lats) if lats else None,
        "cache_hit_pct_avg": round(sum(h[2] for h in hits) / len(hits), 1) if hits else None,
        "cache_written_total": sum(log["cache_written"]) if log["cache_written"] else 0,
        "prompt_tokens_first": log["request_tokens"][0] if log["request_tokens"] else None,
        "prompt_tokens_last": log["request_tokens"][-1] if log["request_tokens"] else None,
    }


# ── manifest 交叉校验 ───────────────────────────────────────────────────

def load_expected(manifest: Path) -> dict[str, dict[str, Any]]:
    """极简 YAML 读取：抽 `- id:` / `expected_flag:` / `solve_reference_steps`。

    刻意不引 PyYAML —— 只为几个字段引入依赖不划算，且 manifest 由本项目生成，
    形态稳定（见 benchmarks/manifest-unit.yaml）。老 manifest（unit 那份）没有
    solve_reference_steps，取到 None 即可，不报错 —— 经济性指标随之退化，
    但解出率/flag 校验照常。
    """
    out: dict[str, dict[str, Any]] = {}
    cur: str | None = None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            cur = s.split(":", 1)[1].strip().strip('"\'')
            out.setdefault(cur, {})
        elif cur and s.startswith("expected_flag:"):
            out[cur]["expected_flag"] = s.split(":", 1)[1].strip().strip('"\'')
        elif cur and s.startswith("solve_reference_steps:"):
            out[cur]["steps"] = int(s.split(":", 1)[1].strip())
    return out


# ── 输出 ────────────────────────────────────────────────────────────────

def print_table(rows: list[dict[str, Any]]) -> None:
    hdr = ("fixture", "解出", "flag对", "尝试", "api", "×参考解", "总token", "工具", "重复率",
           "发现开销", "shell/read", "延迟均值", "缓存命中")
    print()
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for r in rows:
        ok = "✓" if r["flag_matches"] else ("—" if r["flag_matches"] is None else "✗")
        econ = f"{r['ref_multiple']}×" if r["ref_multiple"] is not None else "—"
        name = r["fixture"] if r["log_is_runtime"] else f"{r['fixture']} ⚠️"
        # 日志不可信时工具面四列**必须置为 —**。原先直接打 0/0%/None%，
        # 那是在报告里写下"这题一次工具都没调、零重复、零延迟"这种
        # 不存在的事实 —— 全 0 看起来像最优成绩，实际是数据没了。
        if r["log_is_runtime"]:
            tools, repeat = str(r["tool_calls"]), f"{r['tool_repeat_rate']*100:.0f}%"
            disc = f"{r['discovery_calls']} ({r['discovery_share']*100:.0f}%)"
            sr = f"{r['shell_calls']}/{r['read_calls']}"
            lat, cache = f"{r['api_latency_avg_s']}s", f"{r['cache_hit_pct_avg']}%"
        else:
            tools = repeat = disc = sr = lat = cache = "—"
        print(
            f"| {name} | {'✓' if r['solved'] else '✗'} | {ok} "
            f"| {r['attempts']} | {r['api_calls']} "
            f"| {econ} "
            f"| {(r['total_tokens'] or 0):,} | {tools} "
            f"| {repeat} | {disc} "
            f"| {sr} "
            f"| {lat} | {cache} |"
        )
    if any(r["log_source"] == "mirror" for r in rows):
        print("\n> 标注：读数取自**镜像日志**（solve 目录之外），"
              "work_dir 内那份可能被 agent 改过。")


def print_aggregate(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    n = len(rows)
    solved = sum(1 for r in rows if r["solved"])
    correct = sum(1 for r in rows if r["flag_matches"])
    graded = sum(1 for r in rows if r["flag_matches"] is not None)
    tot_tok = sum(r["total_tokens"] or 0 for r in rows)
    tot_api = sum(r["api_calls"] or 0 for r in rows)
    tot_tools = sum(r["tool_calls"] for r in rows)
    tot_disc = sum(r["discovery_calls"] for r in rows)

    print(f"\n### CTF 路径汇总（{n} 题）\n")
    print(f"- **解出率：** {solved}/{n}")
    if graded:
        print(f"- **flag 正确率：** {correct}/{graded}（与 manifest expected_flag 逐字比对）")
    print(f"- **总 token：** {tot_tok:,}（其中 prompt 侧 "
          f"{sum(r['input_tokens'] or 0 for r in rows):,}，补全侧 "
          f"{sum(r['output_tokens'] or 0 for r in rows):,}）")
    n_suspect = sum(1 for r in rows if not r["log_is_runtime"])
    # 缺失的工具面按 0 计入会让总数**偏低**却看不出偏低 —— 标明它是下界。
    bound = f"（**下界**：{n_suspect} 题的日志不可用，其工具面未计入）" if n_suspect else ""
    print(f"- **api_calls：** {tot_api}；**工具调用：** {tot_tools}{bound}")
    if tot_tools:
        print(f"- **工具发现开销（tool_describe+tool_search）：** {tot_disc} 次 "
              f"= {tot_disc/tot_tools*100:.1f}% 的工具往返")
    print(f"- **shell : read_file =** {sum(r['shell_calls'] for r in rows)} : "
          f"{sum(r['read_calls'] for r in rows)}（CTF 本该 shell 主导）")

    # 先在汇总里报警，再谈指标 —— 数据不可信时后面的数字一个都别信。
    suspect = [r for r in rows if not r["log_is_runtime"]]
    if suspect:
        why = {"overwritten": "solver.log 不是运行日志（0 条 `Making API call` 行却有 api_calls）",
               "missing": "工作目录里没有 solver.log"}
        detail = "；".join(f"{r['fixture']}（{why[r['log_issue']]}）" for r in suspect)
        print(f"- ⚠️ **日志不可信：** {detail}。")
        print("  > `solver.log` 落在 work_dir 里，而 work_dir 是 agent 的地盘 —— "
              "它可以用 `write_file` 把它覆盖成解题报告（实测发生过）。"
              "这些题的工具数/重复率/延迟/缓存**全部不可用**，"
              "尤其别把「工具 0」读成「高效」。跑批时给 `--mirror-dir` 可避免："
              "镜像由 solver 侧同时写到 solve 目录之外。")

    # 读数取自镜像、但 work_dir 那份坏了：本次测量有效，坏的是产物本身
    # （replay/writeup 的证据源）。分开报，别混进上面那条。
    broken = [r for r in rows if r.get("workdir_log_issue")]
    if broken:
        names = "；".join(f"{r['fixture']}（{r['workdir_log_issue']}）" for r in broken)
        print(f"- ⚠️ **work_dir 内的 solver.log 已被扰动：** {names}。"
              f"本次读数取自镜像，测量有效；但 replay/writeup 读的是 work_dir 那份。")

    # 路径经济性 —— 解出率在难题上会饱和（3/3 就没有下降空间了），
    # 这个指标不会：绕远路是连续的，任何一次减冗余都能在它上面看到位移。
    graded_econ = [r for r in rows if r["ref_multiple"] is not None]
    if graded_econ:
        ref_sum = sum(r["ref_steps"] for r in graded_econ)
        api_sum = sum(r["api_calls"] for r in graded_econ)
        worst = max(graded_econ, key=lambda r: r["ref_multiple"])
        print(f"- **路径经济性：** api_calls {api_sum} / 参考解最少步数 {ref_sum} "
              f"= **{api_sum / ref_sum:.1f}×**（越接近 1 越经济；"
              f"最不经济：{worst['fixture']} {worst['ref_multiple']}×）")
        print("  > 解出率饱和时以本项为主指标：题解得出但绕远路，"
              "正是 P0.1/减冗余类改动的靶子。")
    else:
        print("- **路径经济性：** 不可用（manifest 无 solve_reference_steps）")


# ── 重复采样聚合（2c：经济性要能验收，先得有噪声地板） ──────────────────

# 跑批输出目录里除题目之外的东西，别当成 fixture 采
NON_FIXTURE_DIRS = frozenset({"logs", "_selfproof", "_mirror"})


def discover_batch(batch_dir: Path) -> list[Path]:
    """列出跑批目录下的题目 work_dir（跳过 logs/_selfproof/_mirror 与隐藏项）。"""
    return sorted(
        d for d in batch_dir.iterdir()
        if d.is_dir() and d.name not in NON_FIXTURE_DIRS and not d.name.startswith(".")
    )


def repeat_stats(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """把同一 fixture 的多次采样压成一行统计。

    报**范围**而不只是均值：n 小的时候标准差没有意义，但"同一份代码跑出
    12–26 次 api"这个事实本身就能说明该指标的分辨率上限。
    """
    out = []
    for name, samples in sorted(groups.items()):
        apis = [s["api_calls"] for s in samples if s["api_calls"] is not None]
        mults = [s["ref_multiple"] for s in samples if s["ref_multiple"] is not None]
        toks = [s["total_tokens"] for s in samples if s["total_tokens"]]
        out.append({
            "fixture": name,
            "n": len(samples),
            "solved": sum(1 for s in samples if s["solved"]),
            "flag_ok": sum(1 for s in samples if s["flag_matches"]),
            "graded": sum(1 for s in samples if s["flag_matches"] is not None),
            "log_untrusted": sum(1 for s in samples if not s["log_is_runtime"]),
            "api_mean": round(sum(apis) / len(apis), 1) if apis else None,
            "api_min": min(apis) if apis else None,
            "api_max": max(apis) if apis else None,
            "mult_mean": round(sum(mults) / len(mults), 2) if mults else None,
            "mult_min": min(mults) if mults else None,
            "mult_max": max(mults) if mults else None,
            "token_mean": round(sum(toks) / len(toks)) if toks else None,
            "ref_steps": samples[0]["ref_steps"],
        })
    return out


def print_repeat_table(stats: list[dict[str, Any]]) -> None:
    hdr = ("fixture", "n", "解出", "flag对", "api 均值", "api 范围",
           "×参考解 均值", "×参考解 范围", "token 均值")
    print()
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for s in stats:
        api_rng = (f"{s['api_min']}–{s['api_max']}"
                   if s["api_min"] is not None else "—")
        mult_rng = (f"{s['mult_min']}–{s['mult_max']}"
                    if s["mult_min"] is not None else "—")
        flag = f"{s['flag_ok']}/{s['graded']}" if s["graded"] else "—"
        print(
            f"| {s['fixture']} | {s['n']} | {s['solved']}/{s['n']} | {flag} "
            f"| {s['api_mean'] if s['api_mean'] is not None else '—'} | {api_rng} "
            f"| {s['mult_mean'] if s['mult_mean'] is not None else '—'}× | {mult_rng} "
            f"| {(s['token_mean'] or 0):,} |"
        )


def print_repeat_summary(stats: list[dict[str, Any]]) -> None:
    """给出**噪声地板** —— 2c 的全部意义就在这里。

    没有它，任何一次改动的前后差异都无法与采样噪声区分（v1 3.7× / v2 2.9×
    的位移就是纯噪声）。所以这里不只报数，还要把"小于多少算没变"说出来。
    """
    if not stats:
        return
    ns = sorted({s["n"] for s in stats})
    n_rng = f"{ns[0]}" if len(ns) == 1 else f"{ns[0]}–{ns[-1]}"
    print(f"\n### 重复采样汇总（{len(stats)} 题 × {n_rng} 次）\n")

    tot_solved = sum(s["solved"] for s in stats)
    tot_n = sum(s["n"] for s in stats)
    print(f"- **解出率：** {tot_solved}/{tot_n}")
    untrusted = sum(s["log_untrusted"] for s in stats)
    if untrusted:
        print(f"- ⚠️ **其中 {untrusted} 次采样的日志不可信** —— 工具面数字已剔除，"
              f"见单批报告。解出率与 api_calls 不受影响。")

    mults = [s for s in stats if s["mult_mean"] is not None]
    if not mults:
        print("- **路径经济性：** 不可用（manifest 无 solve_reference_steps）")
        return

    ref_sum = sum(s["ref_steps"] * s["n"] for s in mults)
    api_sum = sum(s["api_mean"] * s["n"] for s in mults)
    print(f"- **路径经济性（合并）：** api_calls {api_sum:,.0f} / 参考解最少步数 "
          f"{ref_sum} = **{api_sum / ref_sum:.1f}×**")

    # 噪声地板只从「采了 ≥2 次」的题里取 —— 单次采样没有跨度可言，
    # 让它们把整块判据顶掉，等于用「有一题没重复跑」取消全部结论。
    dup, single = [], []
    for s in mults:
        (single if s["n"] < 2 else dup).append(s)
    if not dup:
        print(f"- ⚠️ **{len(single)} 题全是单次采样，算不出方差** —— "
              f"单点差异不得当证据。")
        return
    if single:
        print(f"- ℹ️ **{len(single)} 题只采了 1 次，不参与噪声地板**"
              f"（{', '.join(s['fixture'] for s in single)}）—— "
              f"单点数字当基线可以，当判据不行。")

    # 噪声地板：取各题 ×参考解 跨度的最大值。比它小的前后差异一律不可归因。
    spans = [(s["fixture"], s["mult_max"] - s["mult_min"]) for s in dup]
    worst = max(spans, key=lambda kv: kv[1])
    floor = worst[1]
    print(f"- **噪声地板（同一份代码的自身摆动）：** 最大跨度 {floor:.2f}× "
          f"（{worst[0]}）")
    for name, span in sorted(spans, key=lambda kv: -kv[1]):
        print(f"  - {name}: {span:.2f}× 跨度")
    print(f"  > **验收判据：** 改动前后的 ×参考解 差异若小于 **{floor:.2f}×**，"
          f"本批采样分辨不了，不能归因于改动。"
          f"要压过它，要么改动足够大，要么加大 n。")
    if floor == 0:
        print("  > 本次各题跨度全为 0（样本高度一致）—— 地板取 0 意味着"
              "任何非零差异都显著；但 n 小时这也可能是巧合，n≥3 前别据此下结论。")


def run_repeat_mode(batch_dirs: list[Path], meta: dict[str, dict[str, Any]],
                    json_path: Path | None) -> int:
    groups: dict[str, list[dict[str, Any]]] = {}
    unknown: dict[str, list[str]] = {}
    for batch in batch_dirs:
        if not batch.is_dir():
            print(f"⚠️  跳过（不是目录）：{batch}", file=sys.stderr)
            continue
        mirror = batch / "_mirror"
        for d in discover_batch(batch):
            # 有 manifest 就按 manifest 认题：跑批目录**不是** agent 够不着的地方，
            # 实测 agent 会把中间产物写到 work_dir 的上一级（misc-chunkconcat-01
            # 那题的 $OUT/out/chan*.bin）。按目录名猜"这是不是一道题"会把它算成
            # 一道 fixture，虚增题数、还把解出率拉低 —— 缺数据变成了假数据。
            if meta and d.name not in meta:
                unknown.setdefault(d.name, []).append(batch.name)
                continue
            m = meta.get(d.name, {})
            row = analyze(d, m.get("expected_flag"), m.get("steps"),
                          mirror if mirror.is_dir() else None)
            row["batch"] = batch.name
            groups.setdefault(d.name, []).append(row)

    if unknown:
        print(f"\n⚠️ **跑批目录里有 {len(unknown)} 项不在 manifest 里，已排除** —— "
              f"多半是 agent 写在 work_dir 上一级的中间产物，不是题目：")
        for name, batches in sorted(unknown.items()):
            print(f"  - `{name}/`（出现在 {', '.join(sorted(set(batches)))}）")
        print("  > 与「agent 用 write_file 覆盖 solver.log」同源：**跑批目录也在"
              "agent 的可写范围内**。排除是对的，但别把它读成「这题没跑」。")
    elif not meta:
        print("\n⚠️ 未给 `--manifest`，无法把「题目」与「agent 写进来的杂物」区分开 —— "
              "目录里出现的每一项都会被当成一道题。做对照跑时请务必给 manifest。")

    if not groups:
        sys.exit("❌ 没有任何可分析的 work_dir")

    stats = repeat_stats(groups)
    print_repeat_table(stats)
    print_repeat_summary(stats)

    # 每次单独摊开，便于定位是哪一批异常（均值会把它抹平）
    print("\n<details><summary>逐次采样</summary>\n")
    for name, samples in sorted(groups.items()):
        cells = ", ".join(
            f"{s['batch']}: {s['api_calls']} api / {s['ref_multiple']}×"
            + ("" if s["log_is_runtime"] else "（日志不可信）")
            for s in samples
        )
        print(f"- **{name}** — {cells}")
    print("\n</details>")

    if json_path:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema": "ctf-path-baseline/2-repeat",
            "batches": [str(b) for b in batch_dirs],
            "fixture_count": len(stats),
            "stats": stats,
            "samples": groups,
            # 落档：跑批目录里被排除的非 fixture 项 —— 它们是"agent 写了东西到
            # work_dir 之外"的证据，留着可以判断这类污染有没有变多。
            "excluded_non_fixture": unknown,
        }
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n✅ 已写入 {json_path}")
    return 0


def _span_of(stat: dict[str, Any]) -> float | None:
    """一题自身 ×参考解 的跨度；只采过 1 次就没有跨度可言。"""
    if stat.get("n", 0) < 2:
        return None
    lo, hi = stat.get("mult_min"), stat.get("mult_max")
    if lo is None or hi is None:
        return None
    return hi - lo


def load_repeat_archive(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema")
    if schema != "ctf-path-baseline/2-repeat":
        raise ValueError(f"{path} 不是 2-repeat 归档（schema={schema!r}）")
    return payload


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _chronology_warning(base: dict[str, Any], changed: dict[str, Any]) -> str | None:
    """「改动后」比「改动前」还早 —— 大概率是两个参数传反了。

    这个校验现在做得了，是因为归档开始记 ``generated_at`` 了。踩过一次：
    清理提交与对照跑交错的窗口里，很容易顺手把新采的那份放在第一个位置，
    于是 ``改动后`` 实际是**更旧**的代码，Δ 的符号整个反过来 —— 而报告上
    看不出任何异常，两个数字照样印得整整齐齐。

    只报"可疑"，不断言传反了：倒着比（新 → 旧）本身是合法的，Δ 就按
    ``后 − 前`` 的字面意思读。
    """
    tb, tc = _parse_ts(base.get("generated_at")), _parse_ts(changed.get("generated_at"))
    if tb is None or tc is None or tc >= tb:
        return None
    return (f"「改动后」那份采集于 {changed['generated_at']}，**早于**「改动前」的 "
            f"{base['generated_at']} —— 两个参数是不是传反了？Δ 的符号按"
            f"「后 − 前」的字面定义读，若确实是有意倒着比，忽略本警告。")


def _archive_provenance(archive: dict[str, Any]) -> dict[str, Any]:
    """归档自述：这份数据是**哪些跑批、什么时候**采的。

    为什么要落这个：判断"这次对照说明什么"需要用到一个归档本身记不下的
    事实 —— **两侧之间代码差了什么**。实测踩过：一份 09-12 的对照跑与
    一份 09-11 的基线比出 +0.40×，而这两次采集之间还夹着六个提交；不手工
    `git diff` 一遍就没法知道这 0.40× 该记给谁。归档能固定的只有跑批来源，
    剩下那半必须由写结论的人核对后**明写**，否则同一个 Δ 可以被读成任何
    一次提交的效果。
    """
    return {
        "generated_at": archive.get("generated_at"),
        "batches": list(archive.get("batches") or []),
        "fixture_count": archive.get("fixture_count"),
    }


def _batch_aggregates(archive: dict[str, Any], names: set[str], side: str
                      ) -> tuple[dict[str, float], list[str]]:
    """每个跑批各自的合并 ×参考解；只算**跑齐了全部对照题**的批。

    这是合并指标噪声地板的来源：同一份代码、同题集，逐批之间的摆动就是
    该指标的分辨率上限。缺题的批（新题只在前一批出现过之类）不参与，
    但要**点名报出来** —— 静默少一批等于偷偷缩小样本。

    ``side`` 只用于给跳过的批加前缀：两侧的跑批常同名（各自根目录下的
    ``run1``/``run2``…），不带前缀的话"哪一侧少了批"读不出来。
    """
    by_batch: dict[str, dict[str, dict[str, Any]]] = {}
    for fx, samples in archive.get("samples", {}).items():
        if fx not in names:
            continue
        for s in samples:
            by_batch.setdefault(s.get("batch"), {})[fx] = s

    out: dict[str, float] = {}
    skipped: list[str] = []
    for batch, got in sorted(by_batch.items(), key=lambda kv: str(kv[0])):
        if set(got) != names or any(
                got[f].get("api_calls") is None or not got[f].get("ref_steps")
                for f in names):
            skipped.append(f"{side}/{batch}")
            continue
        api = sum(got[f]["api_calls"] for f in names)
        ref = sum(got[f]["ref_steps"] for f in names)
        out[str(batch)] = api / ref
    return out, skipped


def compare_archives(base: dict[str, Any], changed: dict[str, Any]) -> dict[str, Any]:
    """两组 ``--runs`` 归档的对照，判据是**噪声地板**。

    为什么不把两组批目录塞进一次 ``--runs``：那样算出来的"地板"会把两组
    之间的真实差异一起算进去，等于用被测量的东西当尺子 —— 差异越大，
    尺子越长，永远测不出显著。**两侧各自的内部摆动必须是分开估的。**

    地板取两侧跨度的较大者：两侧都是同一套 harness 的噪声实现，合并起来
    是同一个量的更多样本，取大偏保守（改动压低方差时不会因此误判显著）。
    """
    b_by = {s["fixture"]: s for s in base.get("stats", [])}
    c_by = {s["fixture"]: s for s in changed.get("stats", [])}

    rows, only_base, only_changed, steps_mismatch = [], [], [], []
    for name in sorted(set(b_by) | set(c_by)):
        b, c = b_by.get(name), c_by.get(name)
        if b is None:
            only_changed.append(name)
            continue
        if c is None:
            only_base.append(name)
            continue
        if b.get("ref_steps") != c.get("ref_steps"):
            # 参考步数变了 = 题目本身变了，两侧跑的不是同一道题，差值无意义
            steps_mismatch.append((name, b.get("ref_steps"), c.get("ref_steps")))
            continue

        spans = [s for s in (_span_of(b), _span_of(c)) if s is not None]
        floor = max(spans) if spans else None
        dm = (None if b["mult_mean"] is None or c["mult_mean"] is None
              else round(c["mult_mean"] - b["mult_mean"], 2))
        rows.append({
            "fixture": name,
            "ref_steps": b.get("ref_steps"),
            "n_base": b["n"], "n_changed": c["n"],
            "mult_base": b["mult_mean"], "mult_changed": c["mult_mean"],
            "mult_delta": dm,
            "floor": None if floor is None else round(floor, 2),
            # 只有两侧都采到 ≥2 次，跨度才存在，差异才谈得上能不能归因
            "resolvable": (None if floor is None or dm is None
                           else abs(dm) > floor),
            "api_mean_base": b["api_mean"], "api_mean_changed": c["api_mean"],
            "api_delta": (None if b["api_mean"] is None or c["api_mean"] is None
                          else round(c["api_mean"] - b["api_mean"], 1)),
            "token_mean_base": b["token_mean"], "token_mean_changed": c["token_mean"],
            "solved_base": f"{b['solved']}/{b['n']}",
            "solved_changed": f"{c['solved']}/{c['n']}",
        })

    # 合并经济性。只统计**可对照**的题（steps 一致、两侧都有），否则分子
    # 分母和逐题行对不上。
    def _pooled(by: dict[str, dict[str, Any]], names: set[str]) -> tuple[float, float]:
        a = sum(by[n]["api_mean"] * by[n]["n"]
                for n in names if by[n]["api_mean"])
        r = sum(by[n]["ref_steps"] * by[n]["n"]
                for n in names if by[n].get("ref_steps"))
        return a, r

    names = {r["fixture"] for r in rows}
    api_b, ref_b = _pooled(b_by, names)
    api_c, ref_c = _pooled(c_by, names)
    mul_b = api_b / ref_b if ref_b else None
    mul_c = api_c / ref_c if ref_c else None

    # 合并指标的噪声地板**直接按跑批量**：把每个跑批各自的合并 ×参考解 算出来，
    # 取同侧逐批摆动的最大跨度。这样地板与被判的量是同一个统计量，不靠
    # 「只有一题在摆」之类的假设。代价是需要每侧 ≥2 个跑批。
    batches_b, skip_b = _batch_aggregates(base, names, "改动前")
    batches_c, skip_c = _batch_aggregates(changed, names, "改动后")
    spans = [max(v.values()) - min(v.values())
             for v in (batches_b, batches_c) if len(v) >= 2]
    agg_floor = max(spans) if spans else None

    agg_delta = None if mul_b is None or mul_c is None else round(mul_c - mul_b, 2)
    return {
        "sources": {"base": _archive_provenance(base),
                    "changed": _archive_provenance(changed)},
        "chronology_warning": _chronology_warning(base, changed),
        "rows": rows,
        "only_base": only_base,
        "only_changed": only_changed,
        "steps_mismatch": steps_mismatch,
        "incomplete_batches": skip_b + skip_c,
        "pooled": {
            "api_base": round(api_b), "api_changed": round(api_c),
            "ref_steps": ref_b if ref_b == ref_c else None,
            "mult_base": None if mul_b is None else round(mul_b, 2),
            "mult_changed": None if mul_c is None else round(mul_c, 2),
            "mult_delta": agg_delta,
            "floor": None if agg_floor is None else round(agg_floor, 2),
            "resolvable": (None if agg_floor is None or agg_delta is None
                           else abs(agg_delta) > agg_floor),
            "batches_base": None if not batches_b else
                {k: round(v, 2) for k, v in sorted(batches_b.items())},
            "batches_changed": None if not batches_c else
                {k: round(v, 2) for k, v in sorted(batches_c.items())},
        },
    }


def print_comparison(cmp: dict[str, Any]) -> None:
    rows = cmp["rows"]
    print("\n### 对照（改动前 → 改动后）\n")

    src = cmp.get("sources") or {}
    if src:
        print("采集来源 —— **归档记不下「两侧之间代码差了什么」**，那半个前提"
              "必须自己核对后写进结论，否则下面这个 Δ 可以被读成任何一次提交的效果：")
        for key, label in (("base", "改动前"), ("changed", "改动后")):
            s = src.get(key) or {}
            batches = "、".join(s.get("batches") or []) or "未记录"
            print(f"  - {label}: {s.get('generated_at') or '时间未记录'}（{batches}）")
        if cmp.get("chronology_warning"):
            print(f"  ⚠️ {cmp['chronology_warning']}")
        print()

    if cmp["steps_mismatch"]:
        print("⚠️ **以下题目的参考步数在两组间不一致，已排除在对照之外** ——"
              "参考步数变了说明题目本身变了，两侧跑的不是同一道题：")
        for name, rb, rc in cmp["steps_mismatch"]:
            print(f"  - {name}: {rb} → {rc}")
        print()
    if cmp["only_base"]:
        print(f"ℹ️ **只在改动前那组出现过、无法对照：** {', '.join(cmp['only_base'])}"
              f" —— 单侧数据不构成对照，不许拿它下结论。")
    if cmp["only_changed"]:
        print(f"ℹ️ **只在改动后那组出现过、无法对照：** "
              f"{', '.join(cmp['only_changed'])}")

    if not rows:
        print("\n❌ **没有任何一题是可对照的** —— 两组之间没有共同题目。")
        return

    hdr = ("fixture", "n 前/后", "×参考解 前", "×参考解 后", "Δ", "地板",
           "判据", "api Δ", "token 前→后", "解出 前/后")
    print("\n| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for r in rows:
        verdict = {True: "✅ 可归因", False: "❌ 分辨不了", None: "— 采样不足"}[r["resolvable"]]
        floor = "—" if r["floor"] is None else f"{r['floor']:.2f}×"
        delta = "—" if r["mult_delta"] is None else f"{r['mult_delta']:+.2f}×"
        apid = "—" if r["api_delta"] is None else f"{r['api_delta']:+.1f}"
        tk = (f"{r['token_mean_base']:,}→{r['token_mean_changed']:,}"
              if r["token_mean_base"] and r["token_mean_changed"] else "—")
        print(f"| {r['fixture']} | {r['n_base']}/{r['n_changed']} "
              f"| {r['mult_base'] if r['mult_base'] is not None else '—'}× "
              f"| {r['mult_changed'] if r['mult_changed'] is not None else '—'}× "
              f"| {delta} | {floor} | {verdict} | {apid} | {tk} "
              f"| {r['solved_base']} → {r['solved_changed']} |")

    p = cmp["pooled"]
    print(f"\n- **合并经济性：** {p['mult_base']}× → {p['mult_changed']}× "
          f"（{p['api_base']:,} → {p['api_changed']:,} api / {p['ref_steps']} 参考步数）")
    if p["mult_delta"] is None or p["floor"] is None:
        print("  > ⚠️ 合并判据不可用（每侧至少要 2 个跑批才估得出逐批摆动，"
              "参考步数也要一致）—— 只看逐题行，别用合并数字下结论。")
    else:
        mark = "✅ 可归因" if p["resolvable"] else "❌ 分辨不了"
        print(f"  > Δ {p['mult_delta']:+.2f}× vs 逐批地板 {p['floor']:.2f}× → **{mark}**")
        if p["batches_base"]:
            print(f"  > 改动前逐批：{p['batches_base']}")
        if p["batches_changed"]:
            print(f"  > 改动后逐批：{p['batches_changed']}")
        print("  > 地板是被判统计量自身的逐批摆动（同一份代码跑两遍的差），"
              "不是推导出来的近似。**合并指标比逐题指标灵敏得多** —— "
              "逐题地板 0.75–1.40× 量级，合并后常常只有 0.1× 量级，"
              "因为各题噪声互相抵消。")
    if cmp.get("incomplete_batches"):
        print(f"  > ℹ️ 有 {len(cmp['incomplete_batches'])} 个跑批没跑齐对照题集，"
              f"未参与地板估计：{', '.join(cmp['incomplete_batches'])}")

    resolved = [r for r in rows if r["resolvable"]]
    n_ok, n_no, n_na = (len(resolved),
                        sum(1 for r in rows if r["resolvable"] is False),
                        sum(1 for r in rows if r["resolvable"] is None))
    print(f"\n- **可归因 {n_ok} 题 / 分辨不了 {n_no} 题 / 采样不足 {n_na} 题**")
    if n_ok == 0 and n_no == 0:
        print("  > 一题都没采够 —— 这份对照**什么都没证明**，不是「无效果」。")
    elif n_ok == 0:
        print("  > 全部差异都在地板以内：**这批采样分辨不了这个改动**。"
              "这不等于改动无效，只等于当前 n 看不见它。")


def run_compare_mode(base_path: Path, changed_path: Path,
                     json_path: Path | None) -> int:
    try:
        base = load_repeat_archive(base_path)
        changed = load_repeat_archive(changed_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        sys.exit(f"❌ 读不了对照归档：{e}")

    print(f"改动前：{base_path}\n改动后：{changed_path}")
    cmp = compare_archives(base, changed)
    print_comparison(cmp)

    if json_path:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema": "ctf-path-baseline/2-compare",
            "base_archive": str(base_path),
            "changed_archive": str(changed_path),
            "comparison": cmp,
        }
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n✅ 已写入 {json_path}")
    return 0


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="CTF 路径基线采集器（读 work_dir 的 usage.json + solver.log）",
    )
    ap.add_argument("--dirs", nargs="+", type=Path,
                    help="题目 work_dir 列表")
    ap.add_argument("--runs", nargs="+", type=Path,
                    help="重复采样模式：跑批目录列表（每个下面一层是各题 work_dir）。"
                         "按 fixture 聚合 n/解出率/api 范围/×参考解范围，并给出"
                         "**噪声地板** —— 没有它，单次跑的前后差异无法与采样噪声区分")
    ap.add_argument("--mirror-dir", type=Path,
                    help="镜像运行日志目录（solve 侧 FULILIAN_SOLVER_LOG_MIRROR 的"
                         "落点）。给了它且存在 <fixture>.solver.log 时优先采信镜像，"
                         "work_dir 里被 agent 覆盖过的那份不再影响读数")
    ap.add_argument("--manifest", type=Path,
                    help="benchmark manifest，用于期望 flag 交叉校验")
    ap.add_argument("--compare", nargs=2, type=Path,
                    metavar=("改动前", "改动后"),
                    help="对照模式：两份 --runs 归档（schema 2-repeat）。"
                         "逐题给 Δ 与其自身噪声地板，判据是 |Δ| > 地板 —— "
                         "低于地板的差异这批采样分辨不了，不许归因于改动")
    ap.add_argument("--json", type=Path, help="结果写成 JSON（基线归档）")
    args = ap.parse_args(argv)

    modes = [bool(args.dirs), bool(args.runs), bool(args.compare)]
    if sum(modes) != 1:
        ap.error("--dirs / --runs / --compare 三选一：单批看明细，"
                 "多批看分布，两份归档做对照")

    if args.compare:
        return run_compare_mode(args.compare[0], args.compare[1], args.json)

    meta = load_expected(args.manifest) if args.manifest else {}

    if args.runs:
        return run_repeat_mode(args.runs, meta, args.json)

    rows = []
    for d in args.dirs:
        if not d.is_dir():
            print(f"⚠️  跳过（不是目录）：{d}", file=sys.stderr)
            continue
        m = meta.get(d.name, {})
        rows.append(analyze(d, m.get("expected_flag"), m.get("steps"),
                            args.mirror_dir))

    if not rows:
        sys.exit("❌ 没有任何可分析的 work_dir")

    missing = [r["fixture"] for r in rows if r["api_calls"] is None]
    if missing:
        print(f"⚠️  {', '.join(missing)} 缺 usage.json —— 该次 solve 可能没走 CTF 路径",
              file=sys.stderr)

    print_table(rows)
    print_aggregate(rows)

    if args.json:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema": "ctf-path-baseline/1",
            "fixture_count": len(rows),
            "fixtures": rows,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n✅ 已写入 {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
