"""挑战目标解析 — ``fulilian solve`` 的前置定位（纯只读，不落盘）。

背景：``fulilian solve <id>`` 接受「Challenge ID 或目录」。若传入无法定位的
目标（如不存在的路径），既有管线会在任意位置 mkdir 空工作目录并直接 spawn
agent，agent 在文件系统里乱找十几轮 API 调用白烧 token。本模块在启动 agent
之前判断目标是否「可定位」，不可定位返回 None，由调用方快速报错退出。

解析顺序与 ``fulilian_ctf.cli._resolve_project``（默认单 agent 路径）保持一致，
历史轨迹途径对齐 writeup/replay 的 ``_resolve_writeup_inputs``，避免误杀合法
输入：

1. 存在的目录（裸挑战目录 / 含 challenge.json / 平台清单目录）→ 该目录
2. 清单文件（``registry.load_challenges`` 可解析出挑战，如 ``manifest.json``）
   → 条目的工作目录
3. 历史轨迹 ``FULILIAN_HOME/traces/<id>.json``（``record_solve_outcome`` 写入）
   → solve 将按既有机制新建的 ``cwd/<id>`` 目录
4. 相对裸 id（如 ``web-01``）→ 既有机制：在 cwd 下建同名工作目录，放行

其余（不存在的路径形态输入、不可解析的非清单文件、空白 id）→ None。
纯只读检查：不创建任何目录、不写任何文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fulilian_ctf.registry import CHALLENGE_MANIFEST

__all__ = [
    "looks_like_path",
    "solve_work_dir_for",
    "load_historical_trace",
    "resolve_challenge_target",
]


def looks_like_path(challenge_id: str) -> bool:
    """启发式：输入是否「看起来像路径」（区别于 web-01 这类裸挑战 id）。"""
    if os.sep in challenge_id or (os.altsep and os.altsep in challenge_id):
        return True
    if challenge_id.startswith((".", "~")):
        return True
    return Path(challenge_id).suffix != ""


def solve_work_dir_for(project, challenge_id: str) -> str:
    """纯读镜像 ``cli._prepare_work_dir`` 的目录选择（不落盘、不 mkdir）。

    清单文件形态（challenge_id 指向 .json 且无独立 challenge_dir）在 cwd 求解，
    其余返回 challenge_dir（expanduser + absolute 规范化）。
    """
    raw = Path(project.challenge_dir or challenge_id).expanduser()
    if raw.suffix and not raw.is_dir():
        return str(Path.cwd())
    return str(raw.absolute())


def load_historical_trace(challenge_id: str) -> Optional[dict]:
    """读取 FULILIAN_HOME/traces/{id}.json（record_solve_outcome 的历史轨迹）。"""
    try:
        from fulilian_constants import get_fulilian_home

        # 文件名净化口径必须与写入方（experiential_learning.trace_file_for）
        # 一致，否则含 "/" 的 challenge_id 写入与读取会指向不同文件。
        # 目录在调用时从 get_fulilian_home() 动态解析（C0-1）。
        from fulilian_ctf.fsutil import safe_filename_stem

        trace_file = (
            get_fulilian_home() / "traces" / f"{safe_filename_stem(challenge_id)}.json"
        )
        if trace_file.is_file():
            return json.loads(trace_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ImportError):
        pass
    return None


def resolve_challenge_target(challenge_id: str) -> Optional[str]:
    """判断挑战目标是否可定位：可定位返回将要使用的 work_dir，否则 None。

    Args:
        challenge_id: Challenge ID 或目录（``fulilian solve`` 的位置参数）。
            None / 空白串按不可定位处理。

    Returns:
        work_dir 路径（规范化字符串）或 None（不可定位）。注意「可定位」
        不代表目录已存在：裸 id 与仅有历史轨迹的挑战按既有机制在 cwd 下
        新建同名工作目录（见 ``cli._resolve_project`` 尾分支）。
    """
    if not challenge_id or not challenge_id.strip():
        return None
    try:
        return _resolve(challenge_id)
    except (OSError, ValueError, KeyError, TypeError):
        # 病态输入（空字节路径）/ 损坏的 challenge.json / 缺 id 的条目：
        # 目标无效，交由调用方快速报错，而不是带着 agent 裸奔
        return None


def _resolve(challenge_id: str) -> Optional[str]:
    """解析主体（异常由 ``resolve_challenge_target`` 统一兜底）。"""
    path = Path(challenge_id).expanduser()

    # 1) 存在的目录本身就是挑战（含 challenge.json 的题目目录同样放行）
    if path.is_dir():
        challenge_json = path / CHALLENGE_MANIFEST
        if not challenge_json.is_file():
            return str(path.absolute())
        from fulilian_ctf.registry import challenge_json_to_project

        project = challenge_json_to_project(challenge_json)
        return solve_work_dir_for(project, challenge_id)

    # 2) 清单文件 / 其它 load_challenges 可解析形态
    from fulilian_ctf.registry import challenge_to_project, load_challenges

    try:
        entries = [e for e in load_challenges(challenge_id) if e.get("id")]
    except (ValueError, OSError, KeyError, TypeError):
        entries = []
    if entries:
        return solve_work_dir_for(challenge_to_project(entries[0]), challenge_id)

    # 3) 历史轨迹（与 writeup/replay 同源，record_solve_outcome 写入）
    if load_historical_trace(challenge_id) is not None:
        return str(path.absolute())

    # 4) 相对裸 id：cwd 下建同名工作目录是既有机制，放行
    if not looks_like_path(challenge_id):
        return str(path.absolute())

    return None
