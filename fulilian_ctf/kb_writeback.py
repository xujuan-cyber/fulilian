"""难题 WP 自动回灌知识库（F3-011+）。

解题成功且耗时达到"难题"门槛（默认 600 秒，env
``FULILIAN_CTF_WP_MIN_SECONDS`` 可覆盖）时，把本次解题轨迹自动生成
Writeup，写入知识库（``KB_PATH / "WP汇总" / "自产WP"``）并做 FTS5
增量索引，使自产 WP 立即可被 ``knowledge_retriever.search`` 检索。

设计约束：
- **fail-open**：任何失败（时钟缺失/生成失败/写盘失败/索引失败）只返回
  None 或打印 stderr 告警，绝不抛异常——不影响解题主流程与调度。
- **防泄漏**：flag 明文不写入 WP（frontmatter 与正文均写"已验证 ✔"）。
- **去重**：同 challenge 同日同名 WP 已存在则跳过（宁缺毋滥）。
- KB_PATH / DB_PATH 取 ``knowledge_retriever`` 的运行时解析值（模块属性
  访问，测试可 monkeypatch），不硬编码仓库路径。
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# 难题门槛默认值（秒）：解出耗时 >= 该值才视为"难题"回灌 WP
DEFAULT_MIN_SECONDS = 600

# FTS5 增量索引写入的表结构，镜像 knowledge_retriever.CREATE_TABLE_SQL：
# writeups(title, category, content, source_path UNINDEXED)
_INCREMENTAL_INSERT_SQL = (
    "INSERT INTO writeups (title, category, content, source_path) "
    "VALUES (?, ?, ?, ?)"
)

# challenge_id 中的路径不安全字符（防目录穿越/非法文件名）
_UNSAFE_CHARS_RE = re.compile(r"[^0-9A-Za-z._\-]+")

# FTS5 content 截断长度（与 build_index 保持一致）
_MAX_CONTENT_CHARS = 200_000


def _min_seconds() -> int:
    """难题门槛秒数：env FULILIAN_CTF_WP_MIN_SECONDS > 默认 600。"""
    raw = os.environ.get("FULILIAN_CTF_WP_MIN_SECONDS", "").strip()
    try:
        value = int(raw)
        if value >= 0:
            return value
    except ValueError:
        pass
    return DEFAULT_MIN_SECONDS


def _safe_filename_stem(challenge_id: str) -> str:
    """challenge_id → 文件名安全片段（斜杠/空白等替换为下划线）。"""
    stem = _UNSAFE_CHARS_RE.sub("_", str(challenge_id).strip())
    return stem or "challenge"


def _redact_flag(text: str, flags: list[str]) -> str:
    """把 flag 明文从 WP 文本中替换为"已验证 ✔"（防泄漏）。"""
    for flag in flags:
        if flag and flag in text:
            text = text.replace(flag, "已验证 ✔")
    return text


def _build_frontmatter(
    challenge_id: str,
    category: str,
    elapsed: int,
    model_hint: str,
) -> str:
    """frontmatter 风格头部：来源/题目/分类/日期/耗时/模型（flag 防泄漏）。"""
    minutes = max(0, elapsed) // 60
    lines = [
        "---",
        "source: fulilian 自动沉淀",
        f"challenge_id: {challenge_id}",
        f"category: {category}",
        f"date: {date.today().isoformat()}",
        f"solve_minutes: {minutes}",
        "flag: 已验证 ✔",
        f"model: {model_hint or 'n/a'}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _incremental_index(file_path: Path, category: str, content: str) -> bool:
    """把单篇 WP 直接 INSERT 进 FTS5 writeups 表（增量索引）。

    行结构镜像 knowledge_retriever.build_index() 的 INSERT 语句：
    (title=文件名 stem, category, content=正文截断, source_path=绝对路径)。

    失败（表结构不符 / DB 锁 / 表不存在）降级：stderr 告警，返回 False——
    文件已在库中，下次 force 重建自然入索引。
    """
    from fulilian_ctf import knowledge_retriever as kr

    try:
        conn = sqlite3.connect(str(kr.DB_PATH), timeout=5)
        try:
            conn.execute(
                _INCREMENTAL_INSERT_SQL,
                (
                    file_path.stem,
                    category,
                    content[:_MAX_CONTENT_CHARS],
                    str(file_path),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:  # noqa: BLE001 — 增量索引失败降级为告警
        print(
            f"[kb_writeback] FTS5 增量索引失败（文件已入库，下次重建索引生效）: {exc}",
            file=sys.stderr,
        )
        return False


def writeback_wp_for_solve(
    challenge_id: str,
    category: str,
    work_dir: str | Path,
    flag: str,
    model_hint: str = "",
) -> Optional[Path]:
    """难题解出后把 WP 自动写入知识库并做 FTS5 增量索引。

    Args:
        challenge_id: 题目 ID
        category: 题目分类（空时按内容/文件名自动推断）
        work_dir: 挑战工作目录（solver.log / blackboard / FLAG 所在）
        flag: 已验证的 flag（不写入 WP，防泄漏）
        model_hint: 求解模型名（frontmatter 元信息）

    Returns:
        Path: 写入的 WP 文件路径；未达门槛 / 时钟缺失 / 去重跳过 / 任何
        失败返回 None（fail-open，绝不抛异常）。
    """
    try:
        if not flag or not challenge_id:
            return None
        work_dir = Path(work_dir)

        # 难题门槛：解题时钟缺失（.solve_start 不存在/损坏）直接不回灌
        from fulilian_ctf import solve_clock

        elapsed = solve_clock.elapsed_seconds(work_dir)
        if elapsed is None:
            return None
        if elapsed < _min_seconds():
            return None

        # 生成 WP：复用 writeup.generate_writeup（内部 get_or_build_trace，
        # work_dir 下已有 trace/blackboard/FLAG）
        from fulilian_ctf.trace import get_or_build_trace
        from fulilian_ctf.writeup import generate_writeup

        trace = get_or_build_trace(work_dir)
        writeup_md = generate_writeup(
            challenge_id, work_dir, trace=trace
        ) or ""
        if not writeup_md.strip():
            return None

        # 防泄漏：flag 明文替换为"已验证 ✔"（正文 Flag 节与可能含 flag 的
        # fact/输出一并进行）
        writeup_md = _redact_flag(
            writeup_md, [flag, getattr(trace, "flag", "") or ""]
        )

        # frontmatter 头部 + 正文
        from fulilian_ctf import knowledge_retriever as kr

        kb_path = kr.KB_PATH
        full_md = _build_frontmatter(
            challenge_id, category or "misc", elapsed, model_hint
        ) + writeup_md

        target_dir = kb_path / "WP汇总" / "自产WP"
        file_name = f"{_safe_filename_stem(challenge_id)}-{date.today():%Y%m%d}.md"
        target = target_dir / file_name
        if target.exists():
            return None  # 去重：同 challenge 同日已沉淀，跳过

        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(full_md, encoding="utf-8")

        # FTS5 增量索引（失败降级：文件在库中，force 重建自然入索引）
        resolved_category = category or kr._guess_category(target, full_md)
        _incremental_index(target, resolved_category, full_md)

        return target
    except Exception as exc:  # noqa: BLE001 — WP 回灌全程 fail-open
        print(f"[kb_writeback] WP 回灌失败（静默降级）: {exc}", file=sys.stderr)
        return None


__all__ = ["DEFAULT_MIN_SECONDS", "writeback_wp_for_solve"]
