"""``fulilian replay`` command parser.

Replays a solved challenge's trajectory step by step.
"""

from __future__ import annotations

from typing import Callable


def build_replay_parser(subparsers, *, cmd_replay: Callable) -> None:
    """Attach the ``replay`` subcommand to ``subparsers``."""
    replay_parser = subparsers.add_parser(
        "replay",
        help="Replay a challenge's solution trajectory",
        description="Replay a solved challenge's trajectory step by step.",
    )
    replay_parser.add_argument("id", help="Challenge ID or session ID")
    replay_parser.add_argument("--step", type=int, help="Start at a specific step")
    replay_parser.add_argument("--json", action="store_true",
                               help="Output structured JSON")
    replay_parser.set_defaults(func=cmd_replay)