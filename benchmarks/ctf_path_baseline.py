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
    for batch in batch_dirs:
        if not batch.is_dir():
            print(f"⚠️  跳过（不是目录）：{batch}", file=sys.stderr)
            continue
        mirror = batch / "_mirror"
        for d in discover_batch(batch):
            m = meta.get(d.name, {})
            row = analyze(d, m.get("expected_flag"), m.get("steps"),
                          mirror if mirror.is_dir() else None)
            row["batch"] = batch.name
            groups.setdefault(d.name, []).append(row)

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
    ap.add_argument("--json", type=Path, help="结果写成 JSON（基线归档）")
    args = ap.parse_args(argv)

    if not args.dirs and not args.runs:
        ap.error("至少要给 --dirs 或 --runs")
    if args.dirs and args.runs:
        ap.error("--dirs 与 --runs 互斥：单批看明细，多批看分布")

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
