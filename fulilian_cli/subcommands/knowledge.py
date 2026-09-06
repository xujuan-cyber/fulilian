"""``fulilian knowledge`` command parser.

Manages the CTF knowledge base: import, query, and list knowledge cards.
"""

from __future__ import annotations

from typing import Callable


def build_knowledge_parser(subparsers, *, cmd_knowledge: Callable) -> None:
    """Attach the ``knowledge`` subcommand to ``subparsers``."""
    knowledge_parser = subparsers.add_parser(
        "knowledge",
        help="Manage CTF knowledge base",
        description="Import, query, and list CTF knowledge cards and references.",
    )
    knowledge_subparsers = knowledge_parser.add_subparsers(dest="knowledge_action")

    # knowledge query
    query_parser = knowledge_subparsers.add_parser(
        "query",
        help="Query the knowledge base",
    )
    query_parser.add_argument("query", nargs="+", help="Search terms")
    query_parser.add_argument("--limit", type=int, default=5, help="Max results")
    query_parser.add_argument("--category", choices=["web", "crypto", "reverse", "pwn", "forensics", "misc"],
                              help="Filter by category")

    # knowledge import
    import_parser = knowledge_subparsers.add_parser(
        "import",
        help="Import Des-CTF-Knowledge into FTS5 index",
    )
    import_parser.add_argument("--source", help="Source path (default: Des-CTF-Knowledge)")
    import_parser.add_argument("--force", action="store_true",
                               help="Force rebuild even if index exists")

    # knowledge list
    list_parser = knowledge_subparsers.add_parser(
        "list",
        help="List knowledge cards and index status",
    )
    list_parser.add_argument("--category", choices=["web", "crypto", "reverse", "pwn", "forensics", "misc"],
                             help="Filter by category")

    # knowledge stats
    stats_parser = knowledge_subparsers.add_parser(
        "stats",
        help="Show experiential learning statistics",
    )

    # knowledge cards-sync
    cards_sync_parser = knowledge_subparsers.add_parser(
        "cards-sync",
        help="Generate candidate file of techniques (from experiential learning) "
             "for knowledge cards; edit it, then re-run with --apply to merge",
    )
    cards_sync_parser.add_argument(
        "--apply", action="store_true",
        help="Merge remaining candidate blocks in the file into knowledge cards",
    )
    cards_sync_parser.add_argument(
        "--out",
        help="Candidate file path (default: ~/Exchange/ctf-知识卡候选.md)",
    )

    knowledge_parser.set_defaults(func=cmd_knowledge)