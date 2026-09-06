"""Tests for the proactive-prune rearm lockout fix (#101889 port).

The rearm gate is measured on message bodies only, so a provider-billed
``prompt_tokens`` reading (system prompt + tool schemas included) can sit
ABOVE ``threshold_tokens`` while the message-only estimate sits below the
rearm mark — the prune then no-ops forever with no log and the session grows
until the provider hard-rejects. The fix: bypass the rearm short-circuit on
the billed basis, warn once per distinct no-op reason while over threshold,
and release the dedup key on every rearm reset.
"""

from types import SimpleNamespace

from agent.context_compressor import ContextCompressor


def _compressor(**kwargs) -> ContextCompressor:
    from unittest.mock import patch

    params = dict(
        model="test/model",
        threshold_percent=0.85,
        protect_first_n=1,
        protect_last_n=2,
        quiet_mode=True,
        proactive_prune_tokens=1000,
        proactive_prune_min_result_chars=100,
        proactive_prune_min_reclaim_tokens=10,
    )
    params.update(kwargs)
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=100000
    ):
        return ContextCompressor(**params)


def _msgs() -> list:
    big = "x" * 2000
    return [
        {"role": "user", "content": "solve the challenge"},
        {"role": "assistant", "content": "starting recon"},
        {"role": "user", "content": "go on"},
        {"role": "tool", "tool_call_id": "t1", "content": big},
        {"role": "tool", "tool_call_id": "t2", "content": big + "y"},
        {"role": "assistant", "content": "enumerating"},
        {"role": "user", "content": "latest ask"},
    ]


def test_over_threshold_bypasses_rearm_lockout():
    comp = _compressor()
    comp.threshold_tokens = 5000
    comp._proactive_prune_rearm_tokens = 999_999  # parks the message-only gate
    msgs = _msgs()

    out, pruned = comp.prune_tool_results_only(msgs, current_tokens=6000)

    # Billed basis says over threshold: the rearm mark must not lock pruning out.
    assert out is not msgs
    assert pruned > 0
    assert comp._proactive_prune_rearm_tokens > 0


def test_under_threshold_hysteresis_stays_silent():
    comp = _compressor()
    comp.threshold_tokens = 50000
    comp._proactive_prune_rearm_tokens = 999_999
    msgs = _msgs()

    out, pruned = comp.prune_tool_results_only(msgs, current_tokens=6000)

    # Below threshold a declined prune is ordinary hysteresis: input unchanged.
    assert out is msgs
    assert pruned == 0


def test_dedup_key_released_on_commit():
    comp = _compressor()
    comp.threshold_tokens = 5000
    comp._proactive_prune_rearm_tokens = 999_999

    comp.prune_tool_results_only(_msgs(), current_tokens=6000)

    assert comp._last_reclaim_block_warn is None


def test_no_op_warns_once_over_threshold(caplog):
    comp = _compressor()
    comp.threshold_tokens = 5000
    # Eligible-region contents too small to prune -> nothing_eligible no-op.
    msgs = [
        {"role": "user", "content": "tiny task"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "tool_call_id": "t1", "content": "short"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "latest"},
    ]

    with caplog.at_level("WARNING"):
        out1, n1 = comp.prune_tool_results_only(msgs, current_tokens=6000)
        out2, n2 = comp.prune_tool_results_only(msgs, current_tokens=6000)

    assert out1 is msgs and n1 == 0
    assert out2 is msgs and n2 == 0
    warnings = [r for r in caplog.records if "reclamation did not run" in r.message]
    assert len(warnings) == 1  # deduped across identical no-op states


def test_no_op_silent_below_threshold(caplog):
    comp = _compressor()
    comp.threshold_tokens = 50000
    msgs = [
        {"role": "user", "content": "tiny task"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "tool_call_id": "t1", "content": "short"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "latest"},
    ]

    with caplog.at_level("WARNING"):
        comp.prune_tool_results_only(msgs, current_tokens=6000)

    assert not [r for r in caplog.records if "reclamation did not run" in r.message]


def test_reset_releases_dedup_key():
    comp = _compressor()
    comp._proactive_prune_rearm_tokens = 123
    comp._last_reclaim_block_warn = ("prune:nothing_eligible", 123)

    comp.on_session_reset()

    assert comp._proactive_prune_rearm_tokens == 0
    assert comp._last_reclaim_block_warn is None


def test_billed_basis_helper():
    comp = _compressor()
    comp.threshold_tokens = 5000
    assert comp._billed_basis_over_threshold(6000) is True
    assert comp._billed_basis_over_threshold(4000) is False
    assert comp._billed_basis_over_threshold(None) is False
    comp.threshold_tokens = 0
    assert comp._billed_basis_over_threshold(6000) is False


def test_finish_reason_extraction_shapes():
    from agent.context_compressor import _response_finish_reason

    obj = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x"), finish_reason="Length")]
    )
    assert _response_finish_reason(obj) == "length"
    as_dict = {"choices": [{"finish_reason": "LENGTH", "message": {"content": "x"}}]}
    assert _response_finish_reason(as_dict) == "length"
    assert _response_finish_reason(SimpleNamespace(choices=[])) == ""
    assert _response_finish_reason(None) == ""
    assert _response_finish_reason({"choices": [{}]}) == ""
