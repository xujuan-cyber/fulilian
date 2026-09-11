"""难题 WP 自动回灌统一知识库（自学习闭环·卡E，2026-09-06 规范对齐版）。

解题成功且耗时达到"难题"门槛（默认 600 秒，env
``FULILIAN_CTF_WP_MIN_SECONDS`` 覆盖）时，把 generate_writeup 产出的
WP 落到统一知识库自产 WP 唯一区 ``CTF大赛WP集合/self-solved/``，
元数据单源登记 ``wp_technique_index.json``（similar_by_technique 的
唯一数据源），并做 FTS5 增量索引，使 ``fulilian knowledge query`` /
``kr.search`` / ``kr.similar_by_technique`` 立即可查。

规范依据：~/Exchange/fulilian-知识沉淀规范-20260906.md
- 纯正文（无 frontmatter），元数据单源进 technique index；
- 题级去重（同 challenge_id 已存在即跳过，不带日期后缀）；
- 本地自产库允许 flag 明文（区别于对外分享）；
- fail-open：任何失败只返回 None / stderr 告警，绝不影响求解退出码；
- KB_PATH 取 knowledge_retriever 运行时解析值，测试可 monkeypatch。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# 难题门槛默认值（秒）：解出耗时 >= 该值才视为"难题"回灌 WP
DEFAULT_MIN_SECONDS = 600

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


def _technique_index_path(wp_path: Path) -> Path:
    return wp_path.parent.parent / "wp_technique_index.json"


def _is_registered(wp_path: Path) -> bool:
    """该 WP 是否已在 wp_technique_index.json 登记（幂等重跑判据）。

    只看文件是否存在做去重是不够的：文件写完、登记执行前进程被杀，重跑时
    文件已存在便直接 return，该 WP 永远进不了索引（similar_by_technique
    再也搜不到）。因此去重必须同时要求「已登记」。
    """
    index_path = _technique_index_path(wp_path)
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and wp_path.name in data


def _register_technique_index(wp_path: Path, title: str, category: str,
                              challenge_id: str) -> bool:
    """把自产 WP 登记进 wp_technique_index.json（元数据单源）。

    该文件是 kr.similar_by_technique() 的唯一数据源，不登记则"按考点找
    相似题"永远搜不到本篇。已存在时读入合并追加，绝不覆盖既有条目。
    自动通道 tags 最少给 [category, challenge_id]，人工复盘可补全。

    并发安全：锁内读—改—写 + 原子替换（多个 solve 进程同时达到回灌门槛时，
    原来的裸读改写会让后写者抹掉先写者的登记；读失败时还会用仅含新条目的
    dict 覆盖整个文件，历史登记全灭）。

    Returns:
        bool: 是否登记成功。失败仅 stderr 告警（fail-open）。
    """
    index_path = _technique_index_path(wp_path)
    entry = {
        "title": title,
        "source_path": str(wp_path),
        "tags": [tag for tag in (category, challenge_id) if tag],
    }

    def _merge(data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        data[wp_path.name] = entry
        return data

    try:
        from fulilian_ctf.fsutil import update_json

        update_json(index_path, _merge, {})
        return True
    except (OSError, ValueError) as exc:
        print(
            f"[kb_writeback] technique index 登记失败"
            f"（similar_by_technique 将搜不到本篇）: {exc}",
            file=sys.stderr,
        )
        return False


def _incremental_index(file_path: Path, category: str, content: str) -> bool:
    """把单篇 WP 增量插入 FTS5 writeups 表。

    行结构镜像 knowledge_retriever.build_index()：title=文件名 stem、
    category、content 截 200k、source_path=绝对路径。SQL 为常量字面量，
    所有运行时值经 sqlite3 参数绑定传入。失败（表结构不符 / DB 锁 /
    表不存在）降级：stderr 告警，返回 False——文件已在库中，下次 force
    重建自然入索引。
    """
    from fulilian_ctf import knowledge_retriever as kr

    try:
        content_trunc = content[:_MAX_CONTENT_CHARS]
        row = (file_path.stem, category, content_trunc, str(file_path))
        conn = sqlite3.connect(str(kr.DB_PATH), timeout=5)
        try:
            conn.executemany(
                "INSERT INTO writeups (title, category, content, source_path) VALUES (?, ?, ?, ?)",
                [row],
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

    落点为统一知识库自产 WP 唯一区 ``CTF大赛WP集合/self-solved/``，
    纯正文（无 frontmatter），元数据单源登记 wp_technique_index.json。

    Args:
        challenge_id: 题目 ID（同时作为文件名主体与题级去重键）
        category: 题目分类（空时按内容/文件名自动推断）
        work_dir: 挑战工作目录（solver.log / blackboard / FLAG 所在）
        flag: 已验证的 flag（本地自产库允许明文保留）
        model_hint: 保留参数（元数据单源进 technique index，正文不含）

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

        from fulilian_ctf import knowledge_retriever as kr

        kb_path = kr.KB_PATH
        target_dir = kb_path / "CTF大赛WP集合" / "self-solved"
        # 题级去重：同 challenge 已沉淀（不带日期后缀，同题不重写）。
        # 判据是「文件存在 **且** 已登记」——只判文件存在会漏补：写完文件、
        # 登记执行前进程被杀，重跑时直接 return，该 WP 永远进不了 technique
        # index（FTS 可靠 force 重建补救，index 不会）。
        target = target_dir / f"{_safe_filename_stem(challenge_id)}.md"
        registered = _is_registered(target)
        if target.exists() and registered:
            return None
        if not target.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            # 原子写：进程中断不会留下半截 WP 被后续 build_index 摄入
            from fulilian_ctf.fsutil import atomic_write_text

            atomic_write_text(target, writeup_md)

        # 元数据单源登记（similar_by_technique 的数据源）
        title = writeup_md.splitlines()[0].lstrip("# ").strip() or challenge_id
        resolved_category = category or kr._guess_category(target, writeup_md)
        _register_technique_index(target, title, resolved_category, challenge_id)

        # FTS5 增量索引（失败降级：文件在库中，force 重建自然入索引）
        _incremental_index(target, resolved_category, writeup_md)

        return target
    except Exception as exc:  # noqa: BLE001 — WP 回灌全程 fail-open
        print(f"[kb_writeback] WP 回灌失败（静默降级）: {exc}", file=sys.stderr)
        return None


__all__ = ["DEFAULT_MIN_SECONDS", "writeback_wp_for_solve"]
