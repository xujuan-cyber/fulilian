"""提交闸门：只防「已确认的 flag 重新提交」。

**职责收窄说明（2026-09-17）**

本模块原先承担两个机制：① 第 n 次错提交后的**递增冷却**；② 同 flag 精确
**去重**（``DUPLICATE`` 短路）。两者已整体移除，原因：

- **冷却从未正确生效**。它依赖"平台判错"能正确记账，而判定的极性是错的
  （读 CTFd 信封顶层 ``success``，答错时它同样为 True）→ ``wrong`` 计数几乎
  永不增长 → 冷却档位从未被真实触发过，那些数值（0/30/120/300/600）也从未
  被验证。
- **去重会锁死错误状态**。同一 bug 让"答错"被记成"已确认"，于是错 flag 之后
  永久命中 ``ALREADY_SOLVED``，再也提交不了。去重本身不是问题，"被污染的去重
  输入"才是——而修复输入之后，去重的价值（省一次平台请求）已不足以抵偿它
  引入的状态耦合。

防滥用（限流/突发提交 → WAF IP 封禁）改由 ``submit_state.py`` 承担：区分
"未受理"与"答错"，只对未受理做带抖动的有界退避重试并尊重 ``Retry-After``。

**保留的唯一职责**：平台已确认攻克的 flag 不再重复提交。这不是防滥用，而是
避免把一个已知成功的结果再打一次平台（会得到 ``already_solved``，纯噪音）。

**用法**（各调用点显式写，不经通用 helper——极性 bug 正是"把不透明 lambda 塞进
通用 helper"造成的，去掉那层抽象即去掉同一类错误的容身之处）::

    ok, reason = guard.check(key, flag)
    if not ok:
        return reject_message(reason)
    outcome = do_submit()
    if outcome.is_success:          # 只由平台的显式判定驱动
        guard.mark_confirmed(key, flag)

开关：``FULILIAN_SUBMIT_GUARD=0`` 整体禁用（``check`` 恒放行），默认开启。
线程安全（``threading.Lock``）。``default_guard()`` 是**每进程构造一次**的单例。
"""

from __future__ import annotations

import os
import threading
from typing import Optional

ENV_SUBMIT_GUARD = "FULILIAN_SUBMIT_GUARD"


def normalize_flag(flag: str) -> str:
    """提交前归一化：去首尾空白。flag 本体大小写敏感，不做其他变换。"""
    return (flag or "").strip()


class SubmitGuard:
    """按 key（``work_dir`` 或 ``challenge_id``）隔离的"已确认 flag"闸门。

    两条提交路径的 key 天然不同（本地声明式用 ``work_dir``，CTFd 用
    ``challenge_id``），因此共用同一个单例不会互相干扰。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> 已确认（平台/校验门判定通过）的 flag 集合
        self._confirmed: dict[str, set[str]] = {}

    def _enabled(self) -> bool:
        return os.environ.get(ENV_SUBMIT_GUARD, "").strip() != "0"

    def check(self, key: str, flag: str) -> tuple[bool, str]:
        """提交前检查。返回 ``(放行, 拒绝原因)``。

        唯一拒绝原因：该 flag 已被确认过（``ALREADY_SOLVED``）。关闭开关时恒放行。
        """
        flag = normalize_flag(flag)
        if not self._enabled():
            return True, ""
        with self._lock:
            if flag and flag in self._confirmed.get(str(key), set()):
                return False, f"ALREADY_SOLVED — flag already confirmed for {key}: {flag}"
        return True, ""

    def mark_confirmed(self, key: str, flag: str) -> None:
        """记录一个**平台已确认**的 flag。

        只应由显式成功判定（``SubmitOutcome.is_success`` / 本地校验门
        ``CONFIRMED``）驱动；调用方不得把"网络异常""未受理""未知响应"传进来。
        """
        flag = normalize_flag(flag)
        if not flag:
            return
        with self._lock:
            self._confirmed.setdefault(str(key), set()).add(flag)

    def stats(self, key: str) -> dict:
        """只读快照（测试/诊断用）。"""
        with self._lock:
            return {"confirmed": len(self._confirmed.get(str(key), set()))}

    def reset(self) -> None:
        """清空全部状态（测试用）。"""
        with self._lock:
            self._confirmed.clear()


_default: Optional[SubmitGuard] = None
_default_lock = threading.Lock()


def default_guard() -> SubmitGuard:
    """进程内单例（两条提交路径各自经此取用）。"""
    global _default
    with _default_lock:
        if _default is None:
            _default = SubmitGuard()
        return _default


def reset_default_guard(guard: Optional[SubmitGuard] = None) -> None:
    """重置单例（测试用；生产代码不要调用）。"""
    global _default
    with _default_lock:
        _default = guard if guard is not None else SubmitGuard()


__all__ = [
    "ENV_SUBMIT_GUARD",
    "SubmitGuard",
    "default_guard",
    "normalize_flag",
    "reset_default_guard",
]
