"""PwnSpecialist — PWN 二进制漏洞利用专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class PwnSpecialist(BaseSpecialist):
    """PWN 类别专家：checksec / gdb / pwntools / ropper / radare2。"""

    def __init__(self) -> None:
        self.category = "pwn"
        self.tools = ["checksec", "gdb", "pwntools", "ropper", "radare2"]
        self.workflow = (
            "1. checksec: check binary protections (canary, PIE, NX, RELRO)\n"
            "2. analyze: disassemble with radare2 / gdb, identify vulnerable functions\n"
            "3. exploit: build ROP chain / ret2libc / shellcode with pwntools\n"
            "4. debug: verify with gdb, adjust offsets and leak addresses"
        )
        super().__init__()