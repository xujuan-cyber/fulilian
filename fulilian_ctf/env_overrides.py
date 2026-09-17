"""CTF 数值常量的环境变量覆盖层。

背景：``fulilian_ctf/`` 里的秒数/条数/阈值原本全是硬编码常量或函数默认参数，
现场想调参只能改代码。本模块提供**统一、永不抛异常**的解析器，让每个数值旋钮
都能用 ``FULILIAN_CTF_*`` 环境变量覆盖，优先级为 **CLI > env > 默认**。

设计约定
--------
1. **永不抛异常**：未设 / 空串 / 非数字 / 越界 → 一律回退默认值。
2. **绝不 import 期绑定**：调用方必须在**构造/调用期**调用解析器，不要把它写进
   默认参数表达式或 dataclass 字段默认值——那会让 env 在 import 时被冻结，
   测试与现场调参都会失效。
3. **默认值以调用方传入的为准**：本模块不 import 任何兄弟模块（避免循环 import），
   各模块在自己常量旁定义薄 resolver，形如::

       def tier_thresholds() -> list[int]:
           return env_int_list(ENV_TIER_THRESHOLDS, TIER_THRESHOLDS, min_value=1)

4. ``min_value`` / ``max_value`` **只作用于 env 解析出的值**；env 未设时原样返回
   ``default``（即使 default 本身越界）。
5. 显式 ``0`` 对多数旋钮表示"未指定"→ 回退默认（与既有 ``x or DEFAULT`` 行为一致）；
   少数旋钮的 ``0`` 是合法哨兵（如 ``FULILIAN_CTF_TIMEBOX`` 的 0 = 按难度自适应），
   这类需传 ``min_value=0`` 并在调用侧用 ``is not None`` 判断。

单例语义提醒
------------
``loop_guard.default_detector()`` 与 ``submit_guard.default_guard()`` 是**每进程只
构造一次**的单例，因此它们的阈值是"每进程读一次 env"。进程启动前设好即可；运行中
改 env 对已构造的单例无效（测试需调 ``reset_default_detector`` / ``reset_default_guard``）。
"""

from __future__ import annotations

import os
from typing import Optional

# ── 通用解析器 ────────────────────────────────────────────────────────────────


def _raw(name: str) -> str:
    """读取并去空白；未设或空串返回空串。"""
    return (os.environ.get(name) or "").strip()


def env_int(
    name: str,
    default: int,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    """解析整型 env；未设/空/非法/越界一律回退 ``default``。"""
    raw = _raw(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if min_value is not None and value < min_value:
        return default
    if max_value is not None and value > max_value:
        return default
    return value


def env_float(
    name: str,
    default: float,
    *,
    min_value: Optional[float] = None,
) -> float:
    """解析浮点 env；未设/空/非法/越界一律回退 ``default``。"""
    raw = _raw(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if min_value is not None and value < min_value:
        return default
    return value


def env_int_list(
    name: str,
    default: "list[int]",
    *,
    min_value: Optional[int] = None,
) -> "list[int]":
    """解析逗号分隔的整型 env（如 ``300,900,1800``）。

    逐条 skip 非法/越界项；去重后升序返回。**至少 1 条合法才生效**，
    否则回退 ``list(default)``（新列表，绝不返回调用方的可变对象）。
    """
    raw = _raw(name)
    if not raw:
        return list(default)
    values = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            value = int(token)
        except (TypeError, ValueError):
            continue
        if min_value is not None and value < min_value:
            continue
        values.append(value)
    if not values:
        return list(default)
    return sorted(set(values))


def env_int_map(
    name: str,
    default: "dict[str, int]",
    *,
    min_value: Optional[int] = None,
) -> "dict[str, int]":
    """解析 ``key:value`` 逗号分隔的整型映射 env（如 ``easy:300,medium:900``）。

    - key 统一 ``strip().lower()``（lookup 侧都按小写查，原样存 ``"HARD"`` 会永不命中）
    - 逐条 skip 非法/越界项
    - **至少 1 条合法才生效**，否则回退 ``dict(default)``
    - 返回**新 dict**，绝不原地修改 ``default``
    """
    resolved = dict(default)
    raw = _raw(name)
    if not raw:
        return resolved
    applied = 0
    for part in raw.split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        key, _, value_text = token.partition(":")
        key = key.strip().lower()
        if not key:
            continue
        try:
            value = int(value_text.strip())
        except (TypeError, ValueError):
            continue
        if min_value is not None and value < min_value:
            continue
        resolved[key] = value
        applied += 1
    if not applied:
        return dict(default)
    return resolved


# ── 环境变量名登记（集中定义，避免各模块散落裸字符串）────────────────────────

ENV_TIER_THRESHOLDS = "FULILIAN_CTF_TIER_THRESHOLDS"
ENV_DIFFICULTY_BUDGETS = "FULILIAN_CTF_DIFFICULTY_BUDGETS"
ENV_TOKEN_BUDGETS = "FULILIAN_CTF_TOKEN_BUDGETS"
ENV_PARTIAL_FLAG_MULTIPLIER = "FULILIAN_CTF_PARTIAL_FLAG_MULTIPLIER"
ENV_MAX_NO_OUTPUT_ROUNDS = "FULILIAN_CTF_MAX_NO_OUTPUT_ROUNDS"
ENV_MAX_VARIANT_FAILURES = "FULILIAN_CTF_MAX_VARIANT_FAILURES"
ENV_LOOP_WINDOW = "FULILIAN_CTF_LOOP_WINDOW"
ENV_LOOP_WARN = "FULILIAN_CTF_LOOP_WARN"
ENV_LOOP_BREAK = "FULILIAN_CTF_LOOP_BREAK"
ENV_SUBMIT_ATTEMPTS = "FULILIAN_CTF_SUBMIT_ATTEMPTS"
ENV_SUBMIT_BASE_DELAY = "FULILIAN_CTF_SUBMIT_BASE_DELAY"
ENV_SUBMIT_RETRY_AFTER_CAP = "FULILIAN_CTF_SUBMIT_RETRY_AFTER_CAP"
ENV_PROBE_TIMEOUT = "FULILIAN_CTF_PROBE_TIMEOUT"
ENV_PROBE_SCAN_TIMEOUT = "FULILIAN_CTF_PROBE_SCAN_TIMEOUT"
ENV_PROBE_CONCURRENCY = "FULILIAN_CTF_PROBE_CONCURRENCY"
ENV_WORKERS = "FULILIAN_CTF_WORKERS"
ENV_MAX_ATTEMPTS = "FULILIAN_CTF_MAX_ATTEMPTS"
ENV_TIMEBOX = "FULILIAN_CTF_TIMEBOX"
ENV_NO_OUTPUT_ROUND_SECONDS = "FULILIAN_CTF_NO_OUTPUT_ROUND_SECONDS"
ENV_ESCALATION_TIMEBOX_MULTIPLIER = "FULILIAN_CTF_ESCALATION_TIMEBOX_MULTIPLIER"


class _Entry:
    """登记表条目（纯文档用途，不参与解析）。"""

    __slots__ = ("env", "target", "default", "unit", "note")

    def __init__(self, env: str, target: str, default: str, unit: str, note: str = ""):
        self.env = env
        self.target = target
        self.default = default
        self.unit = unit
        self.note = note


# (env 名, 生效位置, 默认值, 单位, 备注)
OVERRIDE_REGISTRY = (
    _Entry(ENV_TIER_THRESHOLDS, "timebox 递增档位", "300,900,1800,3600", "秒", "CSV，去重升序"),
    _Entry(ENV_DIFFICULTY_BUDGETS, "timebox 难度首档预算", "easy:300,medium:900,hard:600", "秒", "支持部分覆盖"),
    _Entry(ENV_TOKEN_BUDGETS, "stopper token 分档预算", "easy:200000,medium:1500000,hard:1000000,expert:1500000", "token", "仅显式启用分档时生效"),
    _Entry(ENV_PARTIAL_FLAG_MULTIPLIER, "临门不弃预算放大倍数", "2", "倍", ""),
    _Entry(ENV_MAX_NO_OUTPUT_ROUNDS, "连续无新 Fact 轮数止损", "7", "轮", ""),
    _Entry(ENV_MAX_VARIANT_FAILURES, "同攻击类变体失败止损", "7", "次", ""),
    _Entry(ENV_LOOP_WINDOW, "循环检测滑动窗口", "12", "次调用", "每进程读一次（单例）"),
    _Entry(ENV_LOOP_WARN, "循环检测 warn 阈值", "3", "次", "每进程读一次（单例）"),
    _Entry(ENV_LOOP_BREAK, "循环检测 break 阈值", "5", "次", "须 >= warn，否则整组回退默认"),
    _Entry(ENV_SUBMIT_ATTEMPTS, "提交总尝试次数", "4", "次", "仅对「未受理」重试，INCORRECT 立即返回"),
    _Entry(ENV_SUBMIT_BASE_DELAY, "提交重试线性退避基数", "1.5", "秒", "带 0~0.5s 抖动"),
    _Entry(ENV_SUBMIT_RETRY_AFTER_CAP, "Retry-After 封顶", "300", "秒", "0 = 不封顶"),
    _Entry(ENV_PROBE_TIMEOUT, "探针总超时", "60", "秒", "socket 层有效上限 10 秒"),
    _Entry(ENV_PROBE_SCAN_TIMEOUT, "兜底端口扫描超时", "5.0", "秒", ""),
    _Entry(ENV_PROBE_CONCURRENCY, "并发探活题数", "4", "题", ""),
    _Entry(ENV_WORKERS, "并行 solver 进程数", "3", "个", "CLI --workers 优先"),
    _Entry(ENV_MAX_ATTEMPTS, "单题最大尝试次数", "5", "次", "CLI --max-attempts 优先"),
    _Entry(ENV_TIMEBOX, "单档时间盒覆盖", "0", "秒", "0 = 按难度自适应"),
    _Entry(ENV_NO_OUTPUT_ROUND_SECONDS, "一轮无产出折算秒数", "60", "秒", ""),
    _Entry(ENV_ESCALATION_TIMEBOX_MULTIPLIER, "收割升级时间盒延长倍率", "1.5", "倍", ""),
)


def describe_overrides() -> str:
    """渲染登记表（自查/文档用）。"""
    lines = ["env 变量 | 生效位置 | 默认 | 单位 | 备注", "---|---|---|---|---"]
    for entry in OVERRIDE_REGISTRY:
        lines.append(
            f"{entry.env} | {entry.target} | {entry.default} | {entry.unit} | {entry.note}"
        )
    return "\n".join(lines)


__all__ = [
    "ENV_DIFFICULTY_BUDGETS",
    "ENV_ESCALATION_TIMEBOX_MULTIPLIER",
    "ENV_LOOP_BREAK",
    "ENV_LOOP_WARN",
    "ENV_LOOP_WINDOW",
    "ENV_MAX_ATTEMPTS",
    "ENV_MAX_NO_OUTPUT_ROUNDS",
    "ENV_MAX_VARIANT_FAILURES",
    "ENV_NO_OUTPUT_ROUND_SECONDS",
    "ENV_PARTIAL_FLAG_MULTIPLIER",
    "ENV_PROBE_CONCURRENCY",
    "ENV_PROBE_SCAN_TIMEOUT",
    "ENV_PROBE_TIMEOUT",
    "ENV_SUBMIT_ATTEMPTS",
    "ENV_SUBMIT_BASE_DELAY",
    "ENV_SUBMIT_RETRY_AFTER_CAP",
    "ENV_TIER_THRESHOLDS",
    "ENV_TIMEBOX",
    "ENV_TOKEN_BUDGETS",
    "ENV_WORKERS",
    "OVERRIDE_REGISTRY",
    "describe_overrides",
    "env_float",
    "env_int",
    "env_int_list",
    "env_int_map",
]
