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
        self.asset_discipline = (
            "Before writing any exploit, run the three asset checks:\n"
            "1. Template match — skills/ctf-cards/templates/ has 8 pwn templates, pick by trigger condition:\n"
            "   - pwn_ret2libc.py: stack overflow + NX on, leak GOT -> libc base -> system('/bin/sh')\n"
            "   - pwn_tcache_poison.py: menu heap with UAF/double-free, glibc >= 2.26 tcache poisoning (safe-linking branch for >= 2.32)\n"
            "   - pwn_srop.py: 64-bit tiny binary / payload length limited, pop rax(15)+syscall gadgets, one stack leak\n"
            "   - pwn_orw.py: seccomp bans execve; pure open/read/write shellcode reads /flag\n"
            "   - pwn_fmtstr.py: printf takes user input as format string; arbitrary write / GOT leak, auto offset (32/64-bit)\n"
            "   - pwn_ret2csu_stack.py: 64-bit glibc <= 2.33, overflow too short for full ROP or need rdx; stack pivot to bss\n"
            "   - pwn_fsop_apple2.py: glibc >= 2.34 (no __free_hook/__malloc_hook), heap UAF/edit -> house of apple2\n"
            "   - pwn_heap_menu.py: any add/del/edit/show menu heap challenge; scaffold to confirm the bug first, then chain into tcache_poison/fsop_apple2\n"
            "2. History lookup — from fulilian_ctf/knowledge_retriever.py: search_snippets(query, category='pwn') for exp snippets,\n"
            "   search(query, category='pwn') for similar past write-ups, similar_by_technique(tags) for technique-tagged matches\n"
            "3. Ready-made tools — skills/ctf-cards/scripts/ROUTE.md maps scenarios to battle-tested scripts\n"
            "Priority: template > snippet reference > adapt script > write from scratch.\n"
            "When using a template: Read its header docstring first to confirm applicability (glibc version, protections,\n"
            "interaction protocol), then edit only the TODO parameter block at the top. Paths are relative to the repo root."
        )
        super().__init__()