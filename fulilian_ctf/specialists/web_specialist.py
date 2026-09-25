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
        self.asset_discipline = (
            "1. Template match — ~/.fulilian/skills/ctf-cards/templates/ has 8 web templates, pick by trigger condition:\n"
            "   - web_php_filter_chain.py: include/require param fully controllable, php://filter iconv chain turns LFI into RCE (PHP 7.0.29+/7.2.4+)\n"
            "   - web_ssti_probe.py: param rendered by a template engine; multi-engine probe ({{7*7}}/${7*7}/<%=7*7%>) then engine-specific RCE\n"
            "   - web_jwt_kit.py: JWT found; alg=none / HS256 weak-key crack / kid injection subcommands\n"
            "   - web_ssrf_gopher.py: SSRF with gopher support; inner Redis (webshell/crontab) or FastCGI 9000 RCE payload builder\n"
            "   - web_sqlmap_kit.py: injection point located; sqlmap command cheat-sheet + boolean/time blind-union script\n"
            "   - web_phar_gen.py: file functions with controllable path + known POP chain; craft phar:// deserialization file\n"
            "   - web_oob_rce.py: command injection/RCE without echo; DNSLog/HTTP exfil variants + webshell drop\n"
            "   - web_pickle_pt.py: pickle.loads on user data, or Node prototype pollution via merge/deepCopy/lodash.set\n"
            "2. History lookup — similar past write-ups, exp snippets and technique-tagged matches for this\n"
            "   category are ALREADY injected into your context (see 知识卡 / 专题速查 / 相似历史 WP 参考);\n"
            "   read them before writing anything from scratch (do not try to call Python search() yourself)\n"
            "3. Ready-made tools — ~/.fulilian/skills/ctf-cards/scripts/ROUTE.md maps scenarios to battle-tested scripts\n"
            "Priority: template > snippet reference > adapt script > write from scratch.\n"
            "When using a template: Read its header docstring first to confirm applicability (target language/runtime version,\n"
            "network egress, prerequisites), then edit only the TODO parameter block at the top. Paths above are under FULILIAN_HOME (~/.fulilian)."
        )
        super().__init__()