"""文件系统小工具 — 原子写 + 跨进程串行化的 JSON 读改写。

背景（P1 修复）：``learning.json`` / ``wp_technique_index.json`` 这类全局共享
的 JSON 状态此前是「裸 read_text → 改 → write_text」。两个 ``fulilian solve``
进程并行结束时会各自读入同一份快照再整体覆盖，后写者抹掉先写者；写入中途被
杀还会留下截断的 JSON，而 ``load_*`` 对损坏内容一律静默回退成空 dict，
下一次保存就把全部历史清空。

本模块提供两件事：

- :func:`atomic_write_text` — 先写「带 pid+uuid 的临时文件」再 ``replace``，
  任何时刻正式文件要么是旧的完整内容、要么是新的完整内容；
- :func:`update_json` — 在排他文件锁内完成 read → mutate → 原子写，
  多进程并发更新不再互相丢数据。

锁用 ``fcntl.flock``（POSIX）。Windows 无 fcntl 时降级为无锁——此时仍有
原子替换保底（不会写坏文件），只是并发更新可能丢条目。
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

try:  # pragma: no cover - 平台分支
    import fcntl  # POSIX 文件锁；Windows 无此模块
except ImportError:  # pragma: no cover - Windows only
    fcntl = None  # type: ignore[assignment]

__all__ = ["atomic_write_text", "path_lock", "load_json_or", "update_json"]


@contextmanager
def path_lock(path: Path) -> Iterator[None]:
    """对 ``path`` 的同级 ``<name>.lock`` 取排他锁（fcntl 不可用时为空操作）。

    锁文件本身不承载内容，仅用于跨进程串行化「读—改—写」这一整个区间，
    因此调用方必须把读取放在锁内，只包住写入是无效的。
    """
    if fcntl is None:  # pragma: no cover - Windows only
        yield
        return
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_write_text(path: str | Path, text: str, *, lock: bool = True) -> Path:
    """原子写入文本：临时文件 → ``replace`` 到目标路径。

    临时文件名带 pid + uuid，避免多个进程并发保存同一路径时互相覆盖临时文件。
    ``lock=True`` 时在 ``<name>.lock`` 上取排他锁，串行化并发替换动作。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")

    def _do_write() -> None:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    if lock:
        with path_lock(path):
            _do_write()
    else:
        _do_write()
    return path


def load_json_or(path: str | Path, default: Any) -> Any:
    """读取 JSON；文件缺失 / 损坏 / 不可读时返回 ``default``。

    注意：调用方**不应**把「损坏得到 default」直接写回去——那会静默清空
    历史数据。需要回写时用 :func:`update_json`，它在锁内区分两种情形。
    """
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return default


def update_json(
    path: str | Path,
    mutate: Callable[[Any], Any],
    default: Any,
    *,
    indent: int = 2,
    corrupt_backup: bool = True,
) -> Any:
    """锁内 read → ``mutate`` → 原子写，返回写回后的数据。

    与「裸读改写」的区别：

    - 整个区间持排他锁，多进程并发更新不会互相覆盖；
    - 原子替换，崩溃不会留下截断 JSON；
    - 正式文件存在但内容损坏时**不**用 ``default`` 静默覆盖，而是先把损坏
      文件另存为 ``<name>.corrupt-<ts>``（``corrupt_backup=True``）再重建，
      保住证据。``mutate`` 仍会在 ``default`` 上执行。

    Args:
        mutate: 接收当前数据、返回要落库的新数据（可就地修改后返回）。
    """
    path = Path(path)
    with path_lock(path):
        data = None
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, ValueError):
                data = None
                if corrupt_backup:
                    _backup_corrupt(path)
        if data is None:
            data = default
        new_data = mutate(data)
        if new_data is None:
            new_data = data
        atomic_write_text(
            path,
            json.dumps(new_data, ensure_ascii=False, indent=indent),
            lock=False,  # 已在锁内
        )
        return new_data


def _backup_corrupt(path: Path) -> None:
    """把损坏的 JSON 另存为 ``<name>.corrupt-<timestamp>``，绝不静默丢弃。"""
    import time

    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.replace(target)
    except OSError:
        pass


def safe_filename_stem(value: str) -> str:
    """把任意文本净化为可安全用作文件名的片段（路径穿越 / 分隔符防御）。

    challenge_id 来自清单文件等自由文本，可能含 ``/``、``..``、空格；直接内插
    进文件名会让 trace 写到子目录（OSError）甚至穿越到目录之外。
    """
    import re

    stem = re.sub(r"[^\w.\-]+", "_", str(value), flags=re.UNICODE).strip("._")
    if not stem:
        stem = "unnamed"
    # 单独一个 "." / ".." 已被 strip("._") 清空，此处再兜一层
    if stem in (".", ".."):
        stem = "unnamed"
    return stem[:120]
