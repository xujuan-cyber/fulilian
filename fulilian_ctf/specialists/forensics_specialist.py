"""ForensicsSpecialist — FORENSICS 数字取证专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class ForensicsSpecialist(BaseSpecialist):
    """FORENSICS 类别专家：volatility3 / sleuthkit / foremost / binwalk / steghide。"""

    def __init__(self) -> None:
        self.category = "forensics"
        self.tools = ["volatility3", "sleuthkit", "foremost", "binwalk", "steghide"]
        self.workflow = (
            "1. identify: determine file type, check for hidden data (binwalk, foremost)\n"
            "2. extract: carve files, recover deleted data, unpack firmware\n"
            "3. memory: analyze memory dump with volatility3 if applicable\n"
            "4. decode: extract hidden messages (steganography, metadata, LSB)"
        )
        super().__init__()