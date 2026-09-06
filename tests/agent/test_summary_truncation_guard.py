"""Tests for the finish_reason="length" truncation guards on summary paths.

A summary stopped by the output token cap is PARTIAL text. Persisting it as
the compaction checkpoint (main path) or absorbing it into the rolling
summary (micro-compaction path) silently truncates the conversation's memory
and compounds the loss across compactions. Both paths must treat a length
stop as a failure (ported from hermes-agent, pi#7048).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.context_compressor import ContextCompressor, _TRUNCATED_SUMMARY_MARKER


def _length_response() -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="partial summary text..."),
            )
        ]
    )


def _stop_response(content: str = "complete summary") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=content),
            )
        ]
    )


def _compressor() -> ContextCompressor:
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=100000
    ):
        return ContextCompressor(
            model="test/model",
            threshold_percent=0.85,
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )


def _turns() -> list:
    return [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "working on it"},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    ]


def test_main_summary_rejects_truncated_response(caplog):
    compressor = _compressor()
    with patch(
        "agent.context_compressor.call_llm", return_value=_length_response()
    ):
        # The guard raises inside _generate_summary; its own failure handler
        # logs the cause and pauses summary attempts instead of checkpointing
        # the partial text. Either way NO summary is produced.
        summary = compressor._generate_summary(_turns())

    assert summary is None
    assert any(
        _TRUNCATED_SUMMARY_MARKER in (r.getMessage() or "") for r in caplog.records
    )


def test_main_summary_accepts_complete_response():
    compressor = _compressor()
    with patch(
        "agent.context_compressor.call_llm", return_value=_stop_response()
    ):
        summary = compressor._generate_summary(_turns())

    assert summary is not None
    assert "complete summary" in summary


def test_micro_summarize_discards_truncated_response():
    compressor = _compressor()
    with patch(
        "agent.auxiliary_client.call_llm", return_value=_length_response()
    ):
        assert compressor._micro_summarize_one("exchange text") is None


def test_micro_summarize_accepts_complete_response():
    compressor = _compressor()
    with patch(
        "agent.auxiliary_client.call_llm", return_value=_stop_response("merged")
    ):
        assert compressor._micro_summarize_one("exchange text") == "merged"
