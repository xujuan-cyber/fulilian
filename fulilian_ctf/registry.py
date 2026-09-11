"""题目注册表 — 从平台目录/清单加载挑战（solve-all 的数据入口）。

平台（platform 参数）可以是：

1. JSON 清单文件（platform.json / manifest.json / challenges.json 或任意 .json）
   格式：{"name": ..., "challenges": [{"id", "title", "category", "difficulty",
   "score", "target_host", "target_port", "description", "dir", "timebox", "model"}]}
   ``dir`` 为相对平台的挑战工作目录（缺省用平台目录本身）。

2. 目录：优先找 platform.json / manifest.json / challenges.json；
   否则扫描子目录中的 challenge.json（每个子目录一道题）。

返回原始 dict 列表（数据层），由调用方通过 challenge_to_project() 转 Project。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

MANIFEST_NAMES = ("platform.json", "manifest.json", "challenges.json")
CHALLENGE_MANIFEST = "challenge.json"

DEFAULT_MANIFEST_FIELDS = {
    "difficulty": "medium",
    "score": 0,
    "target_host": "",
    "target_port": 0,
    "description": "",
}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"manifest {path} must be a JSON object")
    return data


def _validate_entries(entries: list[dict], source: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"invalid challenge entry in {source}: {entry!r}")
        cid = str(entry.get("id", "")).strip()
        if not cid:
            raise ValueError(f"challenge entry in {source} is missing 'id'")
        if cid in seen:
            raise ValueError(f"duplicate challenge id '{cid}' in {source}")
        seen.add(cid)
        normalized = dict(DEFAULT_MANIFEST_FIELDS)
        normalized.update(entry)
        normalized["id"] = cid
        normalized["difficulty"] = str(normalized["difficulty"]).lower()
        normalized["score"] = int(normalized.get("score") or 0)
        try:
            normalized["target_port"] = int(normalized.get("target_port") or 0)
        except (TypeError, ValueError):
            normalized["target_port"] = 0
        out.append(normalized)
    return out


def _load_manifest_file(manifest: Path) -> list[dict]:
    data = _read_json(manifest)
    entries = data.get("challenges") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"manifest {manifest} must contain a 'challenges' list")
    return _validate_entries(entries, str(manifest))


def _absolutize_work_dirs(entries: list[dict], base: Path) -> list[dict]:
    """把条目中相对的 ``challenge_dir`` / ``dir`` 规范为绝对路径。

    ``dir`` 的语义是「相对平台的挑战工作目录」（见模块 docstring），但下游
    ``challenge_to_project`` 只在显式收到 ``base_dir`` 时才按 base 解析，否则
    相对值会被当成相对 cwd —— ``fulilian solve /path/platform/manifest.json``
    会在 cwd 下新建空目录求解，绕开真正的题目文件。

    这里在加载期按已知的清单/平台位置统一规范化，使所有调用方（含不传
    ``base_dir`` 的）拿到一致结果；已是绝对路径的值原样保留。
    """
    base_abs = base.expanduser().absolute()
    for entry in entries:
        for key in ("challenge_dir", "dir"):
            raw = entry.get(key)
            if isinstance(raw, str) and raw.strip():
                expanded = Path(raw).expanduser()
                if not expanded.is_absolute():
                    entry[key] = str(base_abs / expanded)
    return entries


def load_challenges(platform: str | Path) -> list[dict]:
    """加载平台上的全部挑战（原始 dict 列表）。找不到/格式错抛 ValueError。"""
    p = Path(platform).expanduser()

    if p.is_file():
        return _absolutize_work_dirs(_load_manifest_file(p), p.parent)

    if p.is_dir():
        # 1) 平台清单
        for name in MANIFEST_NAMES:
            mf = p / name
            if mf.is_file():
                return _absolutize_work_dirs(_load_manifest_file(mf), p)
        # 2) 平台根目录直接是单道题（challenge.json 在根下）
        root_cf = p / CHALLENGE_MANIFEST
        if root_cf.is_file():
            entry = _read_json(root_cf)
            if "challenges" in entry:
                raise ValueError(
                    f"{root_cf} is a platform manifest, not a single challenge object"
                )
            entry.setdefault("challenge_dir", str(p))
            return _absolutize_work_dirs(_validate_entries([entry], str(root_cf)), p)
        # 3) 子目录 challenge.json
        found: list[dict] = []
        for sub in sorted(p.iterdir()):
            if sub.is_dir():
                cf = sub / CHALLENGE_MANIFEST
                if cf.is_file():
                    entry = _read_json(cf)
                    if not isinstance(entry, dict) or "challenges" in entry:
                        raise ValueError(
                            f"{cf} must be a single challenge object (id/title/...), "
                            "not a platform manifest"
                        )
                    entry.setdefault("challenge_dir", str(sub))
                    found.append(entry)
        if found:
            return _absolutize_work_dirs(_validate_entries(found, str(p)), p)
        raise ValueError(
            f"no challenges found under {p} "
            f"(no {CHALLENGE_MANIFEST} files and no platform manifest)"
        )

    raise ValueError(f"platform not found: {platform}")


def challenge_to_project(entry: dict, base_dir: Optional[Path] = None):
    """把原始挑战 dict 转成 Project（延迟导入避免与 dispatcher 循环依赖）。"""
    from .dispatcher import Project

    work_dir = str(entry.get("challenge_dir") or entry.get("dir") or "")
    if work_dir and not Path(work_dir).is_absolute() and base_dir is not None:
        work_dir = str(base_dir / work_dir)

    return Project(
        challenge_id=str(entry["id"]),
        challenge_dir=work_dir or str(base_dir or Path.cwd()),
        title=str(entry.get("title", "")),
        category=str(entry.get("category", "")).lower(),
        difficulty=str(entry.get("difficulty", "medium")).lower(),
        score=int(entry.get("score") or 0),
        target_host=str(entry.get("target_host", "")),
        target_port=int(entry.get("target_port") or 0),
        description=str(entry.get("description", "")),
        model=str(entry.get("model", "")),
        timebox_override=int(entry.get("timebox") or 0),
    )


def challenge_json_to_project(challenge_json: Path):
    """题目目录下的 ``challenge.json`` → Project（``solve <目录>`` 的入口）。

    ``dir`` 的语义是「相对平台的工作目录」（见模块 docstring），所以 base_dir
    取题目目录的**父目录**：``<platform>/<chal>/challenge.json`` 里写
    ``"dir": "chal"`` 仍解析回 ``<platform>/chal``。

    但条目本身没有 ``dir`` / ``challenge_dir`` 时，工作目录就是题目目录自己
    ——不能让 ``challenge_to_project`` 回退到 base_dir，那会返回**父目录**，
    agent 于是在题目目录之外求解（FLAG / AGENTS.md / solver.log 全写错位置）。
    这里显式补上 ``challenge_dir`` 消除该回退。

    Raises:
        ValueError: challenge.json 不是合法 JSON 对象（由 ``_read_json`` 抛出）。
    """
    data = _read_json(Path(challenge_json))
    parent = Path(challenge_json).parent
    if not (data.get("challenge_dir") or data.get("dir")):
        # 必须注入**绝对**路径：相对值会被 challenge_to_project 再与 base_dir
        # 拼接，形成 platform/platform/... 的双重拼接
        data["challenge_dir"] = str(parent.absolute())
    return challenge_to_project(data, base_dir=parent.parent)


__all__ = [
    "MANIFEST_NAMES",
    "CHALLENGE_MANIFEST",
    "load_challenges",
    "challenge_to_project",
    "challenge_json_to_project",
]
