"""Resolve FULILIAN_HOME for standalone skill scripts.

Skill scripts may run outside the Fulilian process (system Python, nix env,
CI) where ``fulilian_constants`` is not importable.  This module provides the
same ``get_fulilian_home()`` contract without requiring it on ``sys.path``.

When ``fulilian_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from fulilian_constants import get_fulilian_home as get_fulilian_home
except (ModuleNotFoundError, ImportError):

    def get_fulilian_home() -> Path:
        """Return the Fulilian home directory (default: ``~/.fulilian``)."""
        val = os.environ.get("FULILIAN_HOME", "").strip()
        return Path(val) if val else Path.home() / ".fulilian"
