"""``fulilian_ctf.submit_state`` 测试：三态判定 + 有界重试策略。

**核心不变量（本文件的主要价值）**：只有平台**显式**给出
``data.status == "incorrect"`` 才判"答错"。任何未知 status、缺 ``data``、
非 JSON、结构异常一律归"未受理"。

这条不变量是防误判的最后一道墙：误判 INCORRECT 会让模型去改本来就正确的
flag（原 bug 的形态）；误判 NOT_ACCEPTED 只是多试一次。所以宁可偏保守。
"""

from __future__ import annotations

import pytest

from fulilian_ctf import submit_state as ss


# ── parse_attempt_envelope：正向 ────────────────────────────────────────


def _envelope(status, message="", success=True, retry_after=None):
    data = {"status": status}
    if message:
        data["message"] = message
    if retry_after is not None:
        data["retry_after"] = retry_after
    return {"success": success, "data": data}


def test_correct():
    out = ss.parse_attempt_envelope(_envelope("correct", "nice"))
    assert out.state is ss.SubmitState.CORRECT
    assert out.is_success is True
    assert out.message == "nice"


def test_incorrect_is_the_only_source_of_wrong():
    out = ss.parse_attempt_envelope(_envelope("incorrect", "nope"))
    assert out.state is ss.SubmitState.INCORRECT
    assert out.is_success is False


@pytest.mark.parametrize("status", ["already_solved", "solved", "ALREADY_SOLVED"])
def test_already_solved(status):
    out = ss.parse_attempt_envelope(_envelope(status))
    assert out.state is ss.SubmitState.ALREADY_SOLVED
    assert out.is_success is True


def test_partial_is_not_wrong():
    out = ss.parse_attempt_envelope(_envelope("partial", "missing part 2"))
    assert out.state is ss.SubmitState.PARTIAL
    assert out.is_success is False


@pytest.mark.parametrize(
    "status", ["ratelimited", "rate_limited", "too_many_requests", "paused", "RATELIMITED"]
)
def test_transient_statuses_are_not_accepted(status):
    out = ss.parse_attempt_envelope(_envelope(status))
    assert out.state is ss.SubmitState.NOT_ACCEPTED


def test_transient_retry_after_is_carried():
    out = ss.parse_attempt_envelope(_envelope("ratelimited", retry_after=42))
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.retry_after == 42


# ── parse_attempt_envelope：铁律（绝不误判 INCORRECT）───────────────────


@pytest.mark.parametrize(
    "payload",
    [
        _envelope("some_new_status_v9"),          # 未知 status
        _envelope(""),                            # 空 status
        {"success": True},                        # 缺 data
        {"success": False},                       # 顶层 success=False 且无 status
        {"success": True, "data": {}},            # data 里无 status
        {"success": True, "data": "not-a-dict"},  # data 类型异常
        {"success": True, "data": None},
        "a string",                               # payload 非对象
        None,
        123,
        [],
    ],
)
def test_never_incorrect_for_unrecognised_payloads(payload):
    """铁律：未知/畸形一律 NOT_ACCEPTED，绝不判 INCORRECT。"""
    out = ss.parse_attempt_envelope(payload)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.state is not ss.SubmitState.INCORRECT


def test_unknown_status_keeps_platform_message():
    out = ss.parse_attempt_envelope(_envelope("weird", "some platform text"))
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert "some platform text" in out.message


def test_status_case_and_whitespace_tolerated():
    out = ss.parse_attempt_envelope({"success": True, "data": {"status": "  Correct  "}})
    assert out.state is ss.SubmitState.CORRECT


# ── is_retryable_http ───────────────────────────────────────────────────


@pytest.mark.parametrize("status", [429, 408, 425, 500, 502, 503, 504, 0])
def test_retryable_statuses(status):
    assert ss.is_retryable_http(status) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_retryable_client_errors(status):
    assert ss.is_retryable_http(status) is False


# ── parse_retry_after ───────────────────────────────────────────────────


def test_retry_after_basic():
    assert ss.parse_retry_after({"Retry-After": "7"}, cap=300) == 7
    assert ss.parse_retry_after({"retry-after": "7"}, cap=300) == 7


def test_retry_after_capped():
    assert ss.parse_retry_after({"Retry-After": "99999"}, cap=300) == 300


def test_retry_after_cap_zero_means_uncapped():
    assert ss.parse_retry_after({"Retry-After": "99999"}, cap=0) == 99999


@pytest.mark.parametrize(
    "headers", [None, {}, {"Retry-After": ""}, {"Retry-After": "abc"}, {"Retry-After": "-5"},
                {"Retry-After": "0"}]
)
def test_retry_after_invalid_returns_zero(headers):
    assert ss.parse_retry_after(headers, cap=300) == 0


def test_retry_after_float_string_truncated():
    assert ss.parse_retry_after({"Retry-After": "2.9"}, cap=300) == 2


# ── retry_delay ─────────────────────────────────────────────────────────


def test_retry_delay_grows_linearly_with_jitter():
    pol = ss.SubmitPolicy(attempts=4, base_delay=1.0, max_delay=30.0)
    for i in range(3):
        d = ss.retry_delay(i, pol)
        assert (i + 1) * 1.0 <= d <= (i + 1) * 1.0 + 0.5


def test_retry_delay_capped_at_max_delay():
    pol = ss.SubmitPolicy(attempts=10, base_delay=10.0, max_delay=15.0)
    assert ss.retry_delay(9, pol) <= 15.5


def test_retry_delay_honours_retry_after():
    pol = ss.SubmitPolicy(attempts=4, base_delay=1.0, max_delay=30.0, retry_after_cap=300)
    assert ss.retry_delay(0, pol, retry_after=20) >= 20


def test_retry_delay_retry_after_respects_cap():
    pol = ss.SubmitPolicy(attempts=4, base_delay=1.0, max_delay=30.0, retry_after_cap=5)
    assert ss.retry_delay(0, pol, retry_after=9999) <= 5.5


# ── default_submit_policy（env 覆盖）─────────────────────────────────────


def test_policy_defaults(monkeypatch):
    for name in (ss.ENV_SUBMIT_ATTEMPTS, ss.ENV_SUBMIT_BASE_DELAY, ss.ENV_SUBMIT_RETRY_AFTER_CAP):
        monkeypatch.delenv(name, raising=False)
    pol = ss.default_submit_policy()
    assert pol.attempts == 4
    assert pol.base_delay == 1.5
    assert pol.retry_after_cap == 300


def test_policy_env_override(monkeypatch):
    monkeypatch.setenv(ss.ENV_SUBMIT_ATTEMPTS, "2")
    monkeypatch.setenv(ss.ENV_SUBMIT_BASE_DELAY, "0.25")
    monkeypatch.setenv(ss.ENV_SUBMIT_RETRY_AFTER_CAP, "10")
    pol = ss.default_submit_policy()
    assert (pol.attempts, pol.base_delay, pol.retry_after_cap) == (2, 0.25, 10)


def test_policy_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(ss.ENV_SUBMIT_ATTEMPTS, "0")
    monkeypatch.setenv(ss.ENV_SUBMIT_BASE_DELAY, "-1")
    monkeypatch.setenv(ss.ENV_SUBMIT_RETRY_AFTER_CAP, "abc")
    pol = ss.default_submit_policy()
    assert (pol.attempts, pol.base_delay, pol.retry_after_cap) == (4, 1.5, 300)


# ── submit_with_policy ──────────────────────────────────────────────────


class _Resp:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def _run(responses, *, attempts=4, sleeper=None):
    """按脚本返回响应（或抛异常）驱动 submit_with_policy。"""
    queue = list(responses)
    calls = {"n": 0}

    def do_post(timeout):
        calls["n"] += 1
        item = queue[min(calls["n"] - 1, len(queue) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    slept: list[float] = []
    pol = ss.SubmitPolicy(attempts=attempts, base_delay=0.0, max_delay=0.0)
    out = ss.submit_with_policy(do_post, pol, sleep=slept.append)
    return out, calls["n"], slept


def test_incorrect_returns_immediately_without_retrying():
    out, n, slept = _run([_Resp(200, _envelope("incorrect"))])
    assert out.state is ss.SubmitState.INCORRECT
    assert n == 1
    assert slept == []          # 明确判错 → 不浪费尝试


@pytest.mark.parametrize(
    "payload",
    [_envelope("unknown_v9"), {"success": True}, {"success": True, "data": {}}],
)
def test_unrecognised_payload_is_not_retried(payload):
    """未知/畸形内容不重试——重试同样不会解析出判定，只会拖慢调度。"""
    out, n, _ = _run([_Resp(200, payload)], attempts=3)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.transient is False
    assert n == 1


def test_content_level_ratelimit_is_retried():
    """CTFd 可以 200 + status=ratelimited —— 这是内容层瞬时故障，必须重试。"""
    out, n, slept = _run([_Resp(200, _envelope("ratelimited"))], attempts=3)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.transient is True
    assert n == 3
    assert len(slept) == 2


def test_content_level_ratelimit_recovers():
    out, n, _ = _run(
        [_Resp(200, _envelope("ratelimited")), _Resp(200, _envelope("correct"))], attempts=4
    )
    assert out.state is ss.SubmitState.CORRECT
    assert n == 2


def test_429_is_retried_with_retry_after():
    out, n, slept = _run(
        [_Resp(429, None, text="too many", headers={"Retry-After": "3"})], attempts=2
    )
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.http_status == 429
    assert n == 2
    assert out.retry_after == 3
    assert slept and slept[0] >= 3


def test_5xx_is_retried():
    out, n, _ = _run([_Resp(503, None, text="overloaded")], attempts=3)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.http_status == 503
    assert n == 3


def test_network_error_is_retried_and_reported():
    out, n, _ = _run([ConnectionError("connection refused")], attempts=2)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.transient is True
    assert "ConnectionError" in out.message
    assert n == 2


def test_non_json_200_is_not_accepted_not_argument_error():
    """非 JSON 的 200 不得被误报成"参数非法"（原实现会被 ValueError 分支吞掉）。"""
    out, n, _ = _run([_Resp(200, None, text="<html>gateway</html>")], attempts=2)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert "non-JSON" in out.message
    assert n == 1


def test_401_is_not_retried():
    """鉴权失败重试无意义 → 单次返回未受理。"""
    out, n, _ = _run([_Resp(401, None, text="unauthorized")], attempts=4)
    assert out.state is ss.SubmitState.NOT_ACCEPTED
    assert out.http_status == 401
    assert n == 1


def test_recovery_after_transient_failure():
    out, n, _ = _run([_Resp(429), _Resp(200, _envelope("correct"))], attempts=4)
    assert out.state is ss.SubmitState.CORRECT
    assert n == 2


def test_attempts_recorded_on_success_and_failure():
    ok, n, _ = _run([_Resp(200, _envelope("correct"))])
    assert ok.attempts == 1 and n == 1
    bad, n2, _ = _run([_Resp(500)], attempts=3)
    assert bad.attempts == 3 and n2 == 3


# ── model_hint：必须区分「未受理」与「答错」────────────────────────────


def test_hint_distinguishes_not_accepted_from_wrong():
    not_accepted = ss.SubmitOutcome(ss.SubmitState.NOT_ACCEPTED, message="429", attempts=4)
    wrong = ss.SubmitOutcome(ss.SubmitState.INCORRECT, message="Incorrect")
    h1, h2 = ss.model_hint(not_accepted), ss.model_hint(wrong)
    assert "不是答错" in h1 and "答错" not in h1.replace("不是答错", "")
    assert "答错" in h2
    assert h1 != h2


def test_hint_mentions_attempt_count_when_not_accepted():
    out = ss.SubmitOutcome(ss.SubmitState.NOT_ACCEPTED, message="timeout", attempts=3)
    assert "3" in ss.model_hint(out)


def test_hint_for_success_states():
    assert "正确" in ss.model_hint(ss.SubmitOutcome(ss.SubmitState.CORRECT))
    assert "已攻克" in ss.model_hint(ss.SubmitOutcome(ss.SubmitState.ALREADY_SOLVED))
    assert "部分正确" in ss.model_hint(ss.SubmitOutcome(ss.SubmitState.PARTIAL))
