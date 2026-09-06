"""Tests for frozen-segment compaction mode (``compression.segment_mode``).

In segment mode each compression summarizes ONLY the turns added since the
previous one; the produced block is stamped ``FROZEN_SEGMENT_KEY`` and is
never merged, rewritten, or dropped by later compressions. The trigger
threshold is evaluated on the new-content basis (live prompt tokens minus
the frozen-segment weight), so frozen blocks never consume the budget.
"""

from unittest.mock import MagicMock, patch

from agent.context_compressor import (
    COMPRESSED_SUMMARY_METADATA_KEY,
    ContextCompressor,
    FROZEN_SEGMENT_KEY,
    MICRO_COMPACT_MARKER_KEY,
    _SUMMARY_END_MARKER,
)


def _compressor(**kwargs) -> ContextCompressor:
    params = dict(
        model="test/model",
        threshold_percent=0.85,
        protect_first_n=1,
        protect_last_n=1,
        # Tiny tail budget: the default 0.20×window would put the whole
        # toy transcript inside the protected tail and skip compression.
        summary_target_ratio=0.0001,
        quiet_mode=True,
        segment_mode=True,
    )
    params.update(kwargs)
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=100000
    ):
        return ContextCompressor(**params)


def _response(content: str, finish_reason: str = "stop"):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    if finish_reason is not None:
        mock_response.choices[0].finish_reason = finish_reason
    return mock_response


def _fresh_turns(tag: str) -> list:
    turns = [
        {"role": "user", "content": f"investigate target {tag}"},
        {"role": "assistant", "content": f"scanned {tag}, found services"},
        {"role": "tool", "tool_call_id": f"t1-{tag}", "content": f"scan output {tag}"},
        {"role": "assistant", "content": f"exploited {tag} via known CVE"},
        {"role": "user", "content": f"pivot deeper into {tag}"},
        {"role": "assistant", "content": f"escalated privileges on {tag}"},
        {"role": "tool", "tool_call_id": f"t2-{tag}", "content": f"shell session {tag}"},
        {"role": "assistant", "content": f"captured artifacts from {tag}"},
        {"role": "user", "content": f"next step for {tag}?"},
    ]
    return turns


def _summary_messages(messages: list) -> list:
    return [
        msg
        for msg in messages
        if isinstance(msg, dict)
        and msg.get(COMPRESSED_SUMMARY_METADATA_KEY)
    ]


def test_second_compression_prompt_excludes_first_segment():
    """The merge template must never run in segment mode: the second
    compression's summarizer prompt covers only the NEW turns."""
    compressor = _compressor()

    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("SEGMENT-ONE narrative"),
    ):
        after_first = compressor.compress(_fresh_turns("alpha"))

    seg_one = [m for m in after_first if m.get(FROZEN_SEGMENT_KEY)]
    assert len(seg_one) == 1
    assert "SEGMENT-ONE narrative" in str(seg_one[0]["content"])

    grew = after_first + _fresh_turns("beta")
    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("SEGMENT-TWO narrative"),
    ) as mock_call:
        after_second = compressor.compress(grew)

    prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    assert "PREVIOUS SUMMARY" not in prompt
    assert "SEGMENT-ONE narrative" not in prompt
    assert "SEGMENT-TWO narrative" not in prompt
    # The beta turns were the summarizer's input; alpha rows were not.
    assert "beta" in prompt
    assert "scanned alpha" not in prompt
    assert after_second is not grew


def test_frozen_segment_carried_verbatim_across_compactions():
    """Old segments ride the output byte-for-byte; the new segment is
    stamped frozen as well."""
    compressor = _compressor()
    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("SEGMENT-ONE narrative"),
    ):
        after_first = compressor.compress(_fresh_turns("alpha"))
    seg_one = next(m for m in after_first if m.get(FROZEN_SEGMENT_KEY))
    original_content = seg_one["content"]

    grew = after_first + _fresh_turns("beta")
    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("SEGMENT-TWO narrative"),
    ):
        after_second = compressor.compress(grew)

    segments = [m for m in after_second if m.get(FROZEN_SEGMENT_KEY)]
    assert len(segments) == 2
    carried = next(m for m in segments if "SEGMENT-ONE" in str(m["content"]))
    assert carried["content"] == original_content
    assert carried["role"] == seg_one["role"]
    assert any("SEGMENT-TWO" in str(m["content"]) for m in segments)


def test_trigger_uses_new_content_basis():
    """Frozen segments must not consume the trigger budget: a live reading
    above threshold with enough frozen weight stays under the trigger."""
    compressor = _compressor()
    compressor.threshold_tokens = 10000
    compressor._last_frozen_tokens_estimate = 60000

    # live 65K - frozen 60K = 5K new content -> below threshold.
    fired, reason = compressor.should_compress_info(prompt_tokens=65000)
    assert fired is False
    assert reason is None

    # live 70.5K - frozen 60K = 10.5K new content -> over threshold.
    fired, _ = compressor.should_compress_info(prompt_tokens=70500)
    assert fired is True

    # Legacy mode ignores the frozen estimate entirely.
    legacy = _compressor(segment_mode=False)
    legacy.threshold_tokens = 10000
    legacy._last_frozen_tokens_estimate = 60000
    fired, _ = legacy.should_compress_info(prompt_tokens=65000)
    assert fired is True


def test_trigger_basis_clamps_and_legacy_passthrough():
    compressor = _compressor()
    compressor._last_frozen_tokens_estimate = 500
    assert compressor._trigger_basis(300) == 0
    assert compressor._trigger_basis(None) is None
    legacy = _compressor(segment_mode=False)
    legacy._last_frozen_tokens_estimate = 500
    assert legacy._trigger_basis(700) == 700


def test_config_construction_and_attribute_injection():
    """The constructor accepts segment_mode; agent_init injects the config
    keys by attribute when the engine exposes them (same pattern as
    micro_compact)."""
    compressor = _compressor()
    assert compressor.segment_mode is True
    assert compressor.frozen_ceiling_ratio == 0.6

    # Simulate the agent_init attribute-injection path.
    compressor.frozen_ceiling_ratio = 0.9
    assert compressor.frozen_ceiling_ratio == 0.9


def test_micro_rehydrate_never_tags_frozen_block():
    """A frozen batch block may seed the micro rolling summary in memory,
    but must never gain MICRO_COMPACT_MARKER_KEY (which would make it
    supersede/defrag-eligible, i.e. mutable)."""
    compressor = _compressor()
    block = {
        "role": "user",
        "content": "frozen segment body unique-xyz",
        COMPRESSED_SUMMARY_METADATA_KEY: True,
        FROZEN_SEGMENT_KEY: True,
    }
    messages = [
        {"role": "user", "content": "task"},
        block,
        {"role": "assistant", "content": "new work"},
        {"role": "user", "content": "tail request"},
    ]
    compressor._micro_compact_rolling_summary = ""
    cursor = compressor._resolve_compact_cursor(messages, head_end=1, tail_start=4)

    assert cursor == 2  # past the frozen block
    assert "frozen segment body unique-xyz" in compressor._micro_compact_rolling_summary
    assert not block.get(MICRO_COMPACT_MARKER_KEY)


def test_emergency_consolidation_merges_all_segments():
    """Past the ceiling fraction, ONE pass folds every frozen body into a
    single new segment and carries nothing."""
    compressor = _compressor()
    compressor.frozen_ceiling_ratio = 0.0001  # ceiling ≈ 10 tokens on 100K window

    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("SEGMENT-ONE narrative"),
    ):
        after_first = compressor.compress(_fresh_turns("alpha"))

    grew = after_first + _fresh_turns("beta")
    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("CONSOLIDATED segment"),
    ) as mock_call:
        after_second = compressor.compress(grew)

    prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    assert "SEGMENT-ONE narrative" in prompt
    segments = [m for m in after_second if m.get(FROZEN_SEGMENT_KEY)]
    assert len(segments) == 1
    assert "CONSOLIDATED segment" in str(segments[0]["content"])


def test_fallback_segment_does_not_swallow_frozen_blocks():
    """The deterministic fallback must not embed a previous-summary snapshot
    in segment mode (frozen blocks already ride the transcript)."""
    compressor = _compressor()
    compressor._previous_summary = "LEGACY rolling narrative"

    body = compressor._build_static_fallback_summary(_fresh_turns("alpha"))

    assert "## Previous Summary Snapshot" not in body
    assert "LEGACY rolling narrative" not in body


def test_summary_end_marker_still_applied_per_segment():
    """Each standalone segment keeps the end-marker envelope that stops weak
    models from reading past-compaction quotes as fresh input."""
    compressor = _compressor()
    with patch(
        "agent.context_compressor.call_llm",
        return_value=_response("SEGMENT-ONE narrative"),
    ):
        after_first = compressor.compress(_fresh_turns("alpha"))

    seg = next(m for m in after_first if m.get(FROZEN_SEGMENT_KEY))
    assert _SUMMARY_END_MARKER in str(seg["content"])
