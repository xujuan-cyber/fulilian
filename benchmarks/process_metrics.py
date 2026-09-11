#!/usr/bin/env python3
"""CTF 解题的过程指标采集器（只读 state.db，不碰 solver 一行代码）。

背景：现有 `fulilian_ctf/benchmark.py --suite unit` 把 solver mock 成参考解，
`flag 提取/三门/落盘` 是真实代码但**模型推理不是**——它能锁住链路不退化，
锁不住"agent 变笨了"。`--suite smoke` 是真 API，但 manifest 是待填骨架且
runner 一律拒绝运行。于是**没有任何工具能测出改动让 agent 变好还是变坏**。

本脚本补这一格：把「过程指标」从 `state.db` 里读出来，用于改动前后对照。

指标定义见 docs/ctf-agent-optimization-plan.md §1：
  M1  重复工具调用占比      同一会话内 1 - 不同命令数 / 命令总数
  M2  平均工具调用数 / 回合  衡量串行往返
  M3  被压缩消息占比        压缩 = 失忆的直接来源
  M4  CTF 工具调用次数       verify_flag/record_fact/submit_flag/... 实测为 0
  M5  首次 flag 出现前的工具调用数（到 flag 的代价，代理指标）
  M6  会话级 token / cache_read / api_calls

仅依赖标准库。只读打开（mode=ro&immutable=1），绝不写库。

已知局限（2026-09-11 实测确认）：
  * `sessions.cache_write_tokens` 在全部 112 个会话、所有模型上均为 0 ——
    该字段未被记录。因此"压缩强制一次缓存全价重写"这一机制推断（优化
    计划书 §3.H）**无法从 state.db 验证**，只能由代码逻辑支撑，不要在
    本工具的输出上宣称已证实。
  * M5 是代理指标，见 analyze_session 内注释。
  * 本工具只测**过程**（重复率/往返/压缩/工具面/token）。解题能力
    （flag 率）必须靠 holdout 真题，过程指标好不等于题做得出来。

用法：
    # 先看有哪些会话可挑
    python3 benchmarks/process_metrics.py --list

    # 单会话
    python3 benchmarks/process_metrics.py --session <session_id>

    # 最近 N 个 cli 会话
    python3 benchmarks/process_metrics.py --recent 5

    # 某日期之后
    python3 benchmarks/process_metrics.py --since 2026-09-01

    # 落基线（约定路径 benchmarks/baselines/YYYY-MM-DD-<tag>.json）
    python3 benchmarks/process_metrics.py --recent 10 --json benchmarks/baselines/2026-09-11-ctf-agent.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ── 常量 ────────────────────────────────────────────────────────────────

DEFAULT_DB = Path.home() / ".fulilian" / "state.db"

# M4：CTF 层宣称的核心工具（tools/ctf_solve.py）。实测在所有会话中调用 0 次。
CTF_TOOLS = (
    "verify_flag", "submit_flag", "record_fact", "http_session",
    "git_auto_commit", "compile_check", "checkpoint", "generate_writeup",
)

# 用于 M5 的 flag 形状匹配。多平台前缀，与 benchmarks/manifest-unit.yaml 的
# expected_flag 前缀覆盖保持一致。
FLAG_RE = re.compile(
    r"\b(?:flag|ctfshow|nssctf|dasctf|iscc|buuctf|hgame|moectf|n1ctf|sctf|"
    r"de1ctf|starctf|hitcon|zer0pts|inctf|asis|defcon|picoctf|uiuctf)"
    r"\{[^}\n]{1,200}\}",
    re.IGNORECASE,
)

# 常驻型工具：每次都出现，不参与"重复"判定（它们的重复是设计使然）。
NON_REPEAT_TOOLS = frozenset()

RO_URI = f"file:{DEFAULT_DB}?mode=ro&immutable=1"


# ── 数据库 ──────────────────────────────────────────────────────────────

def connect(db: Path = DEFAULT_DB, timeout: float = 300.0) -> sqlite3.Connection:
    """只读打开 state.db。

    必须带 mode=ro&immutable=1：WAL 争用下普通只读连接会长时间阻塞
    （实测 120s 超时返回 0 行），immutable 让 SQLite 跳过锁协商。
    """
    if not db.is_file():
        sys.exit(f"❌ 找不到 state.db: {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, timeout=timeout)
    con.row_factory = sqlite3.Row
    return con


def list_sessions(con: sqlite3.Connection, limit: int = 30) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT id, source, model, title, display_name, started_at,
               message_count, tool_call_count, api_call_count,
               input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
        FROM sessions
        WHERE archived = 0 AND message_count > 0
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def resolve_sessions(
    con: sqlite3.Connection,
    session_ids: Iterable[str] | None = None,
    recent: int | None = None,
    since: str | None = None,
    source: str | None = None,
) -> list[sqlite3.Row]:
    """按优先级解析目标会话集合。"""
    if session_ids:
        marks = ",".join("?" * len(session_ids))
        return con.execute(
            f"SELECT * FROM sessions WHERE id IN ({marks})", tuple(session_ids)
        ).fetchall()

    where, params = ["archived = 0", "message_count > 0"], []
    if source:
        where.append("source = ?")
        params.append(source)
    if since:
        try:
            ts = datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            sys.exit(f"❌ --since 需要 ISO 日期（如 2026-09-01），收到: {since}")
        where.append("started_at >= ?")
        params.append(ts)

    sql = f"SELECT * FROM sessions WHERE {' AND '.join(where)} ORDER BY started_at DESC"
    if recent:
        sql += " LIMIT ?"
        params.append(recent)
    return con.execute(sql, tuple(params)).fetchall()


# ── 解析工具调用 ────────────────────────────────────────────────────────

def iter_calls(raw: str | None) -> list[tuple[str, dict[str, Any]]]:
    """把 messages.tool_calls 的 JSON 解析成 [(tool_name, args_dict), ...]。

    形状：[{"id":..., "type":"function",
            "function":{"name":"terminal","arguments":"{\\"command\\":...}"}}]
    arguments 是**字符串化的 JSON**，需二次解析。任何一步坏了就跳过该条，
    不让一条脏数据毁掉整个统计。
    """
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []

    out: list[tuple[str, dict[str, Any]]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        fn = it.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                args = {}
        out.append((name, args if isinstance(args, dict) else {}))
    return out


def command_of(name: str, args: dict[str, Any]) -> str | None:
    """从工具调用参数里取出"可比较的命令体"，没有则 None。

    terminal 是主力（实测占全部调用 66%），其次是 execute_code。
    两者都按命令/代码体去重，才能量出真实的重复率。
    """
    if name == "terminal":
        cmd = args.get("command") or args.get("cmd")
        return cmd if isinstance(cmd, str) else None
    if name == "execute_code":
        code = args.get("code")
        return code if isinstance(code, str) else None
    return None


# ── 单会话指标 ──────────────────────────────────────────────────────────

def analyze_session(con: sqlite3.Connection, sess: sqlite3.Row) -> dict[str, Any]:
    sid = sess["id"]
    rows = con.execute(
        """
        SELECT role, content, tool_calls, tool_name, compacted, timestamp, token_count
        FROM messages
        WHERE session_id = ?
        ORDER BY timestamp, id
        """,
        (sid,),
    ).fetchall()

    total_msgs = len(rows)
    compacted = sum(1 for r in rows if r["compacted"])

    total_calls = 0
    per_turn: list[int] = []
    cmd_counter: dict[str, int] = {}
    tool_counter: dict[str, int] = {}
    ctf_hits = 0
    first_flag_at: int | None = None   # 首次出现 flag 形状时，已发生的工具调用数

    for r in rows:
        for name, args in iter_calls(r["tool_calls"]):
            total_calls += 1
            tool_counter[name] = tool_counter.get(name, 0) + 1
            if name in CTF_TOOLS:
                ctf_hits += 1
            body = command_of(name, args)
            if body is not None:
                key = body.strip()
                cmd_counter[key] = cmd_counter.get(key, 0) + 1
        if calls := iter_calls(r["tool_calls"]):
            per_turn.append(len(calls))

        # flag 检测：只认 assistant 自己写出来的 flag 形状（模型在"宣称答案"），
        # 不认工具回显/题面里的示例 flag。即便如此 M5 仍只是**代理指标**：
        # 真值（是否解出 + 真实代价）只能来自 `fulilian solve` 的 work_dir
        # （FLAG 声明文件 + usage.json）。当前全部会话都是 `fulilian chat`
        # 人工解题，没有 work_dir，故 M5 仅供同版本前后对照，不可跨版本比较。
        if (first_flag_at is None and r["role"] == "assistant"
                and r["content"] and FLAG_RE.search(r["content"])):
            first_flag_at = total_calls

    distinct_cmds = len(cmd_counter)
    repeat_rate = (1.0 - distinct_cmds / total_calls) if total_calls else 0.0
    redundant = total_calls - distinct_cmds

    return {
        "session_id": sid,
        "source": sess["source"],
        "model": sess["model"],
        "title": sess["title"] or sess["display_name"] or "",
        "started_at": sess["started_at"],
        "M1_repeat_rate": round(repeat_rate, 4),
        "M1_redundant_calls": redundant,
        "M2_calls_per_turn": round(total_calls / len(per_turn), 3) if per_turn else 0.0,
        "M2_max_calls_in_turn": max(per_turn) if per_turn else 0,
        "M3_compacted_pct": round(compacted / total_msgs, 4) if total_msgs else 0.0,
        "M4_ctf_tool_calls": ctf_hits,
        "M5_calls_before_flag": first_flag_at,
        "M6_total_tool_calls": total_calls,
        "M6_distinct_commands": distinct_cmds,
        "M6_assistant_turns": len(per_turn),
        "M6_messages": total_msgs,
        "M6_compacted_messages": compacted,
        "M6_api_calls": sess["api_call_count"] or 0,
        "M6_input_tokens": sess["input_tokens"] or 0,
        "M6_output_tokens": sess["output_tokens"] or 0,
        "M6_cache_read_tokens": sess["cache_read_tokens"] or 0,
        "M6_cache_write_tokens": sess["cache_write_tokens"] or 0,
        "tool_mix": dict(
            sorted(tool_counter.items(), key=lambda kv: -kv[1])[:10]
        ),
        "top_repeated_commands": [
            {"count": c, "command": k[:160]}
            for k, c in sorted(cmd_counter.items(), key=lambda kv: -kv[1])[:5]
            if c > 1
        ],
    }


# ── 输出 ────────────────────────────────────────────────────────────────

def fmt_int(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "—"


def print_table(results: list[dict[str, Any]]) -> None:
    if not results:
        print("（无匹配会话）")
        return
    hdr = ("会话", "回合", "调用", "独立命令", "M1重复率", "M2调用/回合",
           "M3压缩%", "M4 CTF工具", "M5到flag", "M6 cache_read")
    print()
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for r in results:
        label = (r["title"] or r["session_id"])[:28]
        print(
            f"| {label} | {r['M6_assistant_turns']} | {r['M6_total_tool_calls']} "
            f"| {r['M6_distinct_commands']} | {r['M1_repeat_rate']*100:.0f}% "
            f"| {r['M2_calls_per_turn']} | {r['M3_compacted_pct']*100:.0f}% "
            f"| {r['M4_ctf_tool_calls']} "
            f"| {r['M5_calls_before_flag'] if r['M5_calls_before_flag'] is not None else '未检出'} "
            f"| {fmt_int(r['M6_cache_read_tokens'])} |"
        )


def print_aggregate(results: list[dict[str, Any]]) -> None:
    if not results:
        return
    n = len(results)
    tot_calls = sum(r["M6_total_tool_calls"] for r in results)
    tot_distinct = sum(r["M6_distinct_commands"] for r in results)
    tot_turns = sum(r["M6_assistant_turns"] for r in results)
    tot_api = sum(r["M6_api_calls"] for r in results)
    tot_read = sum(r["M6_cache_read_tokens"] for r in results)
    tot_write = sum(r["M6_cache_write_tokens"] for r in results)
    tot_ctf = sum(r["M4_ctf_tool_calls"] for r in results)
    tot_msgs = sum(r["M6_messages"] for r in results)
    tot_comp = sum(r["M6_compacted_messages"] for r in results)

    print(f"\n### 汇总（{n} 个会话）\n")
    print(f"- **M1 重复调用率：** {(1 - tot_distinct/tot_calls)*100:.1f}% "
          f"（{tot_calls - tot_distinct:,} / {tot_calls:,} 次冗余）" if tot_calls else "- M1: —")
    print(f"- **M2 工具调用/回合：** {tot_calls/tot_turns:.2f}" if tot_turns else "- M2: —")
    print(f"- **M3 被压缩消息占比：** {tot_comp/tot_msgs*100:.1f}% "
          f"（{tot_comp:,} / {tot_msgs:,}）" if tot_msgs else "- M3: —")
    print(f"- **M4 CTF 工具调用：** {tot_ctf} 次")
    print(f"- **M6 api_calls：** {fmt_int(tot_api)}")
    print(f"- **M6 cache_read：** {fmt_int(tot_read)}   cache_write：{fmt_int(tot_write)}")
    if tot_api:
        print(f"- **每次 API 调用平均 cache_read：** {tot_read/tot_api:,.0f}")
    if tot_read and tot_write:
        print(f"- **cache_read : cache_write =** {tot_read/tot_write:.1f} : 1 "
              f"（越高越健康；压缩会强制 cache_write）")


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="CTF 解题过程指标采集器（只读 state.db）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="state.db 路径")
    ap.add_argument("--session", action="append", dest="sessions",
                    help="指定会话 ID（可重复）")
    ap.add_argument("--recent", type=int, help="最近 N 个会话")
    ap.add_argument("--since", help="起始日期（ISO，如 2026-09-01）")
    ap.add_argument("--source", help="限定 source（cli / subagent / ...）")
    ap.add_argument("--list", action="store_true", help="列出最近会话后退出")
    ap.add_argument("--json", type=Path, help="把结果写成 JSON（基线归档）")
    args = ap.parse_args(argv)

    con = connect(args.db)
    try:
        if args.list:
            rows = list_sessions(con)
            print(f"\n{'会话 ID':<26} {'src':<9} {'消息':>6} {'调用':>6} {'起始':<20} 标题")
            print("-" * 100)
            for r in rows:
                ts = datetime.fromtimestamp(r["started_at"]).strftime("%Y-%m-%d %H:%M")
                print(f"{r['id']:<26} {r['source']:<9} {r['message_count']:>6} "
                      f"{r['tool_call_count'] or 0:>6} {ts:<20} "
                      f"{(r['title'] or r['display_name'] or '')[:32]}")
            print(f"\n共 {len(rows)} 个。用 --session <id> 分析单个，或 --recent N 批量。")
            return 0

        rows = resolve_sessions(
            con, session_ids=args.sessions, recent=args.recent,
            since=args.since, source=args.source,
        )
        if not rows and not args.sessions and not args.recent and not args.since:
            sys.exit("❌ 请指定 --session / --recent / --since / --list 之一")

        results = [analyze_session(con, r) for r in rows]
    finally:
        con.close()

    print_table(results)
    print_aggregate(results)

    if args.json:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema": "ctf-process-metrics/1",
            "session_count": len(results),
            "sessions": results,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✅ 已写入 {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
