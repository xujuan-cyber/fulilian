"""CTFd 提交状态模型：三态/多态语义 + 有界重试策略。

**为什么需要这个模块**

原先的提交路径把 CTFd 响应信封的**顶层** ``success`` 当作"是否答对"
（``ctfd_adapter.py`` 的 ``is_confirmed=lambda r: r.get("success") is True``），
但 CTFd 的顶层 ``success`` 含义是"**这次 API 请求本身是否成功**"——**答错时它
同样是 True**。于是平台判"答错"被记成"已确认"，该错 flag 之后永久命中
``ALREADY_SOLVED``，再也提交不了。

本模块把判定收拢成一条**可单测的纯函数** ``parse_attempt_envelope``，并确立
一条铁律：

    只有明确出现 ``data.status == "incorrect"`` 才判 INCORRECT。
    任何未知 status、结构异常、非 JSON 响应一律归 NOT_ACCEPTED。

即"宁可少惩罚，也不误伤"——因为误判 INCORRECT 会让模型去改本来正确的 flag，
而误判 NOT_ACCEPTED 只是多试一次。

**与 ``submit_guard`` 的分工**

本模块只管"这次提交发生了什么 + 该不该重试"；``submit_guard`` 只管"这个
flag 是不是已经确认过了，不用再打平台"。两者不重叠。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Mapping, Optional

from .env_overrides import (
    ENV_SUBMIT_ATTEMPTS,
    ENV_SUBMIT_BASE_DELAY,
    ENV_SUBMIT_RETRY_AFTER_CAP,
    env_float,
    env_int,
)

# 默认重试策略（env 可覆盖）
DEFAULT_SUBMIT_ATTEMPTS = 4
DEFAULT_SUBMIT_BASE_DELAY = 1.5
DEFAULT_SUBMIT_MAX_DELAY = 30.0
DEFAULT_SUBMIT_RETRY_AFTER_CAP = 300
DEFAULT_SUBMIT_TIMEOUT = 30.0


class SubmitState(str, Enum):
    """一次提交的结果状态。"""

    CORRECT = "correct"              # 平台确认答对
    ALREADY_SOLVED = "already_solved"  # 该题已攻克（多解链/重提）→ 视同成功
    PARTIAL = "partial"              # 平台认为部分正确（某些 CTFd 插件）→ 不是答错
    INCORRECT = "incorrect"          # 平台**明确**判错 → 唯一"确实答错"
    NOT_ACCEPTED = "not_accepted"    # 未受理：限流/5xx/超时/协议异常 → 不记账、不惩罚


@dataclass(frozen=True)
class SubmitOutcome:
    """一次提交（可能含多次 HTTP 尝试）的最终结果。"""

    state: SubmitState
    http_status: int = 0
    message: str = ""
    retry_after: int = 0
    attempts: int = 1
    transient: bool = False
    """失败是否属于**明确可重试的瞬时故障**（限流/服务端错误/网络）。

    只管 NOT_ACCEPTED。它是"要不要再试一次"的唯一依据：``False`` 表示我们
    无法判定或该故障重试也不会变（未知 status / 非 JSON / 4xx 鉴权/参数）。
    对这类情况重试只会把一次误解放大成 4 次并拖慢整个调度。
    """

    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_success(self) -> bool:
        """平台侧已确认攻克（含 already_solved）。"""
        return self.state in (SubmitState.CORRECT, SubmitState.ALREADY_SOLVED)


@dataclass(frozen=True)
class SubmitPolicy:
    """提交重试策略（值来自 env，构造期解析）。"""

    attempts: int = DEFAULT_SUBMIT_ATTEMPTS
    base_delay: float = DEFAULT_SUBMIT_BASE_DELAY
    max_delay: float = DEFAULT_SUBMIT_MAX_DELAY
    retry_after_cap: int = DEFAULT_SUBMIT_RETRY_AFTER_CAP
    timeout: float = DEFAULT_SUBMIT_TIMEOUT


def default_submit_policy() -> SubmitPolicy:
    """生效的提交重试策略（env 覆盖，构造期读取）。"""
    attempts = env_int(ENV_SUBMIT_ATTEMPTS, DEFAULT_SUBMIT_ATTEMPTS, min_value=1)
    base_delay = env_float(ENV_SUBMIT_BASE_DELAY, DEFAULT_SUBMIT_BASE_DELAY, min_value=0.0)
    cap = env_int(ENV_SUBMIT_RETRY_AFTER_CAP, DEFAULT_SUBMIT_RETRY_AFTER_CAP, min_value=0)
    return SubmitPolicy(
        attempts=attempts,
        base_delay=base_delay,
        retry_after_cap=cap,
        max_delay=max(DEFAULT_SUBMIT_MAX_DELAY, base_delay),
    )


# 平台"已处理但被暂时挡住"→ 未受理，退避后可重试
_TRANSIENT_STATUSES = frozenset({"ratelimited", "rate_limited", "too_many_requests", "paused"})
# 平台确认攻克
_SOLVED_STATUSES = frozenset({"already_solved", "solved"})


def parse_attempt_envelope(payload: object) -> SubmitOutcome:
    """把 CTFd ``/api/v1/challenges/attempt`` 的响应信封解析成 ``SubmitOutcome``。

    真实信封（见 ``tests/fulilian_ctf/test_submit_state.py`` 的构造）::

        {"success": True, "data": {"status": "correct"|"incorrect", "message": ...}}

    **铁律**：只有显式 ``data.status == "incorrect"`` 才返回 INCORRECT；
    未知 status / 缺 data / 类型异常一律 NOT_ACCEPTED。
    """
    if not isinstance(payload, Mapping):
        return SubmitOutcome(
            SubmitState.NOT_ACCEPTED, message=f"non-object response: {type(payload).__name__}"
        )

    data = payload.get("data")
    status = ""
    message = ""
    retry_after = 0
    if isinstance(data, Mapping):
        raw_status = data.get("status")
        status = str(raw_status).strip().lower() if raw_status is not None else ""
        raw_message = data.get("message")
        message = str(raw_message) if raw_message is not None else ""
        raw_ra = data.get("retry_after")
        if isinstance(raw_ra, (int, float)) and raw_ra > 0:
            retry_after = int(raw_ra)

    if status == "correct":
        return SubmitOutcome(SubmitState.CORRECT, message=message, raw=dict(payload))
    if status == "incorrect":
        return SubmitOutcome(SubmitState.INCORRECT, message=message, raw=dict(payload))
    if status in _SOLVED_STATUSES:
        return SubmitOutcome(SubmitState.ALREADY_SOLVED, message=message, raw=dict(payload))
    if status == "partial":
        return SubmitOutcome(SubmitState.PARTIAL, message=message, raw=dict(payload))
    if status in _TRANSIENT_STATUSES:
        return SubmitOutcome(
            SubmitState.NOT_ACCEPTED,
            message=message or f"platform status: {status}",
            retry_after=retry_after,
            transient=True,
            raw=dict(payload),
        )

    # 走到这里：未知 status，或信封里压根没有 data.status。
    # 顶层 success=False 且无 status 也是"未受理"（业务层拒绝）。
    if not status:
        top_success = payload.get("success")
        if top_success is False:
            return SubmitOutcome(
                SubmitState.NOT_ACCEPTED,
                message=message or "platform returned success=false without data.status",
                raw=dict(payload),
            )
        return SubmitOutcome(
            SubmitState.NOT_ACCEPTED,
            message=message or "response has no data.status (cannot judge)",
            raw=dict(payload),
        )
    return SubmitOutcome(
        SubmitState.NOT_ACCEPTED,
        message=message or f"unrecognised platform status: {status}",
        retry_after=retry_after,
        raw=dict(payload),
    )


_RETRYABLE_STATUSES = frozenset({408, 425, 429})


def is_retryable_http(status: int) -> bool:
    """该 HTTP 状态码是否值得退避重试。

    429 限流 / 408 超时 / 425 Too Early / 5xx 服务端错误 → 重试。
    其余 4xx（401 鉴权、404 路径、400 参数）重试无意义 → 不重试。
    """
    if status <= 0:  # 网络层失败（连接被拒/超时/DNS），由调用方归零
        return True
    if status in _RETRYABLE_STATUSES:
        return True
    return 500 <= status <= 599


def parse_retry_after(headers: Optional[Mapping[str, str]], *, cap: int) -> int:
    """解析 ``Retry-After`` 头（秒），按 ``cap`` 封顶；缺失/非法/非正整数返回 0。"""
    if not headers:
        return 0
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return 0
    try:
        seconds = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return min(seconds, cap) if cap > 0 else seconds


def retry_delay(attempt_index: int, policy: SubmitPolicy, retry_after: int = 0) -> float:
    """第 ``attempt_index`` 次失败后应等待的秒数（线性退避 + 抖动）。

    ``retry_after`` 优先于退避，并按 ``policy.retry_after_cap`` 封顶；抖动用于
    避免多个 solver 同时撞上限流。
    """
    delay = min(policy.base_delay * (attempt_index + 1), policy.max_delay)
    if retry_after > 0:
        capped = min(retry_after, policy.retry_after_cap) if policy.retry_after_cap > 0 else retry_after
        delay = max(delay, capped)
    return delay + random.uniform(0, 0.5)


def submit_with_policy(
    do_post: Callable[[float], object],
    policy: SubmitPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    parse_headers: Optional[Callable[[object], Mapping[str, str]]] = None,
    status_of: Optional[Callable[[object], int]] = None,
) -> SubmitOutcome:
    """按策略执行提交。

    **重试规则（唯一依据是"是否明确瞬时故障"）**：

    - 传输层可重试（429 / 408 / 425 / 5xx / 网络异常）→ 退避重试；
    - 内容层瞬时（``ratelimited`` / ``paused``）→ 退避重试；
    - 平台给出**明确判定**（correct / incorrect / already_solved / partial）
      → 立即返回，不浪费尝试；
    - 其余（未知 status / 非 JSON / 4xx 鉴权与参数错误）→ 立即返回。
      这类故障重试不会变好，连打 4 次只会拖慢整个调度。

    ``do_post(timeout)`` 应返回一个响应对象，或抛异常表示网络层失败。
    ``parse_headers`` / ``status_of`` 把响应对象适配成 header 映射与状态码
    （默认按 ``requests.Response`` 的形状取值；测试可注入替身）。
    """
    _headers = parse_headers or (lambda resp: getattr(resp, "headers", {}) or {})
    _status = status_of or (lambda resp: int(getattr(resp, "status_code", 0) or 0))

    last = SubmitOutcome(SubmitState.NOT_ACCEPTED, message="no attempt made", attempts=0)
    for i in range(policy.attempts):
        attempt_no = i + 1
        try:
            resp = do_post(policy.timeout)
        except Exception as e:  # noqa: BLE001 — 网络层失败：明确瞬时 → 可重试
            last = SubmitOutcome(
                SubmitState.NOT_ACCEPTED,
                message=f"{type(e).__name__}: {e}",
                attempts=attempt_no,
                transient=True,
            )
        else:
            status = _status(resp)
            if is_retryable_http(status):
                retry_after = parse_retry_after(_headers(resp), cap=policy.retry_after_cap)
                last = SubmitOutcome(
                    SubmitState.NOT_ACCEPTED,
                    http_status=status,
                    retry_after=retry_after,
                    message=(getattr(resp, "text", "") or "")[:200],
                    attempts=attempt_no,
                    transient=True,
                )
            else:
                try:
                    payload = resp.json()
                except Exception as e:  # noqa: BLE001 — 非 JSON 不再误报成"参数非法"
                    return SubmitOutcome(
                        SubmitState.NOT_ACCEPTED,
                        http_status=status,
                        message=f"non-JSON response ({type(e).__name__})",
                        attempts=attempt_no,
                    )
                outcome = replace(parse_attempt_envelope(payload), http_status=status,
                                  attempts=attempt_no)
                # 明确判定 / 不可重试的未受理 → 立即返回
                if outcome.state is not SubmitState.NOT_ACCEPTED or not outcome.transient:
                    return outcome
                last = outcome

        if i < policy.attempts - 1:
            sleep(retry_delay(i, policy, last.retry_after))
    return last


def model_hint(outcome: SubmitOutcome) -> str:
    """把提交结果转成给模型看的一句话。

    **核心目的**：让模型能区分"平台没受理"与"我答错了"。前者不该促使它改
    flag 或换格式重推（那会白烧提交次数、也只是在被限流时加重突发），后者才是。
    """
    msg = (outcome.message or "").strip()
    tail = f"：{msg}" if msg else ""
    if outcome.state is SubmitState.CORRECT:
        return f"提交正确{tail}"
    if outcome.state is SubmitState.ALREADY_SOLVED:
        return f"该题已攻克（already_solved）{tail}"
    if outcome.state is SubmitState.PARTIAL:
        return f"平台判定部分正确（partial）{tail}。补齐缺失部分后可以再试。"
    if outcome.state is SubmitState.INCORRECT:
        return (
            f"平台判定答案错误（incorrect）{tail}。"
            "这是真的答错了——回到分析阶段，不要重推同一个 flag 或只换格式。"
        )
    return (
        f"平台未受理{tail}。"
        f"**这不是答错**：不要改 flag、不要换格式重推；已自动重试 {outcome.attempts} 次。"
        "稍后（或换一个已验证的候选）再试即可。"
    )


__all__ = [
    "DEFAULT_SUBMIT_ATTEMPTS",
    "DEFAULT_SUBMIT_BASE_DELAY",
    "DEFAULT_SUBMIT_MAX_DELAY",
    "DEFAULT_SUBMIT_RETRY_AFTER_CAP",
    "DEFAULT_SUBMIT_TIMEOUT",
    "SubmitOutcome",
    "SubmitPolicy",
    "SubmitState",
    "default_submit_policy",
    "is_retryable_http",
    "model_hint",
    "parse_attempt_envelope",
    "parse_retry_after",
    "retry_delay",
    "submit_with_policy",
]
