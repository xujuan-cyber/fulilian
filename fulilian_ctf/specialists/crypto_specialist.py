"""CryptoSBeSpecialist — CRYPTO 密码学专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class CryptoSBeSpecialist(BaseSpecialist):
    """CRYPTO 类别专家：sagemath / RsaCtfTool / z3 / hashcat。"""

    def __init__(self) -> None:
        self.category = "crypto"
        self.tools = ["sagemath", "RsaCtfTool", "z3", "hashcat"]
        self.workflow = (
            "1. identify: determine cipher type (RSA/AES/classical/encoding)\n"
            "2. analyze: examine key parameters, look for weak primes, small e, etc.\n"
            "3. compute: use sagemath for modular arithmetic, z3 for constraint solving\n"
            "4. decode: apply appropriate decoding/decryption, recover plaintext"
        )
        self.asset_discipline = (
            "Before solving, check existing assets first:\n"
            "- similar past write-ups and exp snippets for this category are ALREADY injected into your\n"
            "  context (see 知识卡 / 相似历史 WP 参考); read them before writing anything from scratch\n"
            "- ~/.fulilian/skills/ctf-cards/scripts/ROUTE.md may point to a ready-made script for this cipher/scenario; adapt it instead of writing from scratch"
        )
        super().__init__()