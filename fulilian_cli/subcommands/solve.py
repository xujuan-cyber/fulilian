"""``fulilian solve`` / ``solve-all`` command parsers.

CTF first-class commands — solve a single challenge, or batch-solve a
platform.  Registered into the FuLiLian command tree from ``main()``.
"""

from __future__ import annotations

from typing import Callable


def build_solve_parser(subparsers, *, cmd_solve: Callable, cmd_solve_all: Callable) -> None:
    """Attach the ``solve`` and ``solve-all`` subcommands to ``subparsers``."""
    solve_parser = subparsers.add_parser(
        "solve",
        help="Solve a single CTF challenge",
        description="Solve a single CTF challenge with verification gate and knowledge support.",
    )
    solve_parser.add_argument("id", help="Challenge ID or directory")
    solve_parser.add_argument("--model", help="Override solver model")
    solve_parser.add_argument("--architect-model", help="Expensive model for planning (Architect mode)")
    solve_parser.add_argument("--executor-model", help="Cheap model for execution (Architect mode)")
    solve_parser.add_argument("--race", action="store_true", help="Multi-model race mode")
    solve_parser.add_argument("--race-models", default=None,
                              help="Comma-separated models for --race "
                                   "(default: ctf.race_models config or model.default)")
    solve_parser.add_argument("--multi-agent", action="store_true", help="Multi-agent mode")
    solve_parser.add_argument("--boomerang", action="store_true",
                              help="Round-trip multi-agent exploration")
    solve_parser.add_argument("--max-rounds", type=int, default=2,
                              help="Maximum Boomerang exploration rounds")
    solve_parser.add_argument("--directions", default=None,
                              help="Comma-separated exploration directions for --multi-agent "
                                   "(default: blackboard open intents or built-in defaults)")
    solve_parser.add_argument("--explorers", type=int, default=None,
                              help="Number of explorer agents for --multi-agent (default: 4)")
    solve_parser.add_argument("-p", "--print", dest="oneshot", action="store_true",
                              help="Non-interactive mode (print result)")
    solve_parser.add_argument("--json", action="store_true",
                              help="Output structured JSON progress")
    solve_parser.add_argument("--rpc", action="store_true",
                              help="Serve newline-delimited JSON-RPC requests")
    solve_parser.set_defaults(func=cmd_solve)

    solve_all_parser = subparsers.add_parser(
        "solve-all",
        help="Batch-solve challenges on a platform",
        description="Batch-solve multiple CTF challenges with automatic scheduling.",
    )
    solve_all_parser.add_argument("platform", help="Platform name (e.g. ctfd instance URL or ID)")
    solve_all_parser.add_argument("--model", help="Override solver model")
    solve_all_parser.add_argument("--limit", type=int, help="Max challenges to attempt")
    solve_all_parser.add_argument("--workers", type=int,
                                  help="Max parallel solver processes (default: 3)")
    solve_all_parser.add_argument("--probe-timeout", type=int,
                                  help="Probe timeout in seconds (default: 60)")
    solve_all_parser.add_argument("--timebox", type=int,
                                  help="Override timebox in seconds (single tier, for testing)")
    solve_all_parser.add_argument("--max-attempts", type=int,
                                  help="Max attempts per challenge incl. harvest re-runs (default: 5)")
    solve_all_parser.add_argument("--max-tokens", type=int,
                                  help="Stop a solver when accumulated token usage exceeds this (default: unlimited — solve until flag found)")
    solve_all_parser.add_argument("--max-no-output-rounds", type=int,
                                  help="Stop after N consecutive rounds with no new blackboard Fact (default: 7)")
    solve_all_parser.add_argument("--max-variant-failures", type=int,
                                  help="Force-switch attack class after N failed variants (default: 7)")
    solve_all_parser.add_argument("--max-turns", type=int,
                                  help="Cap solver conversation turns for ALL challenges (default: unlimited)")
    solve_all_parser.add_argument("--no-stop-loss", action="store_true",
                                  help="Disable 4-dimension stop-loss governance")
    solve_all_parser.add_argument("--json", action="store_true",
                                  help="Output structured JSON progress")
    solve_all_parser.set_defaults(func=cmd_solve_all)
