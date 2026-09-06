"""解题时钟 — work_dir 级起始时刻标记与耗时读取（WP 回灌门槛 / 知识库检索注入共用）。

mark_solve_start(work_dir) 在求解开始时写 ``.solve_start``（epoch 秒）；
elapsed_seconds(work_dir) 读回耗时秒数。判难（难题 WP 回灌）与
"解题超 10 分钟检索知识库"注入共用同一时钟，保证口径一致。

文件缺失/损坏一律返回 None（调用方 best-effort，自行降级），绝不抛异常——
求解主流程与 hook 均不得因时钟问题崩溃。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

MARKER_FILENAME = ".solve_start"


def mark_solve_start(work_dir: str | Path) -> None:
    """记录求解开始时刻（覆盖写；IO 失败静默）。"""
    try:
        wd = Path(work_dir)
        wd.mkdir(parents=True, exist_ok=True)
        (wd / MARKER_FILENAME).write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def elapsed_seconds(work_dir: str | Path) -> Optional[int]:
    """读取自求解开始以来的耗时（秒）；无标记/标记损坏返回 None。"""
    try:
        text = (Path(work_dir) / MARKER_FILENAME).read_text(encoding="utf-8").strip()
        return max(0, int(time.time()) - int(text))
    except (OSError, ValueError):
        return None


__all__ = ["MARKER_FILENAME", "mark_solve_start", "elapsed_seconds"]
