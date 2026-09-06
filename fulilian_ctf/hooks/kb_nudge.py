#!/usr/bin/env python3
"""kb_nudge.py — 解题超时知识库思路注入（post_tool_call 进程内 hook）。

单题求解超过阈值（默认 600 秒，环境变量 ``FULILIAN_CTF_KB_NUDGE_SECONDS``
可覆盖，单位秒）后，在下一次 terminal 工具调用完成后检索
Des-CTF-Knowledge（FTS5，见 knowledge_retriever），把命中的历史 WP 思路
按 ``{"context": "..."}`` wire 协议注入运行中的解题会话（与 detect_flag
同一注入通道）。

行为约定：
- 一次性：注入成功后在 work_dir 写 ``.kb_nudged`` 标记文件；标记存在即
  跳过（跨进程安全）。标记写入失败也不重试轰炸——模块级按 work_dir 节流
  （同 work_dir 两次触发尝试最小间隔），宽松语义下宁可不注入也不刷屏。
- query 构造：黑板（blackboard.json）中 CONFIRMED/REFUTED fact 文本
  （最多 5 条、每条截 80 字符）+ challenge_id 前缀启发出的分类过滤。
  分类启发在本地实现（不 import fulilian_ctf.cli，避免循环 import）。
  黑板缺失/为空则本次跳过——宁缺毋滥，不拿空查询轰索引。
- 检索结果为空则不注入（返回 None）。
- fail-open：任何异常一律返回 None，绝不阻断工具调用、绝不抛异常。

本模块仅供 ``fulilian_ctf.hooks.register_ctf_tool_hooks()`` 进程内注册，
不提供独立脚本（无手动 shell-hook 注册场景：黑板/时钟都在求解进程内）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# 环境变量 / 文件名常量
ENV_NUDGE_SECONDS = "FULILIAN_CTF_KB_NUDGE_SECONDS"
ENV_WORK_DIR = "FULILIAN_CTF_WORK_DIR"
KB_NUDGED_FILENAME = ".kb_nudged"

# 默认触发阈值（秒）：解题超过 10 分钟
DEFAULT_THRESHOLD_SECONDS = 600

# 模块级节流：同一 work_dir 两次触发尝试的最小间隔（秒），防误触发洪水
MIN_ATTEMPT_INTERVAL_SECONDS = 60.0

# query 构造参数
MAX_FACTS = 5
MAX_FACT_CHARS = 80
SEARCH_LIMIT = 3
MAX_SNIPPET_CHARS = 300

# 按 work_dir 记录上次触发尝试时刻（time.monotonic）
_last_attempt_ts: dict[str, float] = {}


def _threshold_seconds() -> int:
    """读取触发阈值（秒）；环境变量非法/未设回退默认值。"""
    raw = os.environ.get(ENV_NUDGE_SECONDS, "").strip()
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_THRESHOLD_SECONDS


def _guess_category_from_id(challenge_id: str) -> str:
    """从 challenge id 猜测分类（与 fulilian_ctf.cli 同款简单启发）。

    本地实现以避免 import cli 造成循环（cli 在 solve 路径 import hooks）。
    """
    cid = str(challenge_id or "").lower()
    for cat in ("forensics", "crypto", "reverse", "pwn", "web", "misc"):
        if cid.startswith(cat) or f"-{cat}" in cid or f"_{cat}" in cid:
            return cat
    return ""


def _collect_fact_texts(work_dir: Path) -> tuple:
    """从黑板提取 CONFIRMED/REFUTED fact 文本。

    Returns:
        (fact_texts, challenge_id)；黑板缺失/加载失败返回 ([], "")。
    """
    from fulilian_ctf.blackboard import BLACKBOARD_FILENAME, State, load_blackboard

    board = load_blackboard(work_dir / BLACKBOARD_FILENAME)
    if board is None:
        return [], ""
    texts: list[str] = []
    for fact in board.get_facts():
        if len(texts) >= MAX_FACTS:
            break
        if fact.state not in (State.CONFIRMED, State.REFUTED):
            continue
        content = str(fact.content or "").strip()
        if content:
            texts.append(content[:MAX_FACT_CHARS])
    return texts, str(board.challenge_id or "")


def _format_context(results: list, threshold_seconds: int) -> str:
    """把检索结果格式化为注入上下文（中文提示块）。"""
    minutes = max(1, threshold_seconds // 60)
    lines = [f"⏱ 解题已超过 {minutes} 分钟。知识库中与本题相关的历史思路："]
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "(untitled)"
        source = str(item.get("source_path", "")).strip()
        snippet = str(item.get("snippet", "")).strip()[:MAX_SNIPPET_CHARS]
        lines.append(f"【{title}】({source})：{snippet}")
    return "\n".join(lines)


def _kb_nudge_post_tool_hook(*, tool_name=None, result=None, **_kw):
    """post_tool_call 回调：解题超时后一次性注入知识库历史思路。

    签名/返回值与 ``_ctf_post_tool_hook`` 同一 wire 协议：返回
    ``{"context": "..."}`` 注入上下文；不触发/失败返回 None（fail-open）。
    """
    if tool_name != "terminal":
        return None
    try:
        work_dir = os.environ.get(ENV_WORK_DIR, "").strip()
        if not work_dir:
            return None
        wd = Path(work_dir)

        # 一次性去重：标记存在即跳过（宽松语义：读不到才继续）
        if (wd / KB_NUDGED_FILENAME).exists():
            return None

        # 模块级节流：同 work_dir 两次尝试最小间隔，防误触发洪水
        key = str(wd)
        now = time.monotonic()
        last = _last_attempt_ts.get(key)
        if last is not None and now - last < MIN_ATTEMPT_INTERVAL_SECONDS:
            return None
        _last_attempt_ts[key] = now

        # 解题时钟：未超阈值不触发
        from fulilian_ctf.solve_clock import elapsed_seconds

        threshold = _threshold_seconds()
        elapsed = elapsed_seconds(wd)
        if elapsed is None or elapsed < threshold:
            return None

        # query 构造：黑板 fact 文本；黑板空/缺失则跳过（宁缺毋滥）
        fact_texts, challenge_id = _collect_fact_texts(wd)
        query = " ".join(fact_texts).strip()
        if not query:
            return None
        category = _guess_category_from_id(challenge_id) or None

        from fulilian_ctf.knowledge_retriever import search

        results = search(query, category=category, limit=SEARCH_LIMIT)
        if not results:
            return None

        context = _format_context(results, threshold)

        # 注入成功后落一次性标记；写失败不影响本次注入（节流兜底）
        try:
            (wd / KB_NUDGED_FILENAME).write_text(
                str(int(time.time())), encoding="utf-8"
            )
        except OSError:
            pass
        return {"context": context}
    except Exception:  # noqa: BLE001 — fail-open：绝不阻断工具调用
        return None


__all__ = [
    "DEFAULT_THRESHOLD_SECONDS",
    "ENV_NUDGE_SECONDS",
    "ENV_WORK_DIR",
    "KB_NUDGED_FILENAME",
    "MIN_ATTEMPT_INTERVAL_SECONDS",
    "_kb_nudge_post_tool_hook",
]
