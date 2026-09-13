"""P0.1 prune-side persistence: pruned tool results must leave a pointer.

The tool side of P0.1 (truncation → spill → path in the result, see
``tests/tools/test_terminal_truncation_spill.py``) was already wired; this
locks the OTHER half of the corrected P0.1 definition ("让摘要里有东西可指"):

- the Phase-1 prune pass (``_prune_old_tool_results`` → ``_demote_tool_result_at``)
  replaced a >200-char tool result with a 1-line summary that carried command /
  exit code / size — but NO path, because nothing was written to disk. The
  model's only way back was to re-run the command.
- the salvage path (``salvage_grown_transcript``) was worse: bare
  ``[Old tool output cleared...]`` placeholder, no summary at all.

Both must now persist the full content via the Layer-2 spillover primitive
and append a ``[Full output saved to: <path>]`` pointer (format matched to
``tool_result_storage._PERSISTED_PATH_RE`` so ``extract_persisted_path`` —
and the result-reference stubbing guard — can recover the path too).
"""

import json
from pathlib import Path

import pytest

from agent.context_compressor import (
    _PRUNED_TOOL_PLACEHOLDER,
    ContextCompressor,
    salvage_grown_transcript,
)
from tools.tool_result_storage import extract_persisted_path


def _make_compressor(**overrides):
    from unittest.mock import patch

    kwargs = dict(
        model="test/model",
        quiet_mode=True,
        protect_first_n=1,
        protect_last_n=2,
    )
    kwargs.update(overrides)
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=100000
    ):
        return ContextCompressor(**kwargs)


def _big_tool_pair(call_id, name="terminal", marker="PAYLOAD-BODY", size=3000):
    """assistant tool_call + tool result, content > min_prune_chars (200)."""
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps({"command": "run-scan"}),
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": f"{marker}\n" + "x" * size,
        },
    ]


@pytest.fixture
def spill_home(tmp_path, monkeypatch):
    import fulilian_constants

    monkeypatch.setenv("FULILIAN_HOME", str(tmp_path / ".fulilian"))
    monkeypatch.delenv("FULILIAN_TEST_MODE", raising=False)
    return tmp_path / ".fulilian" / "cache" / "spillover"


class TestPrunePersistsPointer:
    def test_pruned_summary_carries_existing_path(self, spill_home):
        cc = _make_compressor()
        msgs = [
            {"role": "user", "content": "go"},
            *_big_tool_pair("call-1"),
            {"role": "user", "content": "next"},
        ]
        pruned, count = cc._prune_old_tool_results(
            msgs, protect_tail_count=1
        )
        assert count >= 1
        content = pruned[2]["content"]
        path = extract_persisted_path(content)
        assert path, f"summary must carry a spill pointer, got: {content!r}"
        p = Path(path)
        assert p.exists()
        # The spill holds the FULL content, not the summary.
        assert "PAYLOAD-BODY" in p.read_text()

    def test_salvage_placeholder_carries_pointer(self, spill_home):
        msgs = [{"role": "user", "content": "go"}]
        for i in range(3):  # salvage keeps the last 2 tool results; make 3
            msgs.extend(_big_tool_pair(f"call-s{i}"))
        msgs.append({"role": "user", "content": "next"})
        out = salvage_grown_transcript(msgs, msgs, budget=20000)
        assert out is not None
        content = out[2]["content"]
        assert content.startswith(_PRUNED_TOOL_PLACEHOLDER)
        path = extract_persisted_path(content)
        assert path, "hard-deleted tool result must leave a spill pointer"
        assert "PAYLOAD-BODY" in Path(path).read_text()

    def test_small_results_are_not_pruned_nor_persisted(self, spill_home):
        cc = _make_compressor()
        msgs = [
            {"role": "user", "content": "go"},
            *_big_tool_pair("call-3", size=50),  # < 200 chars
            {"role": "user", "content": "next"},
        ]
        pruned, count = cc._prune_old_tool_results(
            msgs, protect_tail_count=1
        )
        assert count == 0
        assert pruned[2]["content"].startswith("PAYLOAD-BODY")
        assert extract_persisted_path(pruned[2]["content"]) is None

    def test_persistence_failure_still_prunes(self, spill_home, monkeypatch):
        """Best-effort contract: a spillover failure must never block pruning."""
        import tools.tool_result_storage as trs

        def boom(content, filename):
            raise OSError("disk full")

        monkeypatch.setattr(trs, "_write_to_spillover", boom)
        cc = _make_compressor()
        msgs = [
            {"role": "user", "content": "go"},
            *_big_tool_pair("call-4"),
            {"role": "user", "content": "next"},
        ]
        pruned, count = cc._prune_old_tool_results(
            msgs, protect_tail_count=1
        )
        assert count >= 1
        # Pruned with the summary, but without a dangling pointer.
        assert extract_persisted_path(pruned[2]["content"]) is None

    def test_pointer_format_matches_storage_regex(self, spill_home):
        """The pointer must be recoverable by the storage-layer regex."""
        cc = _make_compressor()
        msgs = [
            {"role": "user", "content": "go"},
            *_big_tool_pair("call-5"),
            {"role": "user", "content": "next"},
        ]
        pruned, _ = cc._prune_old_tool_results(msgs, protect_tail_count=1)
        assert extract_persisted_path(pruned[2]["content"]) is not None
