"""Structural guard: ``agent/`` must not import private ``delegate_tool`` names.

The phase-7 acceptance criterion was originally a grep:

    grep -rn "from tools.delegate_tool import _" agent/

That only matches the single-line spelling. It cannot see

    from tools.delegate_tool import (
        _build_child_preserving_parent_tools,
        DEFAULT_MAX_ITERATIONS,
    )

because the underscore sits on the next line -- and exactly that bypass was
live in ``agent/subagent_lifecycle.py`` while a comment three lines above it
claimed private helpers were never imported. ``grep`` reads glyphs; ``ast``
reads structure, so multi-line imports, parenthesised alias lists and
``import ... as`` forms are all covered here.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"
DELEGATE_MODULE = "tools.delegate_tool"


def _private_imports(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, imported_name) for private delegate_tool imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != DELEGATE_MODULE:
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                found.append((node.lineno, alias.name))
    return found


def test_agent_does_not_import_private_symbols_from_delegate_tool():
    agent_files = sorted(AGENT_DIR.rglob("*.py"))

    # A silently-empty glob would make this test pass for the wrong reason.
    assert agent_files, f"no python files found under {AGENT_DIR}"

    violations = []
    for path in agent_files:
        for lineno, name in _private_imports(path):
            violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno} -> {name}")

    assert not violations, (
        "agent/ imports private symbols from tools.delegate_tool:\n  "
        + "\n  ".join(violations)
        + "\nAdd a public wrapper in tools/delegate_tool.py instead "
        "(see run_child_lifecycle / build_child_preserving_parent_tools)."
    )
