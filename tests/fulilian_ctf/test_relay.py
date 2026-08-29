"""三段式接力块（F2-012 契约）单元测试。"""

from __future__ import annotations

from fulilian_ctf.relay import (
    DEAD_END_HEADER,
    NEXT_HEADER,
    RELAY_HEADER,
    build_relay,
    parse_relay,
    read_relay_file,
    write_relay_file,
)


def test_build_relay_format():
    text = build_relay(
        achieved_primitives=["Port 80 open", "Apache 2.4.49"],
        dead_ends=["CVE-2021-41773 not exploitable"],
        next_steps=["Try CVE-2021-42013"],
    )
    assert text.startswith(RELAY_HEADER)
    assert DEAD_END_HEADER in text
    assert NEXT_HEADER in text
    assert "- Port 80 open" in text
    assert "- Try CVE-2021-42013" in text


def test_parse_round_trip():
    text = build_relay(
        achieved_primitives=["A", "B"],
        dead_ends=["C"],
        next_steps=["D", "E"],
    )
    parsed = parse_relay(text)
    assert parsed["achieved_primitives"] == ["A", "B"]
    assert parsed["dead_ends"] == ["C"]
    assert parsed["next_steps"] == ["D", "E"]


def test_parse_empty():
    parsed = parse_relay("")
    assert parsed == {
        "achieved_primitives": [],
        "dead_ends": [],
        "next_steps": [],
    }


def test_parse_ignores_unmatched_lines():
    text = "noise line\n- orphan item\n" + NEXT_HEADER + "\n  - real step"
    parsed = parse_relay(text)
    assert parsed["next_steps"] == ["real step"]
    assert parsed["achieved_primitives"] == []


def test_write_and_read_file(tmp_path):
    text = build_relay([], [], ["RESUME challenge"])
    write_relay_file(tmp_path, text)
    assert read_relay_file(tmp_path) == text
    # 文件确实落盘
    assert (tmp_path / "RELAY.md").exists()


def test_read_missing_file(tmp_path):
    assert read_relay_file(tmp_path) is None
