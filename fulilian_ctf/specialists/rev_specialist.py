"""RevSpecialist — REV 逆向工程专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class RevSpecialist(BaseSpecialist):
    """REV 类别专家：radare2 / rizin / strings / ghidra-headless。"""

    def __init__(self) -> None:
        # 知识层词表（知识卡/knowledge.db 的 category 列都是 "reverse"）；
        # 注册表键仍是 "rev"，两者由 SpecialistFactory.canonical_category 收口。
        self.category = "reverse"
        self.tools = ["radare2", "rizin", "strings", "ghidra-headless"]
        self.workflow = (
            "1. strings: extract embedded strings and hints\n"
            "2. analysis: disassemble with radare2/rizin, identify key logic\n"
            "3. deobfuscate: unpack, deobfuscate, or decompile as needed\n"
            "4. reconstruct: recover algorithm, extract flag or key"
        )
        self.asset_discipline = (
            "Before solving, check existing assets first:\n"
            "- similar past write-ups and exp snippets for this category are ALREADY injected into your\n"
            "  context (see 知识卡 / 相似历史 WP 参考); read them before writing anything from scratch\n"
            "- ~/.fulilian/skills/ctf-cards/scripts/ROUTE.md may point to a ready-made script (decoders, deobfuscation helpers); adapt it instead of writing from scratch"
        )
        super().__init__()