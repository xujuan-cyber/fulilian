"""``fulilian ctfd`` command parser (F3-011 / F3-012).

CTFd platform integration: list challenges, submit flags, sync a local
manifest for ``solve-all``, create the polling cron job, and run the
bundled stdio MCP server.
"""

from __future__ import annotations

from typing import Callable


def build_ctfd_parser(subparsers, *, cmd_ctfd: Callable) -> None:
    """Attach the ``ctfd`` subcommand to ``subparsers``."""
    ctfd_parser = subparsers.add_parser(
        "ctfd",
        help="CTFd platform integration (list / submit / sync / poll / serve-mcp)",
        description=(
            "CTFd platform integration: list challenges, submit flags, "
            "sync a local manifest for solve-all, create a polling cron "
            "job, or run the bundled stdio MCP server."
        ),
    )
    ctfd_subparsers = ctfd_parser.add_subparsers(dest="ctfd_action")

    p = ctfd_subparsers.add_parser("list", help="List challenges from a CTFd platform")
    p.add_argument("base_url", help="CTFd base URL (e.g. https://ctf.example.com)")
    p.add_argument("--api-key", default=None, help="CTFd API token")
    p.set_defaults(func=cmd_ctfd)

    p = ctfd_subparsers.add_parser("submit", help="Submit a flag to a challenge")
    p.add_argument("base_url", help="CTFd base URL")
    p.add_argument("challenge_id", type=int, help="CTFd challenge ID")
    p.add_argument("flag", help="Flag to submit")
    p.add_argument("--api-key", default=None, help="CTFd API token")
    p.set_defaults(func=cmd_ctfd)

    p = ctfd_subparsers.add_parser(
        "sync", help="Sync challenges into a local manifest for solve-all"
    )
    p.add_argument("base_url", help="CTFd base URL")
    p.add_argument("out_dir", help="Output platform directory")
    p.add_argument("--api-key", default=None, help="CTFd API token")
    p.set_defaults(func=cmd_ctfd)

    p = ctfd_subparsers.add_parser(
        "poll", help="Poll for new challenges (prints new ones, updates state file)"
    )
    p.add_argument("base_url", help="CTFd base URL")
    p.add_argument("platform_dir", help="Platform directory (state: poll-state.json)")
    p.add_argument("--api-key", default=None, help="CTFd API token")
    p.set_defaults(func=cmd_ctfd)

    p = ctfd_subparsers.add_parser(
        "poll-job", help="Create a recurring cron job that polls CTFd and spawns solvers"
    )
    p.add_argument("base_url", help="CTFd base URL")
    p.add_argument("platform_dir", help="Platform directory for manifests/state")
    p.add_argument("--api-key", default=None, help="CTFd API token")
    p.add_argument("--schedule", default="every 5m",
                    help="Cron schedule (default: every 5m)")
    p.set_defaults(func=cmd_ctfd)

    p = ctfd_subparsers.add_parser(
        "serve-mcp", help="Run the bundled stdio MCP server (F3-012)"
    )
    p.add_argument("--base-url", default=None,
                    help="CTFd base URL (default: $CTFD_BASE_URL)")
    p.add_argument("--api-key", default=None,
                    help="CTFd API token (default: $CTFD_API_KEY)")
    p.set_defaults(func=cmd_ctfd)
