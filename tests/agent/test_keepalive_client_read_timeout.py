"""Regression guardrail: the keepalive http client must have a FINITE read
timeout.

Root cause this pins (CTF-holdout incident 2026-09-11, plan §10 item 1 —
"CTF API 路径无读超时"): ``build_keepalive_http_client`` used to construct
its httpx client with ``read=None`` (unbounded) "for SSE streaming
endpoints".  But the OpenAI SDK *adopts* ``http_client.timeout`` whenever a
caller passes an ``http_client`` without an explicit ``timeout``
(``openai._base_client.SyncAPIClient.__init__``), so that ``read=None``
silently became the default socket read budget for every OpenAI-wire call
site that does not pass a per-request timeout — auxiliary calls, async
compression clients, future call sites.  A provider that accepts a request
and then goes silent (observed: ESTAB socket, unacked Send-Q, stalled at
API call #7) then hangs the agent forever instead of surfacing a retryable
timeout.

The main conversation loop is NOT the affected path — it passes its own
per-request ``httpx.Timeout`` (120 s read, stale-stream watchdog on top).
This test pins the *default layer*: no request anywhere may inherit an
unbounded read from the client construction itself.

``FULILIAN_CLIENT_READ_TIMEOUT`` is the escape hatch; ``<= 0`` restores the
old unbounded-read behavior.
"""
import httpx
import pytest

from agent.process_bootstrap import (
    _client_default_read_timeout,
    build_keepalive_http_client,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FULILIAN_CLIENT_READ_TIMEOUT", raising=False)


def test_helper_default_is_finite_600s():
    assert _client_default_read_timeout() == 600.0


def test_helper_env_override():
    import os

    os.environ["FULILIAN_CLIENT_READ_TIMEOUT"] = "30"
    try:
        assert _client_default_read_timeout() == 30.0
    finally:
        del os.environ["FULILIAN_CLIENT_READ_TIMEOUT"]


def test_helper_env_zero_restores_unbounded_read():
    import os

    os.environ["FULILIAN_CLIENT_READ_TIMEOUT"] = "0"
    try:
        assert _client_default_read_timeout() is None
    finally:
        del os.environ["FULILIAN_CLIENT_READ_TIMEOUT"]


def test_helper_env_garbage_falls_back_to_default():
    import os

    os.environ["FULILIAN_CLIENT_READ_TIMEOUT"] = "not-a-number"
    try:
        assert _client_default_read_timeout() == 600.0
    finally:
        del os.environ["FULILIAN_CLIENT_READ_TIMEOUT"]


def test_sync_keepalive_client_read_timeout_is_finite():
    client = build_keepalive_http_client("https://api.example.com/v1")
    try:
        assert isinstance(client, httpx.Client)
        assert client.timeout.read == 600.0
        # connect/write/pool improvements are untouched.
        assert client.timeout.connect == 15.0
        assert client.timeout.write == 15.0
    finally:
        client.close()


def test_async_keepalive_client_read_timeout_is_finite():
    client = build_keepalive_http_client(
        "https://api.example.com/v1", async_mode=True
    )
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert client.timeout.read == 600.0
    finally:
        client.aclose()


def _make_agent():
    from run_agent import AIAgent

    return AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model="test/model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )


def test_openai_sdk_adopts_finite_read_from_keepalive_client():
    """End-to-end adoption pin, at the real SDK layer.

    A primary OpenAI client built through ``create_openai_client`` with NO
    explicit ``timeout`` in client_kwargs (i.e. no
    ``providers.<id>.request_timeout_seconds`` configured) must end up with
    a finite socket read budget.  This is exactly the construction chain
    ``agent_init`` → ``_create_openai_client`` → ``create_openai_client``
    uses on the CTF solve path when the provider has no configured timeout.
    """
    from agent.agent_runtime_helpers import create_openai_client

    agent = _make_agent()
    client = create_openai_client(
        agent,
        {"api_key": "test-key-value", "base_url": "https://openrouter.ai/api/v1"},
        reason="test_read_timeout_adoption",
        shared=False,
    )
    try:
        assert client.timeout.read == 600.0
    finally:
        client.close()
