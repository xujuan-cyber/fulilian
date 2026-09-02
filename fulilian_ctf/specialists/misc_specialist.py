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
        super().__init__()