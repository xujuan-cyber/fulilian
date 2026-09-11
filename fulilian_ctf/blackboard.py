"""黑板架构 — Fact/Intent/Hint + 父子黑板 + tags 信息素（F2-005/006/009）。

对应实施指南 06-P2-黑板架构.md。黑板是 solver 之间的共享状态层（Stigmergy
间接协调）：每个 solver 向黑板发布 Fact、声明 Intent、读取 Hint，不直接通信。

设计要点（与文档偏差处已标注）：
1. 数据模型严格按 06 指南：Fact/Intent/Hint 三原语 + State 枚举。
2. 偏差说明：03-代码设计 曾写 ``tags: dict[str, list[str]]``；06 指南（本
   步权威）与 02-数据与状态机设计 的示例均为 ``{"high_value": "port_80"}``
   单值信息素，故采用 ``dict[str, str]``。
3. 偏差说明：06 指南的 ``to_dict`` 用 ``v.__dict__``，其中 State 是 Enum，
   直接 JSON 序列化会失败；本实现把 state 序列化为字符串值（与
   02-数据与状态机设计 的黑板状态 JSON 示例一致："state": "confirmed"）。
4. 追加扩展：``from_dict`` / ``save_blackboard`` / ``load_blackboard`` 提供
   持久化（Phase 2 验收「黑板正确记录 Fact/Intent/Hint 并持久化」），
   供步骤 07 stopper、步骤 09 多 Agent、F3-006 Coordinator 复用。
5. Append-only：``add_fact`` 对重复 id 抛 ValueError（06 验证方式第 6 条
   「Fact 添加后不可修改」；若同一 Fact 对象重复加入则幂等 no-op）。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from .fsutil import path_lock

try:
    import fcntl  # POSIX 文件锁；Windows 无此模块（见 save_blackboard 降级逻辑）
except ImportError:  # pragma: no cover - Windows only
    fcntl = None


class State(str, Enum):
    """黑板原语状态。"""

    CONFIRMED = "confirmed"   # 已确认
    REFUTED = "refuted"       # 已推翻
    OPEN = "open"             # 待探索
    NEXT = "next"             # 下一步计划


@dataclass
class Fact:
    """一个已确认的、客观的发现。"""

    id: str = ""
    content: str = ""          # 发现内容
    source: str = ""           # 来源（命令/工具输出）
    tags: list = field(default_factory=list)  # 分类标签
    state: State = State.CONFIRMED
    created_at: float = 0.0
    confidence: float = 1.0    # 0.0-1.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        if not self.created_at:
            self.created_at = time.time()
        if not isinstance(self.state, State):
            self.state = State(self.state)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source,
            "tags": list(self.tags or []),
            "state": self.state.value,
            "created_at": self.created_at,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        return cls(
            id=str(d.get("id", "")),
            content=str(d.get("content", "")),
            source=str(d.get("source", "")),
            tags=list(d.get("tags") or []),
            state=State(str(d.get("state", "confirmed"))),
            created_at=float(d.get("created_at", 0.0) or 0.0),
            confidence=float(d.get("confidence", 1.0) or 1.0),
        )


@dataclass
class Intent:
    """一个声明的探索方向。"""

    id: str = ""
    goal: str = ""             # 探索目标
    approach: str = ""         # 攻击方法
    state: State = State.OPEN
    variant_count: int = 0     # 变体尝试次数
    created_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        if not self.created_at:
            self.created_at = time.time()
        if not isinstance(self.state, State):
            self.state = State(self.state)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "approach": self.approach,
            "state": self.state.value,
            "variant_count": self.variant_count,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Intent":
        return cls(
            id=str(d.get("id", "")),
            goal=str(d.get("goal", "")),
            approach=str(d.get("approach", "")),
            state=State(str(d.get("state", "open"))),
            variant_count=int(d.get("variant_count", 0) or 0),
            created_at=float(d.get("created_at", 0.0) or 0.0),
        )


@dataclass
class Hint:
    """人类/协调器注入的判断。"""

    content: str = ""
    source: str = ""           # 来源（用户 / 协调器 / 收割轮）
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Hint":
        return cls(
            content=str(d.get("content", "")),
            source=str(d.get("source", "")),
            created_at=float(d.get("created_at", 0.0) or 0.0),
        )


class Blackboard:
    """黑板 — 共享状态容器。

    支持父子黑板层级（F2-006）：
    - 父黑板（Parent）：跨题共享（全局知识、ATT&CK 索引、死路免疫、信息素）
    - 子黑板（Child）：单题执行状态；写入父黑板可见，读取自动回退父黑板

    Stigmergy 语义：
    - Fact 写透传父黑板（全局发现可见）
    - 死路标记透传父黑板（一个 solver 标记，其他 solver 免疫，F2-009）
    - tags 信息素透传父黑板（跨题高价值路径标记，F2-009）
    - Intent / Hint 仅本黑板（单题探索方向与人工提示）
    """

    def __init__(self, parent: Optional["Blackboard"] = None, challenge_id: str = ""):
        self.facts: dict[str, Fact] = {}
        self.intents: list[Intent] = []
        self.hints: list[Hint] = []
        self.dead_ends: set[str] = set()   # "已证死路" 免疫集
        self.tags: dict[str, str] = {}     # 信息素 key=tag_name, value=tag_value
        self.exclusions: set[str] = set()  # 已证明走不通的路径
        self._listeners: list[Callable[[str, Any], None]] = []  # 事件监听器
        self.parent: Optional[Blackboard] = parent
        self.challenge_id = challenge_id

    # ─── Fact 操作 ─────────────────────────────────────────────────────

    def add_fact(self, fact: Fact) -> None:
        """添加 Fact（append-only：不可覆盖/修改已有 Fact）。"""
        existing = self.facts.get(fact.id)
        if existing is not None:
            if existing is fact:
                return  # 同一对象重复加入 → 幂等 no-op
            # 幂等吞并（P1 修复）：并发场景下多个子黑板会先后向父黑板
            # 透传同 id 的 Fact（各自反序列化出的不同对象、内容相同）。
            # 若一律按 append-only 抛 ValueError，会把无辜的子 solver
            # 打崩——内容一致即视为同一发现，静默跳过；内容不同才是真
            # 冲突（同一 id 被复用），仍然报错暴露。
            if (existing.content or "") == (fact.content or ""):
                return
            raise ValueError(
                f"append-only: fact id '{fact.id}' already exists "
                f"(facts are immutable once added)"
            )
        self.facts[fact.id] = fact
        self._notify("fact_added", fact)
        # 同步到父黑板（全局发现可见）
        if self.parent:
            self.parent.add_fact(fact)

    def get_facts(self, tag: str = None) -> list[Fact]:
        """获取 Fact，可选按 tag 过滤。"""
        if tag:
            return [f for f in self.facts.values() if tag in (f.tags or [])]
        return list(self.facts.values())

    # ─── Intent 操作 ───────────────────────────────────────────────────

    def add_intent(self, intent: Intent) -> None:
        """声明探索方向（单题本地，不透传父黑板）。"""
        self.intents.append(intent)
        self._notify("intent_added", intent)

    def get_open_intents(self) -> list[Intent]:
        """获取待探索的方向。"""
        return [i for i in self.intents if i.state == State.OPEN]

    def mark_intent_state(self, intent_id: str, state: State) -> None:
        """更新 Intent 状态（CONFIRMED/REFUTED/NEXT 等）。"""
        for i in self.intents:
            if i.id == intent_id:
                i.state = state
                return
        raise KeyError(f"intent not found: {intent_id}")

    # ─── 死路操作 ──────────────────────────────────────────────────────

    def mark_dead_end(self, path: str) -> None:
        """标记死路（透传父黑板，其他 solver 免疫，F2-009）。"""
        self.dead_ends.add(path)
        if self.parent:
            self.parent.mark_dead_end(path)

    def is_dead_end(self, path: str) -> bool:
        """检查路径是否已被标记为死路（含父黑板）。"""
        if path in self.dead_ends:
            return True
        if self.parent and path in self.parent.dead_ends:
            return True
        return False

    # ─── Tags 信息素操作 ───────────────────────────────────────────────

    def set_tag(self, key: str, value: str) -> None:
        """设置信息素标记（透传父黑板，跨 solver 可见，F2-009）。"""
        self.tags[key] = value
        if self.parent:
            self.parent.tags[key] = value

    def get_tag(self, key: str) -> Optional[str]:
        """获取信息素标记（本地优先，回退父黑板）。"""
        if key in self.tags:
            return self.tags[key]
        if self.parent and key in self.parent.tags:
            return self.parent.tags[key]
        return None

    # ─── Hint 操作 ─────────────────────────────────────────────────────

    def add_hint(self, hint: Hint) -> None:
        """注入人类/协调器判断（单题本地）。"""
        self.hints.append(hint)
        self._notify("hint_added", hint)

    # ─── 排他路径操作 ─────────────────────────────────────────────────

    def add_exclusion(self, path: str) -> None:
        """声明死路（已证明走不通的路径）。"""
        self.exclusions.add(path)

    def check_excluded(self, path: str) -> bool:
        """检查路径是否已被排除，支持前缀匹配。

        前缀是**裸前缀**：排除 ``port 80`` 也会命中 ``port 8080``，排除
        ``/login`` 也会命中 ``/login-history``。当前 add_exclusion /
        check_excluded 在本包里没有生产调用方（只有定义），所以这个误伤还
        是潜在的；将来接线时若要按「路径段边界」匹配，得先定语义
        （``/login`` 该不该挡 ``/login-history`` 本身就没有共识），
        别直接拿它去挡端口/目录名。
        """
        if path in self.exclusions:
            return True
        for e in self.exclusions:
            if path.startswith(e):
                return True
        return False

    def get_exclusions(self) -> set[str]:
        """返回排他路径集合。"""
        return set(self.exclusions)

    # ─── 事件监听器 ─────────────────────────────────────────────────────

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        """注册事件监听器（callback 签名: (event_type, data)）。"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        """移除监听器。"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, event_type: str, data: Any) -> None:
        """通知所有监听器。监听器中的异常不影响主流程。"""
        for cb in list(self._listeners):
            try:
                cb(event_type, data)
            except Exception:
                pass

    # ─── 序列化 / 反序列化 ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化（JSON-safe：State 输出为字符串值）。"""
        return {
            "challenge_id": self.challenge_id,
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
            "intents": [i.to_dict() for i in self.intents],
            "hints": [h.to_dict() for h in self.hints],
            "dead_ends": sorted(self.dead_ends),
            "tags": dict(self.tags),
            "exclusions": sorted(self.exclusions),
        }

    @classmethod
    def from_dict(cls, d: dict, parent: Optional["Blackboard"] = None) -> "Blackboard":
        """从 to_dict 的输出重建黑板（父黑板由调用方注入）。"""
        board = cls(parent=parent, challenge_id=str(d.get("challenge_id", "")))
        for f in (d.get("facts") or {}).values():
            fact = Fact.from_dict(f)  # 只构造一次：重复构造会白造一个对象
            board.facts[fact.id] = fact
        board.intents = [Intent.from_dict(i) for i in (d.get("intents") or [])]
        board.hints = [Hint.from_dict(h) for h in (d.get("hints") or [])]
        board.dead_ends = set(d.get("dead_ends") or [])
        board.tags = dict(d.get("tags") or {})
        board.exclusions = set(d.get("exclusions") or [])
        return board


# ─── 文件持久化 ──────────────────────────────────────────────────────────

BLACKBOARD_FILENAME = "blackboard.json"


def _write_board(board: Blackboard, path: Path) -> Path:
    """原子写盘（临时文件带 pid + uuid → replace）。

    **不含加锁**：调用方必须已持有 ``path_lock(path)``（见 save_blackboard /
    merge_into_blackboard / update_blackboard）。临时文件名的唯一性保证
    replace 本身的原子性，锁负责的是别让两个写者的「读—改—写」区间交错。
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(
        json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)
    return path


def save_blackboard(board: Blackboard, path: str | Path) -> Path:
    """把黑板持久化为 blackboard.json（原子写：先写临时文件再替换）。

    并发安全（P1 修复）：
    - 临时文件名带 pid + uuid：旧的固定 `*.tmp` 命名下，多 solver 进程
      并发保存同一 blackboard.json 会互相覆盖临时文件，后完成者的
      `replace` 可能把别人写的内容替换进正式文件；
    - 对同一目标路径用 flock 串行化替换动作（fcntl 在 Windows 不可用
      时降级为无锁——临时文件名的唯一性已足以保证 replace 的原子性）。

    ⚠️ 本函数**整体覆盖**目标文件。若目的只是「把自己的发现加进去」，
    必须用 :func:`merge_into_blackboard` / :func:`update_blackboard`——
    覆盖式保存会丢掉调用方 load 之后、save 之前由别人写入的内容。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path_lock(path):
        return _write_board(board, path)


def _merge_boards(target: "Blackboard", extra: "Blackboard") -> None:
    """把 ``extra`` 的发现并入 ``target``（原地）。

    - Fact 走 ``add_fact``：按 id 幂等，同 id 同内容静默跳过；同 id 不同内容
      在磁盘上已有一份，跳过即可（不因一条冲突毁掉整次收尾回写）。
    - Hint 是 list 且 ``add_hint`` 无条件 append，按 content 去重，否则每次
      合并都会把历史 Hint 再堆一遍。
    - Intent 按 id 去重；死路/排他/标签取并集。
    """
    for fact in extra.get_facts():
        try:
            target.add_fact(fact)
        except ValueError:
            continue
    seen = {(h.content or "") for h in target.hints}
    for hint in extra.hints:
        content = hint.content or ""
        if content not in seen:
            target.add_hint(hint)
            seen.add(content)
    known = {i.id for i in target.intents}
    target.intents.extend(i for i in extra.intents if i.id not in known)
    target.dead_ends |= set(extra.dead_ends)
    target.exclusions |= set(extra.exclusions)
    target.tags.update(extra.tags)


def merge_into_blackboard(board: Blackboard, path: str | Path) -> Blackboard:
    """把 ``board`` 的发现并入 ``path`` 上的**最新**磁盘状态并写回。

    整个「读—改—写」在同一把锁内完成，因此与并发的 ``save_blackboard`` /
    ``update_blackboard`` 互斥。收尾回写必须走这里：调用方的黑板往往是运行
    期开始前的快照，直接 ``save_blackboard`` 会抹掉运行期间别的写者
    （MemoryCompressor / HallucinationDetector）落盘的内容。

    Returns:
        实际写入的黑板（磁盘基底 + 并入内容）；文件不存在时即为 ``board``。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path_lock(path):
        try:
            disk = load_blackboard(path)
        except Exception:  # noqa: BLE001 — 磁盘坏了就退回本黑板，至少不丢自己这份
            disk = None
        if disk is None:
            _write_board(board, path)
            return board
        _merge_boards(disk, board)
        _write_board(disk, path)
        return disk


def update_blackboard(
    path: str | Path,
    mutate: Callable[[Blackboard], None],
    *,
    create: bool = True,
) -> Optional[Blackboard]:
    """在锁内对 blackboard.json 做 read-modify-write。

    给「往中心黑板加一条 Hint/Fact」这类写者用：``mutate`` 收到的是**磁盘上
    的最新**黑板，原地修改即可。相比 ``load → add → save``，它把读取也放进
    锁内，因此不会用陈旧快照覆盖并发写者的内容。

    Args:
        mutate: 原地修改回调。
        create: 文件不存在时是否以空白板为基底；为 False 则返回 None 且不写。

    Returns:
        写入后的黑板；``create=False`` 且文件不存在时返回 None。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path_lock(path):
        try:
            disk = load_blackboard(path)
        except Exception:  # noqa: BLE001 — 同 merge_into_blackboard
            disk = None
        if disk is None:
            if not create:
                return None
            disk = Blackboard()
        mutate(disk)
        _write_board(disk, path)
        return disk


def load_blackboard(
    path: str | Path, parent: Optional[Blackboard] = None
) -> Optional[Blackboard]:
    """从 blackboard.json 加载黑板；文件不存在返回 None。"""
    path = Path(path)
    if not path.is_file():
        return None
    return Blackboard.from_dict(
        json.loads(path.read_text(encoding="utf-8")), parent=parent
    )


__all__ = [
    "State",
    "Fact",
    "Intent",
    "Hint",
    "Blackboard",
    "BLACKBOARD_FILENAME",
    "save_blackboard",
    "load_blackboard",
    "merge_into_blackboard",
    "update_blackboard",
]
