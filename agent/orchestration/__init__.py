"""Orchestration subsystem (phase 1: contracts, state machine, config, schema).

Layering rule: nothing in this package may import from ``tools.*``. The engine
must be usable without the legacy delegation stack; the dependency points the
other way (``tools.delegate_tool`` will call into this package, never reverse).
"""

__all__: list[str] = []
