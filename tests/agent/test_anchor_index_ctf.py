"""Tests for the CTF pattern extension of the lean-mode Anchor Index.

The Anchor Index is the LLM-free, regex-harvested exact-identifier section of
compaction summaries (backported from hermes-agent v2026.8.31). This fork
pins CTF-specific categories (flags, hashes, CVEs, offsets, hosts, encoded
blobs) ahead of the upstream coding categories: the per-category char budget
is sequential, so CTF needles must win the squeeze.

Also proves the composed call path ``_redact_compaction_text(_build_anchor_index(...))``
keeps CTF identifiers verbatim — the compaction redactor must not paraphrase
the very facts the index exists to preserve.
"""

from agent.context_compressor import (
    _ANCHOR_NOISE,
    _LEAN_ANCHOR_BUDGET_CHARS,
    _build_anchor_index,
    _redact_compaction_text,
)


def _index(text: str) -> str:
    return _build_anchor_index([{"role": "tool", "content": text}])


def test_flags_extracted_case_insensitive():
    out = _index("found picoCTF{st4sh_it_1985} in /var/www and FLAG{simple_one}")
    assert "flags:" in out
    assert "picoCTF{st4sh_it_1985}" in out
    assert "FLAG{simple_one}" in out


def test_hash_lengths_extracted():
    md5 = "d41d8cd98f00b204e9800998ecf8427e"
    sha1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    out = _index(f"md5 {md5} sha1 {sha1} sha256 {sha256}")
    assert md5 in out
    assert sha1 in out
    assert sha256 in out


def test_cve_offsets_hosts():
    out = _index("exploit for CVE-2021-44228, ret at 0x7ffd4a2b, target 10.10.10.5:9001")
    assert "CVE-2021-44228" in out
    assert "0x7ffd4a2b" in out
    assert "10.10.10.5:9001" in out


def test_encoded_blobs_capped():
    blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5eg=="
    out = _index(f"payload {blob} " + "filler text " * 200)
    assert "encoded blobs:" in out
    assert blob[:64] in out


def test_wildcard_bind_filtered():
    out = _index("listening on 0.0.0.0 and on 10.0.0.2 for the challenge service")
    assert "10.0.0.2" in out
    assert "0.0.0.0" not in out.split("hosts:")[1].splitlines()[0].replace(
        "10.0.0.2", ""
    )


def test_noise_set_contains_wildcard_bind():
    assert "0.0.0.0" in _ANCHOR_NOISE


def test_ctf_categories_precede_coding_ones():
    """CTF categories win the sequential budget before coding categories."""
    text = (
        "flag{budget_probe_01} "
        + ("10.10.10.9 " * 30)
        + ("CVE-2020-1234 " * 30)
        + ("filler prose without identifiers " * 400)
    )
    out = _index(text)
    flag_pos = out.find("flag{budget_probe_01}")
    host_pos = out.find("10.10.10.9")
    assert flag_pos != -1
    assert host_pos != -1
    assert flag_pos < host_pos


def test_budget_respected_on_huge_input():
    blob = "A" * 200
    text = (" ".join([blob] * 500)) + " flag{budget_cap_check} " + ("10.10.10.1 " * 100)
    out = _index([{"role": "tool", "content": text}][0]["content"])
    assert len(out) < _LEAN_ANCHOR_BUDGET_CHARS + 500
    assert "flag{budget_cap_check}" in out


def test_empty_and_non_string_content():
    assert _build_anchor_index([]) == ""
    assert _build_anchor_index([{"role": "tool", "content": ""}]) == ""
    assert _build_anchor_index([{"role": "assistant", "content": None}]) == ""


def test_redaction_preserves_ctf_identifiers():
    raw = _index(
        "flag: picoCTF{st4sh_it_1985} md5 d41d8cd98f00b204e9800998ecf8427e "
        "CVE-2021-44228 at 0x7ffd4a2b host 10.10.10.5:9001"
    )
    redacted = _redact_compaction_text(raw)
    assert "picoCTF{st4sh_it_1985}" in redacted
    assert "d41d8cd98f00b204e9800998ecf8427e" in redacted
    assert "CVE-2021-44228" in redacted
    assert "0x7ffd4a2b" in redacted
    assert "10.10.10.5:9001" in redacted
