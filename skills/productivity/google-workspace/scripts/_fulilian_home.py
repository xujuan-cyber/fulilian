"""Resolve FULILIAN_HOME for standalone skill scripts.

Skill scripts may run outside the Fulilian process (e.g. system Python,
nix env, CI) where ``fulilian_constants`` is not importable.  This module
provides the same ``get_fulilian_home()`` and ``display_fulilian_home()``
contracts as ``fulilian_constants`` without requiring it on ``sys.path``.

When ``fulilian_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``fulilian_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``FULILIAN_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from fulilian_constants import display_fulilian_home as display_fulilian_home
    from fulilian_constants import get_fulilian_home as get_fulilian_home
except (ModuleNotFoundError, ImportError):

    def get_fulilian_home() -> Path:
        """Return the Fulilian home directory (default: ~/.fulilian).

        Mirrors ``fulilian_constants.get_fulilian_home()``."""
        val = os.environ.get("FULILIAN_HOME", "").strip()
        return Path(val) if val else Path.home() / ".fulilian"

    def display_fulilian_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``fulilian_constants.display_fulilian_home()``."""
        home = get_fulilian_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
