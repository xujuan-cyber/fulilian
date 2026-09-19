"""Streamed response lines follow the bullet + hanging-indent grammar.

History: the 4-space ``_STREAM_PAD`` indent made every copied line carry
leading whitespace, so pasting a response out of the terminal produced broken
text; the pad was zeroed (July 2026) and the final-response Rich Panel used
zero horizontal padding for the same reason.

The Claude-Code-aligned transcript grammar reintroduces a *deliberate*
two-space hanging indent for prose continuation lines, so the ``●`` bullet
reads as the paragraph marker.  The anti-pollution guarantee is preserved
where it matters most: fenced code (and realigned tables) stay flush-left, and
markdown's own relative indentation is carried on top of the hanging indent
rather than flattened.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Prose continuation lines carry this indent so the ● bullet stays attached.
HANGING_INDENT = "  "


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


@pytest.fixture
def cli_stub(monkeypatch):
    from cli import FulilianCLI
    import cli as climod

    cli = FulilianCLI.__new__(FulilianCLI)
    cli.show_reasoning = False
    cli.final_response_markdown = "raw"
    cli.show_timestamps = False
    cli._reset_stream_state()

    emitted = []
    monkeypatch.setattr(climod, "_cprint", lambda s: emitted.append(s))
    monkeypatch.setattr(climod, "_terminal_width_for_streaming", lambda: 74)
    return cli, emitted


def test_stream_pad_is_empty():
    import cli as climod

    assert climod._STREAM_PAD == ""


def test_first_line_carries_bullet_without_leading_space(cli_stub):
    cli, emitted = cli_stub
    cli._stream_delta("First streamed line of text.\nSecond streamed line.\n")
    cli._flush_stream()
    plain = [_strip_ansi(e) for e in emitted]
    first = [line for line in plain if "First streamed line" in line]
    assert first, "no content lines captured"
    assert first[0] == "● First streamed line of text."


def test_continuation_lines_take_exactly_the_hanging_indent(cli_stub):
    cli, emitted = cli_stub
    cli._stream_delta("First streamed line of text.\nSecond streamed line.\n")
    cli._flush_stream()
    plain = [_strip_ansi(e) for e in emitted]
    second = [line for line in plain if "Second streamed line" in line]
    assert second, "continuation line not captured"
    assert second[0] == HANGING_INDENT + "Second streamed line."


def test_intentional_markdown_indentation_is_preserved(cli_stub):
    cli, emitted = cli_stub
    cli._stream_delta("- item\n  - nested item\n")
    cli._flush_stream()
    plain = [_strip_ansi(e) for e in emitted]
    # The bullet attaches to the first list item; the nested item keeps its
    # own two spaces *on top of* the hanging indent rather than being
    # flattened to column 0.
    assert any(line == "● - item" for line in plain)
    assert any(line == HANGING_INDENT + "  - nested item" for line in plain)


def test_fenced_code_is_not_indented(cli_stub):
    """Code must stay flush-left: indenting it would pollute copied code."""
    cli, emitted = cli_stub
    cli._stream_delta("Intro paragraph.\n```\nprint('hi')\n```\nOutro.\n")
    cli._flush_stream()
    plain = [_strip_ansi(e) for e in emitted]
    code = [line for line in plain if "print('hi')" in line]
    assert code, "code line not captured"
    assert code[0] == "print('hi')"
    outro = [line for line in plain if "Outro." in line]
    assert outro and outro[0] == HANGING_INDENT + "Outro."
