"""三段式续接 — 接力块生成与解析（F2-012 基础）。

时间盒到期/止损时，solver 把当前状态沉淀为接力块（RELAY.md）：
[已达成原语] + [已证死路] + [下一步]。下一轮 solver 重访时解析接力块，
从「下一步」继续，不重复侦察。

完整止损与续接编排（Stopper 4 维 + 多 flag 链临门不弃）在步骤 07 实现，
本模块提供纯文本契约。

v2 结构化协议（向后兼容）：
- 新增 ``RelayMessage`` / ``RelayBlock`` dataclass + JSON 序列化
- 新格式写 ``relay_block.json``，旧版 ``RELAY.md`` 同步写入
- 旧版函数 ``build_relay`` / ``parse_relay`` / ``write_relay_file`` / ``read_relay_file``
  保持不动
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .fsutil import atomic_write_text as _fsutil_atomic_write_text

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

SOLVER_META_SOURCE = "solver"


def is_relay_meta_text(text: str) -> bool:
    """判断接力块条目是否为运行时元信息（不是解题原语）。"""
    t = text or ""
    return t.startswith("solver ran ") or t.startswith(RELAY_META_FACT_PREFIX)


def is_solver_meta_fact(fact) -> bool:
    """Fact 是否为 solver 运行时元信息（**内容口径**，不是解题原语）。

    「别把元信息当发现」全仓曾有三份内容口径：本模块用
    ``"solver attempt "``/``"solver ran "`` 两个前缀、multi_agent 共享记忆
    发布与 racer 子黑板合并用 ``content.startswith("solver ")``。后者顺带
    把「solver X」这类真发现也一并丢掉（今天没有生产者，但口径本身就是错的），
    统一到本谓词：只认那两个已知前缀，其余一切内容都当发现。

    **本谓词只看内容，不看 source** —— 这一点与 ``is_relay_meta_fact`` 不同，
    是刻意的，别再「统一」掉：共享记忆与子黑板合并要的正是 solver 自己发现
    的事实，按 ``source == "solver"`` 一刀切会把「new finding from A」这类
    发现一起丢掉（实测：test_merge_all_boards_dedupes 与
    test_multi_agent_solved_flag_survives_hallucination_check 立即失败）。
    """
    return is_relay_meta_text(getattr(fact, "content", "") or "")


def is_relay_meta_fact(fact) -> bool:
    """RELAY 口径：是否不该进「已达成原语」列表。

    比 ``is_solver_meta_fact`` 多一条 ``source == "solver"`` —— RELAY 是
    跨尝试续接的原语清单，solver 的自述一旦进去就会被回注黑板、随重试
    线性膨胀（滚雪球），所以整个 source 类别都挡掉，而不只是带前缀的那些。
    dead_ends 不经过本谓词，永不过滤。
    """
    if getattr(fact, "source", "") == SOLVER_META_SOURCE:
        return True
    return is_solver_meta_fact(fact)


def relay_worthy_fact(fact) -> bool:
    """A-4：Fact 是否可进 RELAY「已达成原语」（dispatcher / solver 共用谓词）。

    宁窄勿宽——除 solver 自述外一切 Fact（含任意自定义 source）都放行。
    """
    return not is_relay_meta_fact(fact)


def atomic_write_text(path: Path, text: str) -> None:
    """tmp + os.replace 原子写。

    实现统一到 ``fsutil.atomic_write_text``（本模块曾自持一份等价实现，两处
    tmp 命名/返回值漂移没有收益）。保留本名只为兼容既有导入；新代码请直接用
    fsutil 的实现。``lock=False``：relay 的写者是「单写者 + 多读者」形态，
    加 ``<name>.lock`` 只会往工作目录里多留一个锁文件，不改变 last-writer-wins
    语义（写者之间的串行化靠调用方）。
    """
    _fsutil_atomic_write_text(path, text, lock=False)


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


# ═══════════════════════════════════════════════════════════════════════════
# v2 结构化通信协议（向后兼容）
# ═══════════════════════════════════════════════════════════════════════════

RELAY_BLOCK_FILENAME = "relay_block.json"
PROTOCOL_VERSION = "2.0"


class MessageType(str, Enum):
    """接力消息类型枚举。"""
    ACHIEVED_PRIMITIVE = "achieved_primitive"
    DEAD_END = "dead_end"
    NEXT_STEP = "next_step"
    TASK_DELEGATION = "task_delegation"
    TASK_RESULT = "task_result"
    STATUS_UPDATE = "status_update"
    ERROR_REPORT = "error_report"


class Severity(str, Enum):
    """消息严重级别。"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class RelayMessage:
    """结构化接力消息。

    Attributes:
        msg_id: 消息唯一 ID
        msg_type: 消息类型
        source_agent: 来源 agent 标识
        target_agent: 目标 agent 标识（可选，空表示广播）
        content: 消息内容
        metadata: 元数据（可选附加信息）
        severity: 严重级别
        timestamp: 时间戳
        parent_msg_id: 父消息 ID（回复/关联用）
        protocol_version: 协议版本
    """
    msg_id: str = ""
    msg_type: MessageType = MessageType.STATUS_UPDATE
    source_agent: str = ""
    target_agent: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.INFO
    timestamp: float = 0.0
    parent_msg_id: str = ""
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.msg_id:
            self.msg_id = str(uuid.uuid4())[:8]
        if not self.timestamp:
            self.timestamp = time.time()
        if isinstance(self.msg_type, str):
            self.msg_type = MessageType(self.msg_type)
        if isinstance(self.severity, str):
            self.severity = Severity(self.severity)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "content": self.content,
            "metadata": self.metadata,
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "parent_msg_id": self.parent_msg_id,
            "protocol_version": self.protocol_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "RelayMessage":
        return cls(
            msg_id=str(d.get("msg_id", "")),
            msg_type=MessageType(d.get("msg_type", "status_update")),
            source_agent=str(d.get("source_agent", "")),
            target_agent=str(d.get("target_agent", "")),
            content=str(d.get("content", "")),
            metadata=dict(d.get("metadata", {}) or {}),
            severity=Severity(d.get("severity", "info")),
            timestamp=float(d.get("timestamp", 0.0)),
            parent_msg_id=str(d.get("parent_msg_id", "")),
            protocol_version=str(d.get("protocol_version", PROTOCOL_VERSION)),
        )


@dataclass
class RelayBlock:
    """结构化接力块（v2 协议）。

    Attributes:
        session_id: 会话 ID
        round_number: 轮次
        messages: 消息列表
        achieved_primitives: 已达成原语列表（兼容旧版）
        dead_ends: 已证死路列表（兼容旧版）
        next_steps: 下一步计划列表（兼容旧版）
        confidence: 整体置信度（0.0-1.0）
        created_at: 创建时间戳
    """
    session_id: str = ""
    round_number: int = 0
    messages: list[RelayMessage] = field(default_factory=list)
    achieved_primitives: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    confidence: float = 1.0
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()

    def add_message(self, msg: RelayMessage) -> None:
        """添加消息并同步更新兼容字段。"""
        self.messages.append(msg)
        if msg.msg_type == MessageType.ACHIEVED_PRIMITIVE:
            if msg.content not in self.achieved_primitives:
                self.achieved_primitives.append(msg.content)
        elif msg.msg_type == MessageType.DEAD_END:
            if msg.content not in self.dead_ends:
                self.dead_ends.append(msg.content)
        elif msg.msg_type == MessageType.NEXT_STEP:
            if msg.content not in self.next_steps:
                self.next_steps.append(msg.content)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "round_number": self.round_number,
            "messages": [m.to_dict() for m in self.messages],
            "achieved_primitives": list(self.achieved_primitives),
            "dead_ends": list(self.dead_ends),
            "next_steps": list(self.next_steps),
            "confidence": self.confidence,
            "created_at": self.created_at,
            "protocol_version": PROTOCOL_VERSION,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "RelayBlock":
        return cls(
            session_id=str(d.get("session_id", "")),
            round_number=int(d.get("round_number", 0)),
            messages=[RelayMessage.from_dict(m) for m in d.get("messages", [])],
            achieved_primitives=list(d.get("achieved_primitives", [])),
            dead_ends=list(d.get("dead_ends", [])),
            next_steps=list(d.get("next_steps", [])),
            confidence=float(d.get("confidence", 1.0)),
            created_at=float(d.get("created_at", 0.0)),
        )


# ── 便捷构造器 ────────────────────────────────────────────────────────────


def make_achieved_message(
    source_agent: str,
    content: str,
    metadata: Optional[dict] = None,
) -> RelayMessage:
    """创建已达成原语消息。"""
    return RelayMessage(
        msg_type=MessageType.ACHIEVED_PRIMITIVE,
        source_agent=source_agent,
        content=content,
        metadata=metadata or {},
    )


def make_dead_end_message(
    source_agent: str,
    content: str,
    severity: Severity = Severity.WARNING,
    metadata: Optional[dict] = None,
) -> RelayMessage:
    """创建已证死路消息。"""
    return RelayMessage(
        msg_type=MessageType.DEAD_END,
        source_agent=source_agent,
        content=content,
        severity=severity,
        metadata=metadata or {},
    )


def make_next_step_message(
    source_agent: str,
    content: str,
    metadata: Optional[dict] = None,
) -> RelayMessage:
    """创建下一步消息。"""
    return RelayMessage(
        msg_type=MessageType.NEXT_STEP,
        source_agent=source_agent,
        content=content,
        metadata=metadata or {},
    )


def make_task_delegation(
    source_agent: str,
    target_agent: str,
    task_description: str,
    metadata: Optional[dict] = None,
) -> RelayMessage:
    """创建任务委派消息。"""
    return RelayMessage(
        msg_type=MessageType.TASK_DELEGATION,
        source_agent=source_agent,
        target_agent=target_agent,
        content=task_description,
        metadata=metadata or {},
    )


def make_task_result(
    source_agent: str,
    task_description: str,
    success: bool,
    result_summary: str = "",
    metadata: Optional[dict] = None,
) -> RelayMessage:
    """创建任务结果消息。"""
    meta = dict(metadata or {})
    meta["success"] = success
    if result_summary:
        meta["summary"] = result_summary
    return RelayMessage(
        msg_type=MessageType.TASK_RESULT,
        source_agent=source_agent,
        content=task_description,
        metadata=meta,
    )


def make_error_report(
    source_agent: str,
    error_message: str,
    severity: Severity = Severity.ERROR,
    metadata: Optional[dict] = None,
) -> RelayMessage:
    """创建错误报告消息。"""
    return RelayMessage(
        msg_type=MessageType.ERROR_REPORT,
        source_agent=source_agent,
        content=error_message,
        severity=severity,
        metadata=metadata or {},
    )


# ── 读写操作 ──────────────────────────────────────────────────────────────


def write_relay_block(work_dir: Path, block: RelayBlock) -> None:
    """写入结构化接力块（JSON），同时同步写入旧版 RELAY.md。

    Args:
        work_dir: 工作目录
        block: RelayBlock 实例
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 写入 JSON 格式（原子写：接力块是跨进程/跨轮次交接点，读者可能在
    # 任意时刻读同一个文件 —— 普通 write_text 的 truncate 窗口会被读到空文件）
    json_path = work_dir / RELAY_BLOCK_FILENAME
    atomic_write_text(json_path, block.to_json())

    # 同步写入旧版 RELAY.md（向后兼容）
    relay_md = build_relay(
        achieved_primitives=block.achieved_primitives,
        dead_ends=block.dead_ends,
        next_steps=block.next_steps,
    )
    write_relay_file(work_dir, relay_md)


def read_relay_block(work_dir: Path) -> Optional[RelayBlock]:
    """读取结构化接力块。

    优先读取 JSON 格式。若 JSON 不存在，尝试从旧版 RELAY.md 兼容解析。

    Args:
        work_dir: 工作目录

    Returns:
        RelayBlock | None: 接力块，不存在返回 None
    """
    work_dir = Path(work_dir)
    json_path = work_dir / RELAY_BLOCK_FILENAME

    if json_path.is_file():   # is_file：同名目录不该让 read_text 抛 IsADirectoryError
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(
                    f"relay block 顶层应为对象，实为 {type(data).__name__}"
                )
            return RelayBlock.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError):
            # 「结构合法但形状不对」也必须降级：顶层是列表/字符串/数字、或
            # messages 不是列表时，from_dict 抛的是 AttributeError/TypeError
            # （实测：'[]' → AttributeError、'{"messages": "x"}' → AttributeError、
            # '{"achieved_primitives": 5}' → TypeError）。契约是「坏了就回落到
            # RELAY.md / None」，不该把解析细节漏给调用方（dispatcher 轮次循环）。
            pass

    # 兼容旧版 RELAY.md
    relay_text = read_relay_file(work_dir)
    if relay_text:
        parsed = parse_relay(relay_text)
        return RelayBlock(
            achieved_primitives=parsed.get("achieved_primitives", []),
            dead_ends=parsed.get("dead_ends", []),
            next_steps=parsed.get("next_steps", []),
        )

    return None


__all__ = [
    # 旧版
    "RELAY_HEADER",
    "DEAD_END_HEADER",
    "NEXT_HEADER",
    "build_relay",
    "parse_relay",
    "write_relay_file",
    "read_relay_file",
    "is_relay_meta_text",
    "is_solver_meta_fact",
    "is_relay_meta_fact",
    "relay_worthy_fact",
    # v2 结构化协议
    "RELAY_BLOCK_FILENAME",
    "PROTOCOL_VERSION",
    "MessageType",
    "Severity",
    "RelayMessage",
    "RelayBlock",
    "make_achieved_message",
    "make_dead_end_message",
    "make_next_step_message",
    "make_task_delegation",
    "make_task_result",
    "make_error_report",
    "write_relay_block",
    "read_relay_block",
]
