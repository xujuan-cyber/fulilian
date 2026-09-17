"""``_strip_skill_frontmatter`` must only strip a document that OPENS with it.

Regression guard for audit C2-10: the old implementation split on ``---``
unconditionally, so any body containing two horizontal rules had everything up
to the second rule sliced off and the tail returned as "the body".
"""

from run_agent import _strip_skill_frontmatter


def test_leading_frontmatter_is_stripped():
    text = "---\nname: x\n---\nBody line\n"
    assert _strip_skill_frontmatter(text).strip() == "Body line"


def test_body_with_horizontal_rules_is_kept_intact():
    text = "Title\n\n---\n\nmiddle\n\n---\n\nend\n"
    assert _strip_skill_frontmatter(text) == text


def test_no_delimiter_returns_text_unchanged():
    text = "just a body\n"
    assert _strip_skill_frontmatter(text) == text


def test_single_leading_delimiter_returns_text_unchanged():
    """An opening delimiter with no closing one is not frontmatter."""
    text = "---\nno closing delimiter\n"
    assert _strip_skill_frontmatter(text) == text
