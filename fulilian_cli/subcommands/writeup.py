"""``fulilian writeup`` command parser.

Generates a CTF writeup from a solved challenge's session history.
"""

from __future__ import annotations

from typing import Callable


def build_writeup_parser(subparsers, *, cmd_writeup: Callable) -> None:
    """Attach the ``writeup`` subcommand to ``subparsers``."""
    writeup_parser = subparsers.add_parser(
        "writeup",
        help="Auto-generate a CTF writeup",
        description="Auto-generate a CTF writeup from a solved challenge's session history.",
    )
    writeup_parser.add_argument("id", help="Challenge ID or session ID")
    writeup_parser.add_argument("--format", choices=["markdown", "html", "json"],
                                default="markdown", help="Output format (default: markdown)")
    writeup_parser.add_argument("--output", "-o", help="Output file path")
    writeup_parser.set_defaults(func=cmd_writeup)