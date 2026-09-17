"""细粒度循环检测（P0-2，吸收自 verialabs/ctf-agent loop_detect.py）。

与 ``stopper.py`` 的关系（互补，不重叠）：
- ``stopper.count_variant_failures`` 是**跨轮、语义级**——同一攻击类的变体
  失败次数，由黑板统计，用于止损决策；
- 本模块是**同轮、机械级**——(tool_name, args) 签名在滑动窗口内的重复次数，
  抓得住"同一条命令原样重放"这种语义层看不见的死循环。

参考实现（ctf-agent ``backend/loop_detect.py``，50 行）的参数：
- ``window=12``：滑动窗口长度（deque(maxlen)）；
- ``warn_threshold=3``：同签名出现 ≥3 次 → "warn"（提示，不拦截）；
- ``break_threshold=5``：同签名出现 ≥5 次 → "break"（应强制打断）；
- 签名 = ``f"{tool_name}:{args 序列化[:500]}"``，dict 用 sort_keys 保证稳定。

fulilian 侧接线：``fulilian_ctf/hooks/__init__.py`` 的 pre_tool_call 钩子对
**所有工具**喂入调用签名（terminal 的危险命令检查不变）；break 时复用上游
block 语义（``{"action": "block", "message": ...}``），warn 时经 post_tool_call
注入 ``{"context": ...}`` 提示。racer 每个 solver 是独立子进程，进程内单例
天然按 solver 隔离。

开关：环境变量 ``FULILIAN_LOOP_GUARD=0`` 整体禁用。检查失败一律 fail-open
（放行），避免断题。

窗口/阈值优先级 **显式构造参数 > env > 默认**，env 名为
``FULILIAN_CTF_LOOP_WINDOW`` / ``FULILIAN_CTF_LOOP_WARN`` / ``FULILIAN_CTF_LOOP_BREAK``
（见 ``env_overrides``）。注意 ``default_detector()`` 是**每进程只构造一次**的单例，
所以这三个值实际是"每进程读一次 env"——进程启动前设好即可，运行中改 env 对
已构造的单例无效（测试请调 ``reset_default_detector``）。
"""

from __future__ import annotations

import collections
import json
import os
import threading
from typing import Optional

from .env_overrides import ENV_LOOP_BREAK, ENV_LOOP_WARN, ENV_LOOP_WINDOW, env_int

ENV_LOOP_GUARD = "FULILIAN_LOOP_GUARD"

WARN = "warn"
BREAK = "break"

# 默认阈值（运行期请用 _resolve_thresholds / LoopDetector() 取生效值）
DEFAULT_LOOP_WINDOW = 12
DEFAULT_LOOP_WARN = 3
DEFAULT_LOOP_BREAK = 5


def _resolve_thresholds(
    window: Optional[int],
    warn_threshold: Optional[int],
    break_threshold: Optional[int],
) -> tuple[int, int, int]:
    """解析 (window, warn, break)：显式 > env > 默认。

    ``break_threshold < warn_threshold`` 时把 warn/break **整组回退默认**：
    ``check()`` 先判 break 再判 warn，break 更小会让 warn 永不触发，
    从而静默丢失"提醒但放行"这一级。显式传入的非法组合同样被归一化。
    """
    resolved_window = (
        int(window) if window is not None else env_int(ENV_LOOP_WINDOW, DEFAULT_LOOP_WINDOW, min_value=1)
    )
    resolved_warn = (
        int(warn_threshold)
        if warn_threshold is not None
        else env_int(ENV_LOOP_WARN, DEFAULT_LOOP_WARN, min_value=1)
    )
    resolved_break = (
        int(break_threshold)
        if break_threshold is not None
        else env_int(ENV_LOOP_BREAK, DEFAULT_LOOP_BREAK, min_value=1)
    )
    if resolved_break < resolved_warn:
        resolved_warn, resolved_break = DEFAULT_LOOP_WARN, DEFAULT_LOOP_BREAK
    return resolved_window, resolved_warn, resolved_break


def _signature(tool_name: str, args) -> str:
    """(tool_name, args) → 稳定签名。dict 序列化 sort_keys；截断到 500 字符。"""
    if args is None or args == {} or args == "":
        return str(tool_name)
    if isinstance(args, dict):
        try:
            raw = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            raw = str(args)
    else:
        raw = str(args)
    return f"{tool_name}:{raw[:500]}"


class LoopDetector:
    """滑动窗口内的重复工具调用检测（非线程共享时无需锁，但 hooks 可能
    来自不同线程，统一加锁，成本可忽略）。"""

    def __init__(
        self,
        window: Optional[int] = None,
        warn_threshold: Optional[int] = None,
        break_threshold: Optional[int] = None,
    ):
        window, warn_threshold, break_threshold = _resolve_thresholds(
            window, warn_threshold, break_threshold
        )
        self.window = int(window)
        self.warn_threshold = int(warn_threshold)
        self.break_threshold = int(break_threshold)
        self._recent: collections.deque = collections.deque(maxlen=self.window)
        self._lock = threading.Lock()

    def _enabled(self) -> bool:
        return os.environ.get(ENV_LOOP_GUARD, "").strip() != "0"

    def check(self, tool_name: str, args=None) -> Optional[str]:
        """记录一次调用并判断循环状态。

        Returns:
            None   — 无循环
            "warn" — 接近阈值（提示但不拦截）
            "break" — 超过阈值（应强制打断）
        """
        if not self._enabled():
            return None
        sig = _signature(tool_name, args)
        with self._lock:
            self._recent.append(sig)
            count = sum(1 for s in self._recent if s == sig)
        if count >= self.break_threshold:
            return BREAK
        if count >= self.warn_threshold:
            return WARN
        return None

    def describe(self, tool_name: str, args=None) -> str:
        """生成给模型的可执行反馈（break 时随 block 消息返回）。"""
        return (
            f"loop-guard: the identical call {tool_name} has repeated "
            f"{self.break_threshold}+ times in the last {self.window} calls. "
            "Do NOT repeat it. Change approach: try a different tool or a "
            "materially different argument, or report NO_PATH / blocked."
        )

    def reset(self) -> None:
        with self._lock:
            self._recent.clear()


_default: Optional[LoopDetector] = None
_default_lock = threading.Lock()


def default_detector() -> LoopDetector:
    """进程内单例（racer 每个 solver 独立子进程，天然按 solver 隔离）。"""
    global _default
    with _default_lock:
        if _default is None:
            _default = LoopDetector()
        return _default


def reset_default_detector(detector: Optional[LoopDetector] = None) -> None:
    """重置单例（测试用；生产代码不要调用）。"""
    global _default
    with _default_lock:
        _default = detector if detector is not None else LoopDetector()


__all__ = [
    "BREAK",
    "DEFAULT_LOOP_BREAK",
    "DEFAULT_LOOP_WARN",
    "DEFAULT_LOOP_WINDOW",
    "ENV_LOOP_GUARD",
    "LoopDetector",
    "WARN",
    "default_detector",
    "reset_default_detector",
]
