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
from pathlib import Path
from datetime import datetime
from typing import Optional

from fulilian_constants import FULILIAN_HOME

LEARNING_FILE = FULILIAN_HOME / "learning.json"
TRACES_DIR = FULILIAN_HOME / "traces"


# ── 数据操作 ────────────────────────────────────────────────────────────


def load_learnings() -> dict:
    """加载学习记录。"""
    if LEARNING_FILE.exists():
        try:
            return json.loads(LEARNING_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"entries": [], "index": {}}


def save_learnings(data: dict) -> None:
    """持久化学习记录。"""
    LEARNING_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 记录经验 ────────────────────────────────────────────────────────────


def record_lesson(
    challenge_id: str,
    category: str,
    technique: str,
    success: bool,
    command: str = "",
    notes: str = "",
) -> None:
    """记录正/负知识。

    Args:
        challenge_id: 题目 ID
        category: 分类（web/crypto/reverse/pwn/forensics/misc）
        technique: 技术名称（如 "路径穿越 WAF 绕过"，"RSA 低指数攻击"）
        success: 是否成功（True=正知识，False=负知识）
        command: 关键命令
        notes: 备注
    """
    learnings = load_learnings()

    entry = {
        "challenge_id": challenge_id,
        "category": category,
        "technique": technique,
        "success": success,
        "command": command,
        "notes": notes,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    learnings["entries"].append(entry)

    # 更新 ATT&CK 索引（JSON 键必须为字符串）
    key = f"{category}::{technique}"
    if key not in learnings["index"]:
        learnings["index"][key] = {"success": 0, "fail": 0}
    if success:
        learnings["index"][key]["success"] += 1
    else:
        learnings["index"][key]["fail"] += 1

    save_learnings(learnings)


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
    for key, stats in learnings["index"].items():
        cat, _, tech = key.partition("::")
        if cat == category and stats["fail"] >= min_fail:
            bad.append(tech)
    return bad


# ── 自进化 ──────────────────────────────────────────────────────────────


def self_evolve(challenge_id: str) -> Optional[dict]:
    """自进化：解题后自动复盘 → 提取可复用知识 → 去重落库。

    流程：
    1. 读取该题的解题轨迹（trace 文件）
    2. 提取关键技术点
    3. 去重（与已有知识比较）
    4. 落库

    Args:
        challenge_id: 题目 ID

    Returns:
        dict | None: 提取结果（包含提取的知识点），无轨迹返回 None
    """
    trace_file = TRACES_DIR / f"{challenge_id}.json"
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

    # 构造可复用知识条目
    # 轨迹中的关键命令作为 technique 的来源
    knowledge_points = []
    existing = load_learnings()

    for cmd in key_commands:
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        # 简化命令为技术名称（取前 60 字符）
        technique = cmd.strip()[:60]

        # 去重：检查是否已有相似记录
        if _is_duplicate(existing, category, technique):
            continue

        knowledge_points.append({
            "challenge_id": challenge_id,
            "category": category,
            "technique": technique,
            "success": bool(flag),
            "command": cmd,
            "notes": f"自进化提取自 {challenge_id}",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    if not knowledge_points:
        return {"challenge_id": challenge_id, "extracted": 0, "new_entries": []}

    # 落库
    learnings = load_learnings()
    for kp in knowledge_points:
        learnings["entries"].append(kp)
        key = f"{kp['category']}::{kp['technique']}"
        if key not in learnings["index"]:
            learnings["index"][key] = {"success": 0, "fail": 0}
        if kp["success"]:
            learnings["index"][key]["success"] += 1
        else:
            learnings["index"][key]["fail"] += 1

    save_learnings(learnings)

    return {
        "challenge_id": challenge_id,
        "extracted": len(knowledge_points),
        "new_entries": knowledge_points,
    }


def record_solve_outcome(challenge_id: str, category: str, success: bool,
                         key_commands: list[str], flag: str = "") -> Optional[dict]:
    """一次解题尝试的结果落库（F3-003/F3-004 集成入口）。

    写 trace 文件（TRACES_DIR/{challenge_id}.json：challenge_id/category/
    key_commands/flag/timestamp），然后调用 self_evolve(challenge_id) 做
    提取→去重→落库。返回 self_evolve 的结果；IO 失败返回 None（不抛异常，
    方便调度器 best-effort 裸调）。key_commands 为空列表时也写 trace
    （self_evolve 会返回 extracted=0）。
    """
    try:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        trace = {
            "challenge_id": challenge_id,
            "category": category,
            "key_commands": list(key_commands or []),
            "flag": flag,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        (TRACES_DIR / f"{challenge_id}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError):
        return None
    try:
        return self_evolve(challenge_id)
    except Exception:  # noqa: BLE001 — 落库失败不影响调度
        return None


def _is_duplicate(learnings: dict, category: str, technique: str) -> bool:
    """检查是否已有相似记录（去重）。"""
    for entry in learnings["entries"]:
        if entry["category"] == category and entry["technique"] == technique:
            return True
    return False


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
        "file_path": str(LEARNING_FILE),
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
]