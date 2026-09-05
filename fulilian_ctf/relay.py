"""三段式续接 — 接力块生成与解析（F2-012 基础）。

时间盒到期/止损时，solver 把当前状态沉淀为接力块（RELAY.md）：
[已达成原语] + [已证死路] + [下一步]。下一轮 solver 重访时解析接力块，
从「下一步」继续，不重复侦察。

完整止损与续接编排（Stopper 4 维 + 多 flag 链临门不弃）在步骤 07 实现，
本模块提供纯文本契约。
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Optional

RELAY_HEADER = "[已达成原语]"
DEAD_END_HEADER = "[已证死路]"
NEXT_HEADER = "[下一步]"

RELAY_SECTIONS = {
    "achieved_primitives": RELAY_HEADER,
    "dead_ends": DEAD_END_HEADER,
    "next_steps": NEXT_HEADER,
}


# P1-3 / A-4：运行时元信息前缀。solver 每次尝试都会往黑板写
# "solver attempt N started" 元 Fact，_write_relay 若不过滤，这些行会
# 进入 RELAY「已达成原语」并被回注黑板，随重试线性膨胀（滚雪球）。
RELAY_META_FACT_PREFIX = "solver attempt "


def is_relay_meta_text(text: str) -> bool:
    """判断接力块条目是否为运行时元信息（不是解题原语）。"""
    t = text or ""
    return t.startswith("solver ran ") or t.startswith(RELAY_META_FACT_PREFIX)


def relay_worthy_fact(fact) -> bool:
    """A-4：Fact 是否可进 RELAY「已达成原语」（dispatcher / solver 共用谓词）。

    过滤 source=="solver" 的元 Fact 与 content 以 "solver attempt " 开头
    的条目；宁窄勿宽——其他一切 Fact（含任意自定义 source）都放行。
    dead_ends 不经过本谓词，永不过滤。
    """
    if getattr(fact, "source", "") == "solver":
        return False
    content = getattr(fact, "content", "") or ""
    return not content.startswith(RELAY_META_FACT_PREFIX)


def atomic_write_text(path: Path, text: str) -> None:
    """tmp + os.replace 原子写（与 blackboard.save_blackboard 同模式）。

    中断时旧文件完好，不会留下截断文件；异常路径允许 .tmp 残留（下次覆盖）。
    tmp 文件名带 pid+线程 id：并发写者各用各的 tmp，避免共享 tmp 被并发
    截断后把半截内容 replace 进正式文件（P1-3 契约 6 的竞态窗口由此消除；
    跨写者仍是 last-writer-wins，无锁语义不变）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(
        f"{path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build_relay(
    achieved_primitives: list[str],
    dead_ends: list[str],
    next_steps: list[str],
) -> str:
    """构建接力块（Markdown 格式）。

    Args:
        achieved_primitives: 已达成的原语列表
        dead_ends: 已证死路列表
        next_steps: 下一步计划列表

    Returns:
        str: 接力块 Markdown 文本
    """
    lines: list[str] = []
    lines.append(RELAY_HEADER)
    lines.extend(f"  - {p}" for p in achieved_primitives)
    lines.append("")

    lines.append(DEAD_END_HEADER)
    lines.extend(f"  - {d}" for d in dead_ends)
    lines.append("")

    lines.append(NEXT_HEADER)
    lines.extend(f"  - {n}" for n in next_steps)
    lines.append("")

    return "\n".join(lines)


def parse_relay(relay_text: str) -> dict:
    """解析接力块，提取已达成原语、已证死路、下一步。

    Returns:
        dict: {"achieved_primitives": list[str], "dead_ends": list[str], "next_steps": list[str]}
    """
    result: dict = {
        "achieved_primitives": [],
        "dead_ends": [],
        "next_steps": [],
    }

    current_section: Optional[str] = None
    for line in (relay_text or "").split("\n"):
        stripped = line.strip()
        if stripped.startswith(RELAY_HEADER):
            current_section = "achieved_primitives"
        elif stripped.startswith(DEAD_END_HEADER):
            current_section = "dead_ends"
        elif stripped.startswith(NEXT_HEADER):
            current_section = "next_steps"
        elif stripped.startswith("- ") and current_section:
            result[current_section].append(stripped[2:])

    return result


def write_relay_file(work_dir: Path, relay_text: str) -> None:
    """将接力块写入 work_dir/RELAY.md（原子写，P1-3）。"""
    atomic_write_text(Path(work_dir) / "RELAY.md", relay_text)


def read_relay_file(work_dir: Path) -> Optional[str]:
    """从 work_dir/RELAY.md 读取接力块；不存在返回 None。"""
    relay_file = Path(work_dir) / "RELAY.md"
    if relay_file.exists():
        return relay_file.read_text(encoding="utf-8", errors="replace")
    return None


__all__ = [
    "RELAY_HEADER",
    "DEAD_END_HEADER",
    "NEXT_HEADER",
    "build_relay",
    "parse_relay",
    "write_relay_file",
    "read_relay_file",
]
