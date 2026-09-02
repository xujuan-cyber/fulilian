"""WebSpecialist — WEB 安全专家。"""

from __future__ import annotations

from .base import BaseSpecialist


class WebSpecialist(BaseSpecialist):
    """WEB 类别专家：curl / nmap / gobuster / ffuf / sqlmap。"""

    def __init__(self) -> None:
        self.category = "web"
        self.tools = ["curl", "nmap", "gobuster", "ffuf", "sqlmap"]
        self.workflow = (
            "1. recon: enumerate endpoints with gobuster/ffuf, scan ports with nmap\n"
            "2. analyze: inspect HTTP requests, cookies, parameters with curl\n"
            "3. exploit: test for SQL injection, XSS, SSTI, SSRF, file inclusion\n"
            "4. escalate: chain vulnerabilities, extract flag from admin/internal areas"
        )
        super().__init__()