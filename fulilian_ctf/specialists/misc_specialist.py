"""MiscSpecialist — MISC 杂项专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class MiscSpecialist(BaseSpecialist):
    """MISC 类别专家：通用流程 + 多工具组合。"""

    def __init__(self) -> None:
        self.category = "misc"
        self.tools = [
            "file", "strings", "binwalk", "steghide", "exiftool",
            "foremost", "pcap", "python", "z3",
        ]
        self.workflow = (
            "1. inspect: examine provided files, check metadata, strings, file type\n"
            "2. decode: test common encodings (base64, hex, rot, etc.)\n"
            "3. extract: carve hidden data, solve puzzles, automate analysis\n"
            "4. conclude: synthesize findings, apply domain-specific techniques"
        )
        self.asset_discipline = (
            "Before solving, check existing assets first:\n"
            "- similar past write-ups and exp snippets are ALREADY injected into your context (see 知识卡 /\n"
            "  相似历史 WP 参考); misc has no fixed category, so also check the 专题速查 pointers below\n"
            "- ~/.fulilian/skills/ctf-cards/scripts/ROUTE.md indexes many encoding/puzzle/conversion scripts; adapt one instead of writing from scratch"
        )
        super().__init__()