"""RevSpecialist — REV 逆向工程专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class RevSpecialist(BaseSpecialist):
    """REV 类别专家：radare2 / rizin / strings / ghidra-headless。"""

    def __init__(self) -> None:
        self.category = "rev"
        self.tools = ["radare2", "rizin", "strings", "ghidra-headless"]
        self.workflow = (
            "1. strings: extract embedded strings and hints\n"
            "2. analysis: disassemble with radare2/rizin, identify key logic\n"
            "3. deobfuscate: unpack, deobfuscate, or decompile as needed\n"
            "4. reconstruct: recover algorithm, extract flag or key"
        )
        self.asset_discipline = (
            "Before solving, check existing assets first:\n"
            "- search(query, category='reverse') and search_snippets(query, category='reverse') from fulilian_ctf/knowledge_retriever.py for similar past write-ups and exp snippets (note: the knowledge base uses 'reverse', not 'rev')\n"
            "- skills/ctf-cards/scripts/ROUTE.md may point to a ready-made script (decoders, deobfuscation helpers); adapt it instead of writing from scratch"
        )
        super().__init__()