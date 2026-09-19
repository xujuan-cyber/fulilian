"""Tests for the Claude-Code-style transcript grammar in agent/display.py.

Covers ``render_tool_call_line`` / ``render_numbered_block`` /
``render_tool_result_summary`` / ``render_tool_completion`` — the shared
primitives behind the ``● Tool(args)`` / ``⎿`` transcript lines.
"""

import json

import pytest

from agent.display import (
    render_numbered_block,
    render_tool_call_line,
    render_tool_completion,
    render_tool_result_summary,
    set_tool_preview_max_len,
    tool_display_name,
)


@pytest.fixture(autouse=True)
def reset_tool_preview_max_len():
    set_tool_preview_max_len(0)
    yield
    set_tool_preview_max_len(0)


# ── tool_display_name ────────────────────────────────────────────────────


def test_display_name_maps_known_tools():
    assert tool_display_name("write_file") == "Write"
    assert tool_display_name("terminal") == "Bash"
    assert tool_display_name("read_file") == "Read"
    assert tool_display_name("patch") == "Edit"


def test_display_name_falls_back_to_pascal_case():
    assert tool_display_name("brand_new_tool") == "BrandNewTool"
    assert tool_display_name("single") == "Single"


def test_display_name_handles_empty():
    assert tool_display_name("") == "Tool"
    assert tool_display_name(None) == "Tool"


# ── render_tool_call_line ────────────────────────────────────────────────


def test_call_line_includes_args_preview():
    assert render_tool_call_line("write_file", {"path": "notes.md"}, colorize=False) == "● Write(notes.md)"


def test_call_line_without_args_has_no_parens():
    assert render_tool_call_line("terminal", {}, colorize=False) == "● Bash"


def test_call_line_colorized_adds_ansi_but_keeps_text():
    line = render_tool_call_line("write_file", {"path": "a.md"}, colorize=True)
    assert "●" in line and "Write(a.md)" in line
    assert "\033[" in line


def test_call_line_never_raises_on_bad_args():
    for bad in (None, {}, {"path": None}, {"path": {"nested": 1}}):
        assert "●" in render_tool_call_line("write_file", bad, colorize=False)


# ── render_numbered_block ────────────────────────────────────────────────


def test_numbered_block_aligns_gutter_for_double_digits():
    lines = render_numbered_block([f"l{i}" for i in range(1, 12)], colorize=False)
    assert len(lines) == 11
    # indent(6) + gutter right-justified to the widest number (2) + one space
    assert lines[0].startswith(" " * 7 + "1 ")
    assert lines[9].startswith(" " * 6 + "10 ")
    assert lines[10].startswith(" " * 6 + "11 ")


def test_numbered_block_honours_start_offset():
    lines = render_numbered_block(["a", "b"], start=41, colorize=False)
    assert lines[0].strip().startswith("41")
    assert lines[1].strip().startswith("42")


def test_numbered_block_diff_markers():
    lines = render_numbered_block(["old", "new"], markers=["-", "+"], colorize=False)
    assert lines[0].endswith("-old")
    assert lines[1].endswith("+new")


def test_numbered_block_drops_mismatched_markers():
    lines = render_numbered_block(["only"], markers=["-", "+"], colorize=False)
    assert len(lines) == 1
    assert lines[0].endswith(" only")


def test_numbered_block_without_numbers_keeps_indent():
    lines = render_numbered_block(["a", "b"], numbers=False, colorize=False)
    assert lines == ["      a", "      b"]


def test_numbered_block_empty_input():
    assert render_numbered_block([], colorize=False) == []


# ── render_tool_result_summary ───────────────────────────────────────────


def test_read_file_gets_numbered_body_and_size_summary():
    content = "\n".join(f"line {i}" for i in range(1, 13))
    summary, body, numbered = render_tool_result_summary("read_file", content)
    assert summary == "Read 12 lines"
    assert numbered is True
    assert body == [f"line {i}" for i in range(1, 13)]


def test_read_file_single_line_says_line_singular():
    summary, body, numbered = render_tool_result_summary("read_file", "only one")
    assert summary == "Read 1 line"
    assert body == ["only one"]


def test_read_file_long_content_is_clipped():
    content = "\n".join(f"l{i}" for i in range(1, 200))
    summary, body, numbered = render_tool_result_summary("read_file", content, max_lines=40)
    assert "Read 199 lines" in summary
    assert len(body) == 40
    assert numbered is True


def test_terminal_uses_first_line_as_summary_with_unnumbered_body():
    result = json.dumps({"exit_code": 0, "stdout": "drwxr a\n-rw- b\n-rw- c\n"})
    summary, body, numbered = render_tool_result_summary("terminal", result)
    assert summary == "drwxr a"
    assert body == ["-rw- b", "-rw- c"]
    assert numbered is False


def test_terminal_long_output_is_summarized_not_dumped():
    result = "\n".join(f"o{i}" for i in range(200))
    summary, body, numbered = render_tool_result_summary("terminal", result, max_lines=40)
    assert "(+199 lines)" in summary
    assert body == []


def test_write_file_is_summary_only():
    result = json.dumps({"success": True, "message": "Wrote 6 lines to notes.md"})
    summary, body, numbered = render_tool_result_summary("write_file", result)
    assert summary == "Wrote 6 lines to notes.md"
    assert body == []


def test_failure_reports_reason():
    summary, body, numbered = render_tool_result_summary("terminal", json.dumps({"exit_code": 1}))
    assert summary == "exit 1"
    assert body == []


def test_empty_result_says_no_output():
    assert render_tool_result_summary("terminal", "")[0] == "no output"
    assert render_tool_result_summary("terminal", None)[0] == "no output"


def test_nested_json_envelope_is_unwrapped():
    result = json.dumps({"output": json.dumps({"exit_code": 0, "stdout": "line a\nline b"})})
    summary, body, _ = render_tool_result_summary("terminal", result)
    assert summary == "line a"
    assert body == ["line b"]


def test_multiline_non_body_tool_is_summarized():
    summary, body, numbered = render_tool_result_summary("web_search", "first\nsecond\nthird")
    assert summary == "first (+2 lines)"
    assert body == []
    assert numbered is False


# ── render_tool_completion ───────────────────────────────────────────────


def test_completion_shape_for_write():
    lines = render_tool_completion(
        "write_file", {"path": "notes.md"}, 1.2,
        json.dumps({"success": True, "message": "Wrote 6 lines to notes.md"}),
        colorize=False,
    )
    assert lines[0] == "● Write(notes.md)"
    assert lines[1] == "  ⎿  Wrote 6 lines to notes.md (1.2s)"
    assert len(lines) == 2


def test_completion_includes_numbered_body_for_read():
    lines = render_tool_completion(
        "read_file", {"path": "a.py"}, 0.3, "a\nb\nc", colorize=False,
    )
    assert lines[0] == "● Read(a.py)"
    assert lines[1] == "  ⎿  Read 3 lines (0.3s)"
    assert lines[2].endswith("1 a")
    assert lines[4].endswith("3 c")


def test_completion_omits_duration_when_unknown():
    lines = render_tool_completion("terminal", {"command": "ls"}, 0.0, "out", colorize=False)
    assert lines[1] == "  ⎿  out"


def test_completion_never_raises_on_garbage():
    for args in (None, {}, {"path": 1}):
        for result in (None, "", "not json", "{\"broken\":"):
            lines = render_tool_completion("read_file", args, 0.1, result, colorize=False)
            assert lines and lines[0].startswith("● ")
