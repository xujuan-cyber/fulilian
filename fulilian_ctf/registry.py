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


def load_challenges(platform: str | Path) -> list[dict]:
    """加载平台上的全部挑战（原始 dict 列表）。找不到/格式错抛 ValueError。"""
    p = Path(platform).expanduser()

    if p.is_file():
        return _load_manifest_file(p)

    if p.is_dir():
        # 1) 平台清单
        for name in MANIFEST_NAMES:
            mf = p / name
            if mf.is_file():
                return _load_manifest_file(mf)
        # 2) 平台根目录直接是单道题（challenge.json 在根下）
        root_cf = p / CHALLENGE_MANIFEST
        if root_cf.is_file():
            entry = _read_json(root_cf)
            if "challenges" in entry:
                raise ValueError(
                    f"{root_cf} is a platform manifest, not a single challenge object"
                )
            entry.setdefault("challenge_dir", str(p))
            return _validate_entries([entry], str(root_cf))
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
            return _validate_entries(found, str(p))
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


__all__ = [
    "MANIFEST_NAMES",
    "CHALLENGE_MANIFEST",
    "load_challenges",
    "challenge_to_project",
]
