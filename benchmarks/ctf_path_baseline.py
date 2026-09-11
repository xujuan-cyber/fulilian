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
  * ``solver.log`` 每跑一次被 ``"w"`` 覆盖，基线必须当次跑完立刻采集。

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


def parse_solver_log(work_dir: Path) -> dict[str, Any]:
    """从 solver.log 拆出 API 节奏、缓存命中、工具调用序列。"""
    p = work_dir / SOLVER_LOG
    out: dict[str, Any] = {
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

def analyze(work_dir: Path, expected_flag: str | None = None) -> dict[str, Any]:
    usage = parse_usage(work_dir)
    log = parse_solver_log(work_dir)

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

    return {
        "fixture": work_dir.name,
        "work_dir": str(work_dir),
        # C1 解出与正确性
        "flag": flag,
        "expected_flag": expected_flag,
        "flag_matches": (flag == expected_flag) if expected_flag else None,
        "solved": bool(flag),
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

def load_expected(manifest: Path) -> dict[str, str]:
    """极简 YAML 读取：只抽 `- id:` / `expected_flag:` 两个键。

    刻意不引 PyYAML —— 只为两个字段引入依赖不划算，且 manifest 由本项目生成，
    形态稳定（见 benchmarks/manifest-unit.yaml）。
    """
    out: dict[str, str] = {}
    cur: str | None = None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            cur = s.split(":", 1)[1].strip().strip('"\'')
        elif cur and s.startswith("expected_flag:"):
            out[cur] = s.split(":", 1)[1].strip().strip('"\'')
            cur = None
    return out


# ── 输出 ────────────────────────────────────────────────────────────────

def print_table(rows: list[dict[str, Any]]) -> None:
    hdr = ("fixture", "解出", "flag对", "尝试", "api", "总token", "工具", "重复率",
           "发现开销", "shell/read", "延迟均值", "缓存命中")
    print()
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for r in rows:
        ok = "✓" if r["flag_matches"] else ("—" if r["flag_matches"] is None else "✗")
        print(
            f"| {r['fixture']} | {'✓' if r['solved'] else '✗'} | {ok} "
            f"| {r['attempts']} | {r['api_calls']} "
            f"| {(r['total_tokens'] or 0):,} | {r['tool_calls']} "
            f"| {r['tool_repeat_rate']*100:.0f}% | {r['discovery_calls']} "
            f"({r['discovery_share']*100:.0f}%) "
            f"| {r['shell_calls']}/{r['read_calls']} "
            f"| {r['api_latency_avg_s']}s | {r['cache_hit_pct_avg']}% |"
        )


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
    print(f"- **api_calls：** {tot_api}；**工具调用：** {tot_tools}")
    if tot_tools:
        print(f"- **工具发现开销（tool_describe+tool_search）：** {tot_disc} 次 "
              f"= {tot_disc/tot_tools*100:.1f}% 的工具往返")
    print(f"- **shell : read_file =** {sum(r['shell_calls'] for r in rows)} : "
          f"{sum(r['read_calls'] for r in rows)}（CTF 本该 shell 主导）")


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="CTF 路径基线采集器（读 work_dir 的 usage.json + solver.log）",
    )
    ap.add_argument("--dirs", nargs="+", type=Path, required=True,
                    help="题目 work_dir 列表")
    ap.add_argument("--manifest", type=Path,
                    help="benchmark manifest，用于期望 flag 交叉校验")
    ap.add_argument("--json", type=Path, help="结果写成 JSON（基线归档）")
    args = ap.parse_args(argv)

    expected = load_expected(args.manifest) if args.manifest else {}

    rows = []
    for d in args.dirs:
        if not d.is_dir():
            print(f"⚠️  跳过（不是目录）：{d}", file=sys.stderr)
            continue
        rows.append(analyze(d, expected.get(d.name)))

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
