"""Tests for agent/spinner_verbs.py — the Claude-Code verb pool."""

import pytest

from agent.spinner_verbs import DEFAULT_VERB, SPINNER_VERBS, pick_verb


def test_pool_size_matches_claude_code():
    """The pool is the extracted 2.1.274 set; growing it is a deliberate act."""
    assert len(SPINNER_VERBS) == 188


def test_pool_entries_are_non_empty_strings():
    assert all(isinstance(v, str) and v.strip() for v in SPINNER_VERBS)
    assert len(set(SPINNER_VERBS)) == len(SPINNER_VERBS), "duplicate verbs in pool"


def test_pool_boundaries_match_the_extraction():
    """Claude Code ships the pool unsorted, so guard the ends instead.

    ``Gesticulating`` precedes ``Germinating`` in the source list — the pool is
    faithfully copied, not re-sorted, and these anchors catch a botched
    re-extraction.
    """
    assert SPINNER_VERBS[0] == "Accomplishing"
    assert SPINNER_VERBS[-1] == "Zigzagging"
    assert SPINNER_VERBS.index("Gesticulating") < SPINNER_VERBS.index("Germinating")
    assert "Clauding" in SPINNER_VERBS


def test_pick_is_deterministic():
    assert pick_verb("thinking:1700000000000") == pick_verb("thinking:1700000000000")


def test_pick_returns_a_pool_member():
    for seed in ("thinking:1", "responding:2", "tool:3", "x", "Ünicode"):
        assert pick_verb(seed) in SPINNER_VERBS


@pytest.mark.parametrize("seed", ["thinking:1", "responding:1", "tool:1", "thinking:2"])
def test_pick_varies_across_seeds(seed):
    """A different phase instance should usually draw a different verb.

    Not asserted as a hard inequality for every pair (collisions are legal),
    but the phase-name component alone must not pin every phase to one word.
    """
    results = {pick_verb(f"{name}:{n}") for name in ("thinking", "responding", "tool") for n in range(1, 6)}
    assert len(results) > 3, f"verb pool looks degenerate: {results}"


def test_empty_seed_falls_back_to_default():
    assert pick_verb("") == DEFAULT_VERB
    assert pick_verb(None) == DEFAULT_VERB
