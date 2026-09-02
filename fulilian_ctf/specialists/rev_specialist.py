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
        super().__init__()