"""``fulilian console`` subcommand parser."""

from __future__ import annotations

from typing import Callable


def build_console_parser(subparsers, *, cmd_console: Callable) -> None:
    """Attach the safe Fulilian Console REPL subcommand."""
    console_parser = subparsers.add_parser(
        "console",
        help="Open the safe Fulilian command console",
        description=(
            "Open a curated Fulilian command REPL. This is not a raw shell and "
            "does not expose the full Fulilian CLI."
        ),
    )
    console_parser.set_defaults(func=cmd_console)
