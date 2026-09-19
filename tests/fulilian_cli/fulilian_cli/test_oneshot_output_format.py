"""Tests for fulilian -z --output-format {text,json,stream-json}."""

import io
import json

import pytest

from fulilian_cli._parser import build_top_level_parser
from fulilian_cli.oneshot import JsonEventSink, _result_payload


def _result(**overrides):
    base = {
        "estimated_cost_usd": 0.1234,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 800,
        "cache_write_tokens": 0,
        "reasoning_tokens": 50,
        "total_tokens": 1250,
        "api_calls": 3,
        "model": "openai/gpt-5.5",
        "provider": "openrouter",
        "session_id": "abc123",
        "completed": True,
        "failed": False,
    }
    base.update(overrides)
    return base


def _events(buf):
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def _types(buf):
    return [e["type"] for e in _events(buf)]


class TestResultPayload:
    def test_maps_fulilian_keys_onto_the_claude_code_shape(self):
        payload = _result_payload(_result(), "hello")
        assert payload["subtype"] == "success"
        assert payload["is_error"] is False
        assert payload["result"] == "hello"
        assert payload["session_id"] == "abc123"
        assert payload["num_turns"] == 3
        assert payload["total_cost_usd"] == 0.1234
        assert payload["usage"]["input_tokens"] == 1000
        assert payload["usage"]["cache_read_input_tokens"] == 800
        assert payload["usage"]["cache_creation_input_tokens"] == 0

    def test_failure_sets_error_subtype(self):
        payload = _result_payload(_result(failed=True), "")
        assert payload["subtype"] == "error"
        assert payload["is_error"] is True

    def test_partial_counts_as_error(self):
        assert _result_payload(_result(partial=True), "")["is_error"] is True

    def test_unset_fields_are_dropped_not_nulled(self):
        payload = _result_payload({"failed": False}, "hi")
        assert "session_id" not in payload
        assert "total_cost_usd" not in payload


class TestStreamJsonEvents:
    def _run(self, include_partial=True):
        buf = io.StringIO()
        sink = JsonEventSink(buf, include_partial=include_partial)
        sink.system_init(cwd="/tmp", model="m")
        sink.reasoning_delta("thinking")
        sink.text_delta("Hello ")
        sink.text_delta("world")
        sink.tool_start("tu_1", "read_file", {"path": "a.py"})
        sink.tool_complete("tu_1", "read_file", {"path": "a.py"}, "file body")
        sink.text_delta("Done.")
        sink.result(_result(), "Hello worldDone.")
        return buf, sink

    def test_every_line_is_valid_json(self):
        buf, _ = self._run()
        assert _events(buf), "no events emitted"

    def test_starts_with_system_init(self):
        buf, _ = self._run()
        first = _events(buf)[0]
        assert first["type"] == "system"
        assert first["subtype"] == "init"

    def test_ends_with_the_result_object(self):
        buf, _ = self._run()
        last = _events(buf)[-1]
        assert last["type"] == "result"
        assert last["subtype"] == "success"

    def test_message_and_block_boundaries_are_balanced(self):
        buf, _ = self._run()
        events = [e["event"]["type"] for e in _events(buf) if e["type"] == "stream_event"]
        assert events.count("message_start") == events.count("message_stop")
        assert events.count("message_start") == events.count("message_delta")
        assert events.count("content_block_start") == events.count("content_block_stop")

    def test_text_and_thinking_blocks_are_typed(self):
        buf, _ = self._run()
        kinds = [
            e["event"]["content_block"]["type"]
            for e in _events(buf)
            if e["type"] == "stream_event" and e["event"]["type"] == "content_block_start"
        ]
        assert "thinking" in kinds
        assert "text" in kinds
        assert "tool_use" in kinds

    def test_tool_calls_emit_assistant_tool_use_and_user_tool_result(self):
        buf, _ = self._run()
        events = _events(buf)
        tool_use = [
            b for e in events if e["type"] == "assistant"
            for b in e["message"]["content"] if b["type"] == "tool_use"
        ]
        assert tool_use and tool_use[0]["name"] == "read_file"
        results = [
            b for e in events if e["type"] == "user"
            for b in e["message"]["content"] if b["type"] == "tool_result"
        ]
        assert results and results[0]["content"] == "file body"

    def test_assistant_envelope_carries_accumulated_text(self):
        buf, _ = self._run()
        texts = [
            b["text"] for e in _events(buf) if e["type"] == "assistant"
            for b in e["message"]["content"] if b["type"] == "text"
        ]
        assert any(t == "Hello world" for t in texts)

    def test_without_partial_messages_deltas_are_omitted(self):
        buf, _ = self._run(include_partial=False)
        deltas = [
            e for e in _events(buf)
            if e["type"] == "stream_event" and e["event"]["type"] == "content_block_delta"
        ]
        assert deltas == []
        # ...but the block-level envelope still carries the text.
        assert any(
            b["type"] == "text"
            for e in _events(buf) if e["type"] == "assistant"
            for b in e["message"]["content"]
        )

    def test_deltas_present_when_requested(self):
        buf, _ = self._run(include_partial=True)
        deltas = [
            e["event"]["delta"]["type"] for e in _events(buf)
            if e["type"] == "stream_event" and e["event"]["type"] == "content_block_delta"
        ]
        assert "text_delta" in deltas
        assert "thinking_delta" in deltas

    def test_close_message_is_idempotent(self):
        buf = io.StringIO()
        sink = JsonEventSink(buf)
        sink.text_delta("hi")
        sink.close_message()
        before = len(_events(buf))
        sink.close_message()
        assert len(_events(buf)) == before


class TestSinkRobustness:
    def test_broken_stream_does_not_raise(self):
        class _Boom:
            def write(self, *_a):
                raise OSError("pipe closed")

            def flush(self):
                raise OSError("pipe closed")

        sink = JsonEventSink(_Boom())
        # A machine-readable line must never abort a completed run.
        sink.system_init(cwd="/tmp")
        sink.text_delta("hi")
        sink.result(_result(), "hi")

    def test_non_serializable_tool_result_is_stringified(self):
        buf = io.StringIO()
        sink = JsonEventSink(buf)
        sink.tool_complete("tu", "t", {}, object())
        assert _events(buf)


class TestParserWiring:
    def test_default_is_text(self):
        parser, _subparsers, _chat = build_top_level_parser()
        args = parser.parse_args(["-z", "hi"])
        assert args.output_format == "text"
        assert args.include_partial_messages is False

    @pytest.mark.parametrize("mode", ["json", "stream-json"])
    def test_modes_are_accepted(self, mode):
        parser, _subparsers, _chat = build_top_level_parser()
        args = parser.parse_args(["-z", "hi", "--output-format", mode])
        assert args.output_format == mode

    def test_unknown_mode_is_rejected(self):
        parser, _subparsers, _chat = build_top_level_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["-z", "hi", "--output-format", "yaml"])

    def test_include_partial_messages_flag(self):
        parser, _subparsers, _chat = build_top_level_parser()
        args = parser.parse_args(["-z", "hi", "--output-format", "stream-json",
                                  "--include-partial-messages"])
        assert args.include_partial_messages is True
