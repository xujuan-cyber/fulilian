"""跨题运行学习 + 自进化 (F3-003 / F3-004).

记录跨题的正/负知识，建立 ATT&CK 索引，避免重复犯错。
解题后自动复盘 → 提取可复用知识 → 去重落库。

数据结构：
- learning.json: 经验条目 + ATT&CK 索引
  - entries: 逐条记录（challenge_id, category, technique, success, ...）
  - index: {(category, technique) → {success, fail}}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

from fulilian_constants import get_fulilian_home

from fulilian_ctf.fsutil import (
    atomic_write_text,
    load_json_or,
    safe_filename_stem,
    update_json,
)


def _learning_file() -> Path:
    """learning.json 路径——调用时动态解析（C0-1）。

    不再固化模块级 ``FULILIAN_HOME / "learning.json"``：import 期快照会与
    ``get_fulilian_home()`` 的 ContextVar override / 运行期 env 变更分叉。
    全部读写都经本函数在调用点解析。
    """
    return get_fulilian_home() / "learning.json"


def _traces_dir() -> Path:
    """traces 目录——调用时动态解析（C0-1，口径同 ``_learning_file``）。"""
    return get_fulilian_home() / "traces"

# 噪音模式（F3-004 质量门）：提取 technique 时跳过的进程日志 / 调度输出 /
# 空白行，避免把 "solver attempt 0 started (pid 10249)" 这类运行时噪音
# 落库为「技巧」。命中任意一条即视为噪音。
NOISE_PATTERNS = [
    re.compile(r"^solver attempt \d+ (started|finished)"),
    re.compile(r"pid \d+"),          # 含进程号的行（solver 启停日志等）
    re.compile(r"^\[dispatch\]"),    # 调度器控制台输出
    re.compile(r"^\s*$"),            # 空 / 纯空白
]


def _is_noise(cmd: str) -> bool:
    """判断 key_commands 的一条记录是否为噪音行。"""
    return any(pattern.search(cmd) for pattern in NOISE_PATTERNS)


# ── 数据操作 ────────────────────────────────────────────────────────────


def _empty_learnings() -> dict:
    """新建一份空的学习记录结构（损坏重建时也用它，保证 entries/index 齐备）。"""
    return {"entries": [], "index": {}}


def load_learnings() -> dict:
    """加载学习记录（缺失/损坏时返回空结构）。"""
    return load_json_or(_learning_file(), _empty_learnings())


def save_learnings(data: dict) -> None:
    """持久化学习记录（原子写 + 锁，见 ``fsutil``）。"""
    learning_file = _learning_file()
    learning_file.parent.mkdir(parents=True, exist_ok=True)
    update_json(learning_file, lambda _cur: data, _empty_learnings())


def trace_file_for(challenge_id: str) -> Path:
    """traces 目录下该题轨迹文件路径。

    文件名经净化（``/``、``..`` 等替换），避免清单来源的 challenge_id 把轨迹
    写到子目录之外或读时路径穿越。写入方与全部读取方共用本函数以保持口径一致。
    """
    return _traces_dir() / f"{safe_filename_stem(challenge_id)}.json"


def _append_entries(learnings: dict, new_entries: list[dict]) -> None:
    """把条目追加进 ``entries`` 并同步更新 ATT&CK ``index`` 计数。

    集中落库逻辑，避免 ``record_lesson`` / ``self_evolve`` 各写一份而口径漂移。
    """
    index = learnings.setdefault("index", {})
    for entry in new_entries:
        learnings.setdefault("entries", []).append(entry)
        key = f"{entry['category']}::{entry['technique']}"
        stats = index.get(key)
        if not isinstance(stats, dict):
            stats = {"success": 0, "fail": 0}
            index[key] = stats
        stats.setdefault("success", 0)
        stats.setdefault("fail", 0)
        if entry.get("success"):
            stats["success"] += 1
        else:
            stats["fail"] += 1


# ── 记录经验 ────────────────────────────────────────────────────────────


def record_lesson(
    challenge_id: str,
    category: str,
    technique: str,
    success: bool,
    command: str = "",
    notes: str = "",
    verified: bool = False,
) -> None:
    """记录正/负知识。

    Args:
        challenge_id: 题目 ID
        category: 分类（web/crypto/reverse/pwn/forensics/misc）
        technique: 技术名称（如 "路径穿越 WAF 绕过"，"RSA 低指数攻击"）
        success: 是否成功（True=正知识，False=负知识）
        command: 关键命令
        notes: 备注
        verified: 该条经验是否经 flag 三重校验门确认（默认 False）
    """
    entry = {
        "challenge_id": challenge_id,
        "category": category,
        "technique": technique,
        "success": success,
        "command": command,
        "notes": notes,
        "verified": bool(verified),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    # 锁内读—改—写：并发记录的多个进程不会互相覆盖（原来各自 load 后整体
    # save，后写者会抹掉先写者的条目与 index 计数）
    update_json(
        _learning_file(),
        lambda data: (_append_entries(data, [entry]), data)[1],
        _empty_learnings(),
    )


# ── 查询经验 ────────────────────────────────────────────────────────────


def query_experience(
    category: Optional[str] = None,
    technique: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """查询历史经验。

    Args:
        category: 可选分类过滤
        technique: 可选技术名称过滤（模糊匹配）
        limit: 返回结果数

    Returns:
        list[dict]: 经验条目列表（按时间倒序）
    """
    learnings = load_learnings()
    results = []
    for entry in reversed(learnings["entries"]):  # 最新优先
        if category and entry["category"] != category:
            continue
        if technique and technique not in entry["technique"]:
            continue
        results.append(entry)
        if len(results) >= limit:
            break
    return results


def query_index(
    category: Optional[str] = None,
    min_total: int = 1,
) -> list[dict]:
    """查询 ATT&CK 索引。

    Args:
        category: 可选分类过滤
        min_total: 最少出现次数过滤

    Returns:
        list[dict]: [{"category", "technique", "success", "fail", "total",
                       "success_rate"}, ...]
    """
    learnings = load_learnings()
    results = []
    for key, stats in learnings["index"].items():
        # key 格式: "category::technique"
        cat, _, tech = key.partition("::")
        if category and cat != category:
            continue
        # index 可能被手工改坏（值非 dict / 缺键），跳过坏条目而不是崩掉调用方
        if not isinstance(stats, dict):
            continue
        success, fail = stats.get("success", 0), stats.get("fail", 0)
        total = success + fail
        if total < min_total:
            continue
        results.append({
            "category": cat,
            "technique": tech,
            "success": success,
            "fail": fail,
            "total": total,
            "success_rate": round(success / total, 2) if total > 0 else 0.0,
        })
    results.sort(key=lambda x: x["total"], reverse=True)
    return results


def get_avoid_list(category: str, min_fail: int = 1) -> list[str]:
    """获取「不要再犯」列表 — 特定分类下失败次数多的技术。

    Args:
        category: 分类
        min_fail: 最少失败次数

    Returns:
        list[str]: 技术名称列表
    """
    learnings = load_learnings()
    bad = []
    for key, stats in learnings.get("index", {}).items():
        cat, _, tech = key.partition("::")
        if cat != category:
            continue
        # 与 query_experience 同款防御：index 可能被手工改坏（值非 dict /
        # 缺 fail 键），一条坏数据不应让整份 avoid list 抛异常丢失
        if not isinstance(stats, dict):
            continue
        if stats.get("fail", 0) >= min_fail:
            bad.append(tech)
    return bad


# ── 自进化 ──────────────────────────────────────────────────────────────


def self_evolve(challenge_id: str, verified: bool = False) -> Optional[dict]:
    """自进化：解题后自动复盘 → 提取可复用知识 → 去重落库。

    流程：
    1. 读取该题的解题轨迹（trace 文件）
    2. 提取关键技术点（噪音行 — 进程日志/调度输出/空白 — 不入库）
    3. 去重（与已有知识比较）
    4. 落库

    Args:
        challenge_id: 题目 ID
        verified: 本次解题的 flag 是否经校验确认（写入 entry 的 verified 字段）

    Returns:
        dict | None: 提取结果（包含提取的知识点），无轨迹返回 None
    """
    trace_file = trace_file_for(challenge_id)
    if not trace_file.exists():
        return None

    try:
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # 提取元信息
    category = trace.get("category", "misc")
    key_commands = trace.get("key_commands", [])
    flag = trace.get("flag", "")

    # 正/负知识以写入方显式给出的 success 为准。仅当 trace 里没有该字段
    # （旧版轨迹）才退回「flag 非空」推断——否则一道「flag 找到了但提交被
    # 判错/放弃」的题会把全部命令记成成功技巧，污染 avoid list。
    if "success" in trace:
        success = bool(trace.get("success"))
    else:
        success = bool(flag)

    # 构造可复用知识条目
    # 轨迹中的关键命令作为 technique 的来源
    knowledge_points = []
    existing = load_learnings()
    # 去重快照：本轮已入队的技巧也要参与后续比较，否则同一次 trace 内的
    # 重复命令（黑板同一结论双记常见）会各自落库、把 index 计数虚增一倍
    known = _existing_keys(existing)

    for cmd in key_commands:
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        if _is_noise(cmd):
            # 噪音质量门：进程日志 / 调度输出行不作为 technique 入库
            continue
        # 简化命令为技术名称（取前 60 字符）
        technique = cmd.strip()[:60]

        # 去重：检查是否已有相似记录（含本轮已收集的）
        key = (category, technique)
        if key in known:
            continue
        known.add(key)

        knowledge_points.append({
            "challenge_id": challenge_id,
            "category": category,
            "technique": technique,
            "success": success,
            "command": cmd,
            "notes": f"自进化提取自 {challenge_id}",
            "verified": bool(verified),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    if not knowledge_points:
        return {"challenge_id": challenge_id, "extracted": 0, "new_entries": []}

    # 落库（锁内读—改—写，避免并发覆盖）
    update_json(
        _learning_file(),
        lambda data: (_append_entries(data, knowledge_points), data)[1],
        _empty_learnings(),
    )

    return {
        "challenge_id": challenge_id,
        "extracted": len(knowledge_points),
        "new_entries": knowledge_points,
    }


def record_solve_outcome(challenge_id: str, category: str, success: bool,
                         key_commands: list[str], flag: str = "",
                         verified: bool = False) -> Optional[dict]:
    """一次解题尝试的结果落库（F3-003/F3-004 集成入口）。

    写 trace 文件（traces/{challenge_id}.json：challenge_id/category/
    key_commands/flag/verified/timestamp），然后调用 self_evolve(challenge_id)
    做 提取→去重→落库。返回 self_evolve 的结果；IO 失败返回 None（不抛异常，
    方便调度器 best-effort 裸调）。key_commands 为空列表时也写 trace
    （self_evolve 会返回 extracted=0）。

    Args:
        verified: flag 是否经校验确认（单题路径 = flag 检测链命中；默认 False）
    """
    try:
        _traces_dir().mkdir(parents=True, exist_ok=True)
        trace = {
            "challenge_id": challenge_id,
            "category": category,
            "key_commands": list(key_commands or []),
            "flag": flag,
            # success 必须落进 trace：self_evolve 靠它判定正/负知识。此前
            # 该参数被丢弃，自进化只能从 flag 反推，负知识被记成成功技巧。
            "success": bool(success),
            "verified": bool(verified),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_write_text(
            trace_file_for(challenge_id),
            json.dumps(trace, ensure_ascii=False, indent=2),
        )
    except (OSError, TypeError, ValueError):
        return None
    try:
        return self_evolve(challenge_id, verified=verified)
    except Exception:  # noqa: BLE001 — 落库失败不影响调度
        return None


def _existing_keys(learnings: dict) -> set[tuple[str, str]]:
    """已有条目的 ``(category, technique)`` 集合（去重用）。

    对非 dict 条目 / 缺键条目跳过：旧版本残留或手工编辑过的 learning.json
    不应让整次自进化抛 KeyError 失败。
    """
    keys: set[tuple[str, str]] = set()
    for entry in learnings.get("entries", []):
        if not isinstance(entry, dict):
            continue
        cat, tech = entry.get("category"), entry.get("technique")
        if isinstance(cat, str) and isinstance(tech, str):
            keys.add((cat, tech))
    return keys


def _is_duplicate(learnings: dict, category: str, technique: str) -> bool:
    """检查是否已有相似记录（去重）。"""
    return (category, technique) in _existing_keys(learnings)


def get_learning_stats() -> dict:
    """获取学习统计。"""
    learnings = load_learnings()
    entries = learnings["entries"]
    total_entries = len(entries)
    positive = sum(1 for e in entries if e.get("success"))
    negative = total_entries - positive
    techniques = len(learnings["index"])

    # 按分类统计
    by_category: dict[str, int] = {}
    for e in entries:
        cat = e.get("category", "misc")
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "total_entries": total_entries,
        "positive": positive,
        "negative": negative,
        "techniques": techniques,
        "by_category": by_category,
        "file_path": str(_learning_file()),
    }


__all__ = [
    "load_learnings",
    "save_learnings",
    "record_lesson",
    "query_experience",
    "query_index",
    "get_avoid_list",
    "self_evolve",
    "record_solve_outcome",
    "get_learning_stats",
    "NOISE_PATTERNS",
]