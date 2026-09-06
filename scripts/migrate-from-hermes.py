#!/usr/bin/env python3
"""从 ~/.hermes 向 ~/.fulilian 的一次性技能/状态迁移（幂等，可重复执行）。

背景：Fulilian 运行时已统一读取 ~/.fulilian（config v39），本脚本只补齐
历史遗留的目录缺口（2026-09-06 审计发现）：
  1. skills 目录 5 个未迁移技能
  2. ~/.hermes-web-ui/ 独立状态目录

安全约束：
- 只从 ~/.hermes / ~/.hermes-web-ui 读取；绝不写入、修改或删除源目录。
- 幂等：目标已存在的条目默认跳过（--force 则覆盖），因此重跑无副作用。
- 无 ~/.hermes 时直接成功退出（全新机器可安全执行，用于零依赖验证）。

用法：
  python scripts/migrate-from-hermes.py            # 迁移缺失项
  python scripts/migrate-from-hermes.py --force    # 覆盖已存在项
  python scripts/migrate-from-hermes.py --dry-run  # 只打印计划
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

FULILIAN_HOME = Path.home() / ".fulilian"
HERMES_HOME = Path.home() / ".hermes"
HERMES_WEB_UI = Path.home() / ".hermes-web-ui"

# 审计确认的 skills 缺口清单（新机器上不存在 ~/.hermes 时为空集，跳过）
MISSING_SKILLS = [
    "computer-use",
    "dogfood",
    "serving-llms-vllm",
    "solve-challenge",
    "yuanbao",
]


def _copytree_idempotent(src: Path, dst: Path, force: bool, dry: bool) -> str:
    """目录级幂等复制。返回动作描述。"""
    if not src.is_dir():
        return f"SKIP (source missing): {src}"
    if dst.exists():
        if not force:
            return f"SKIP (exists): {dst}"
        if dry:
            return f"WOULD REPLACE: {dst}"
        shutil.rmtree(dst)
    if dry:
        return f"WOULD COPY: {src} -> {dst}"
    shutil.copytree(src, dst)
    return f"COPY: {src} -> {dst}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="覆盖已存在的目标")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划")
    args = parser.parse_args()

    actions: list[str] = []

    if not HERMES_HOME.exists():
        print(f"no {HERMES_HOME} — nothing to migrate (fresh machine: OK)")
    else:
        for skill in MISSING_SKILLS:
            actions.append(_copytree_idempotent(
                HERMES_HOME / "skills" / skill,
                FULILIAN_HOME / "skills" / skill,
                args.force, args.dry_run,
            ))

    # web-ui 状态目录：整体复制（db 文件名保留原名以兼容读方，见改造方案阶段 1）
    actions.append(_copytree_idempotent(
        HERMES_WEB_UI, FULILIAN_HOME / "web-ui", args.force, args.dry_run,
    ))

    for line in actions:
        print(line)
    if args.dry_run:
        return 0

    copied = sum(1 for a in actions if a.startswith(("COPY:", "REPL")))
    print(f"\ndone: {copied} item(s) migrated, "
          f"{sum(1 for a in actions if a.startswith('SKIP'))} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
