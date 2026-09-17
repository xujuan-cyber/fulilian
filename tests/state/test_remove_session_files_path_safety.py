"""Path-safety guard on ``SessionDB._remove_session_files`` (audit C1-13).

The helper builds ``sessions_dir / f"{session_id}{suffix}"`` and a
``request_dump_{session_id}_*.json`` glob from a session id that can originate
outside the state layer (gateway headers, RPC params — see the CWE-22 note in
``gateway/session.py``). An id carrying parent traversal or a path separator
could delete files *outside* the sessions directory; an id carrying a glob
metacharacter could over-match unrelated dumps *inside* it.

The guard refuses such ids outright instead of sanitising them, because this
helper deletes: a mangled name would either miss the real transcript or take
out an unrelated file.
"""

import pytest

from fulilian_state import SessionDB, _session_file_component_unsafe


@pytest.mark.parametrize(
    "session_id",
    [
        "",
        None,
        "..",
        "../outside",
        "../../etc/passwd",
        "a/b",
        "a\\b",
        "C:evil",
        "x*",
        "x?",
        "x[y]",
    ],
)
def test_unsafe_session_ids_are_refused(session_id):
    assert _session_file_component_unsafe(session_id) is True


@pytest.mark.parametrize(
    "session_id",
    [
        # Colon-delimited multi-segment ids are the documented real shape,
        # so an interior colon must NOT be treated as traversal.
        "agent:main:telegram:dm:12345",
        "abc-123_456.789",
        "cron_daily_20260917_120000",
    ],
)
def test_legitimate_session_ids_pass(session_id):
    assert _session_file_component_unsafe(session_id) is False


def test_unsafe_id_deletes_nothing(tmp_path):
    """Traversal and glob ids must not remove anything at all."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    # Would be hit by sessions_dir / "../outside.json".
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    # Would be hit by the glob "request_dump_x*_*.json".
    decoy_dump = sessions_dir / "request_dump_xDECOY_1.json"
    decoy_dump.write_text("keep", encoding="utf-8")

    SessionDB._remove_session_files(sessions_dir, "../outside")
    SessionDB._remove_session_files(sessions_dir, "x*")
    SessionDB._remove_session_files(sessions_dir, "")

    assert outside.read_text(encoding="utf-8") == "keep"
    assert decoy_dump.read_text(encoding="utf-8") == "keep"


def test_safe_id_still_removes_transcript_and_dumps(tmp_path):
    """The guard must not regress the legitimate cleanup path."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    sid = "agent:main:telegram:dm:12345"
    transcript = sessions_dir / f"{sid}.json"
    transcript_jsonl = sessions_dir / f"{sid}.jsonl"
    dump = sessions_dir / f"request_dump_{sid}_20260917_120000.json"
    other_dump = sessions_dir / "request_dump_other_20260917_120000.json"
    for path in (transcript, transcript_jsonl, dump, other_dump):
        path.write_text("x", encoding="utf-8")

    SessionDB._remove_session_files(sessions_dir, sid)

    assert not transcript.exists()
    assert not transcript_jsonl.exists()
    assert not dump.exists()
    # A different session's dump must survive.
    assert other_dump.exists()
