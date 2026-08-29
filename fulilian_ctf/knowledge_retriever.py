"""Des-CTF-Knowledge FTS5 检索桥接 (F3-002).

把 Des-CTF-Knowledge 的 1156 篇 WP Markdown 文件导入 SQLite FTS5，
支持全文搜索（中英文）、分类过滤、BM25 排序。

知识库结构：
- KB_PATH = /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/
  - CTF大赛WP集合/articles/  — 1156 篇 WP（主来源）
  - WP汇总/               — 分类 WP（文件包含、SSTI 等）
  - 根目录 *.md           — 知识文章（命令执行、SQL、SSRF 等）
  - 根目录 *.idx.md       — 分段索引（跳过）

FTS5 使用 trigram tokenizer 兼顾中英文搜索。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

from fulilian_constants import FULILIAN_HOME

# ── 路径常量 ─────────────────────────────────────────────────────────────

KB_PATH = Path("/home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main")
DB_PATH = FULILIAN_HOME / "knowledge.db"

# 需要跳过的文件（非正文）。
# 注意：build_index 只 rglob("*.md")，因此只保留 .md 条目——
# "LICENSE"、".gitignore" 等非 .md 文件永远不会被遍历到（死条目已移除）。
SKIP_FILES = {
    "AI-SEARCH-INDEX.md",
    "README.md",
    "CHANGELOG.md",
    "PAYLOAD-CHEATSHEET.md",
    "SCRIPTS-INDEX.md",
}
# 分段索引文件后缀名。注意不能用 Path.suffix 判断：
# Path("命令执行.idx.md").suffix == ".md"，必须用 name.endswith(".idx.md")。
IDX_SUFFIX = ".idx.md"

# 分类关键词表（从标题/内容推断分类的权威词）
CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "web": frozenset({
        "sql", "xss", "ssti", "csrf", "ssrf", "upload", "file include",
        "file inclusion", "lfi", "rfi", "command injection", "rce",
        "deserialization", "php", "jwt", "oauth", "cors", "apache",
        "nginx", "tomcat", "web", "http", "cookie", "session",
        "cve-", "poc", "bypass", "waf", "webshell", "phpmyadmin",
        "shiro", "log4j", "fastjson", "struts", "spring",
        "xxe", "template injection", "path traversal",
        "directory traversal", "race condition", "jndi", "ldap",
        "注入", "上传", "绕过", "文件包含", "命令执行", "反序列化",
        "跨站", "越权", "未授权", "前端", "后端", "cms", "wordpress",
    }),
    "crypto": frozenset({
        "rsa", "aes", "des", "ecc", "md5", "sha", "hash", "cipher",
        "encrypt", "decrypt", "plaintext", "ciphertext", "xor",
        "lcg", "lfsr", "coppersmith", "wiener", "boneh", "diffie",
        "hellman", "elgamal", "dlog", "discrete log", "padding",
        "oracle", "ecb", "cbc", "ctr", "gcm", "block cipher",
        "stream cipher", "vigenere", "caesar", "substitution",
        "transposition", "classical", "crypto", "base64", "base32",
        "base16", "hex", "encode", "decode", "otp", "rainbow",
        "素数", "分解", "加密", "密码", "编码", "古典", "模",
    }),
    "reverse": frozenset({
        "reverse", "reverse engineering", "reversing", "crack", "keygen",
        "obfuscation", "obfuscate", "deobfuscate", "decompile",
        "disassemble", "anti-debug", "anti-debugging", "packer",
        "unpack", "upx", "vmp", "themida", "ollvm", "control flow",
        "flattening", "android", "apk", "dex", "smali", "frida",
        "xposed", "jni", "native", "so file", "elf", "pe",
        "ida pro", "ghidra", "gdb", "radare2", "angr", "z3",
        "symbolic execution", "taint", "动态分析", "静态分析",
        "逆向", "破解", "脱壳", "反调试", "花指令", "算法还原",
    }),
    "pwn": frozenset({
        "pwn", "exploit", "exploitation", "buffer overflow", "bof",
        "stack overflow", "heap overflow", "heap spray", "use after free",
        "uaf", "double free", "tcache", "fastbin", "unsorted bin",
        "house of ", "ret2libc", "ret2win", "ret2shellcode", "rop",
        "srop", "brop", "format string", "fmtstr", "integer overflow",
        "off-by-one", "null byte", "canary", "pie", "aslr", "nx",
        "seccomp", "sandbox", "orw", "shellcode", "one_gadget",
        "execve", "got", "plt", "libc", "fsop", "io_file",
        "栈溢出", "堆溢出", "格式化字符串", "沙箱", "逃逸",
        "漏洞利用",
    }),
    "forensics": frozenset({
        "forensic", "forensics", "memory", "volatility", "pcap",
        "pcapng", "wireshark", "tshark", "tcpdump", "network",
        "traffic", "packet", "disk", "image", "disk image",
        "encase", "ftk", "sleuth kit", "autopsy", "steganography",
        "stego", "lsb", "exif", "metadata", "binwalk", "foremost",
        "file carving", "carving", "ntfs", "mft", "ads", "registry",
        "event log", "prefetch", "jump list", "lnk", "shellbags",
        "取证", "隐写", "流量", "内存", "磁盘", "镜像", "恢复",
        "删除", "痕迹", "日志", "数据恢复",
    }),
    "misc": frozenset({
        "misc", "miscellaneous", "osint", "social engineering",
        "stego", "steganography", "brainfuck",
        "jsfuck", "pokemon", "emoji", "qr code", "barcode",
        "programming", "algorithm", "automation", "captcha",
        "blockchain", "smart contract", "ethereum", "solidity",
        "iot", "firmware", "modbus", "mqtt", "coap",
        "杂项", "编程", "社工", "社会工程",
        "脑洞", "脑洞题", "图片隐写", "音频隐写",
    }),
}

# 目录名 → 分类映射（从路径直接推断）
DIR_CATEGORY_MAP: dict[str, str] = {
    "web": "web",
    "crypto": "crypto",
    "reverse": "reverse",
    "pwn": "pwn",
    "forensics": "forensics",
    "misc": "misc",
    "代码审计": "web",
    "文件包含": "web",
    "文件上传": "web",
    "sql": "web",
    "xss": "web",
    "ssti": "web",
    "nodejs": "web",
    "ssrf": "web",
    "php": "web",
    "jwt": "web",
    "rsa": "crypto",
    "aes": "crypto",
    "古典密码": "crypto",
    "编码": "misc",
    "隐写": "forensics",
    "图片隐写": "forensics",
    "音频隐写": "forensics",
    "流量": "forensics",
    "内存取证": "forensics",
    "取证": "forensics",
    "堆": "pwn",
    "栈": "pwn",
    "格式化字符串": "pwn",
    "逆向": "reverse",
    "crack": "reverse",
    "脱壳": "reverse",
    "android": "reverse",
    "apk": "reverse",
    "物联网": "misc",
    "iot": "misc",
    "osint": "misc",
    "区块链": "misc",
    "blockchain": "misc",
    "编程": "misc",
    "脑洞": "misc",
}

# FTS5 建表 SQL（trigram tokenizer 支持中文）
CREATE_TABLE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS writeups USING fts5(
    title,
    category,
    content,
    source_path UNINDEXED,
    tokenize='trigram'
);
"""

# 兼容旧版 schema（unicode61），如果表已存在且是 unicode61 则重建
LEGACY_TABLE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS writeups USING fts5(
    title,
    category,
    content,
    source_path UNINDEXED
);
"""


# ── 分类推断 ────────────────────────────────────────────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _kw_hit(text: str, kw: str) -> bool:
    """关键词命中判定。

    - 含 CJK 的关键词：子串匹配（中文无词边界）。
    - 纯 ASCII 关键词：词边界匹配，避免 "dex" 误命中 "index"、"sql" 误命中 "mysql"。
    - 关键词以非字母数字结尾（如 "cve-"）：只做起始边界，允许后面跟版本号。
    """
    if not kw:
        return False
    if _CJK_RE.search(kw):
        return kw in text
    pattern = re.escape(kw)
    if kw[-1].isalnum():
        pattern += r"(?![A-Za-z0-9])"
    return re.search(r"(?<![A-Za-z0-9])" + pattern, text, re.IGNORECASE) is not None


def _guess_category(path: Path, content: str = "") -> str:
    """从路径+内容推断题目分类。

    优先级：目录名 > 文件名 > 内容关键词。
    """
    text = str(path).replace("\\", "/").lower()
    stem = path.stem.lower()

    # 1) 目录名/文件名匹配（DIR_CATEGORY_MAP 键，词边界命中）
    for keyword, cat in DIR_CATEGORY_MAP.items():
        if _kw_hit(text, keyword):
            return cat

    # 2) 内容关键词匹配（取前 200 字符 + 文件名）
    head = content[:2000].lower()
    scores: dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if _kw_hit(head, kw) or _kw_hit(stem, kw))
        if score > 0:
            scores[cat] = score

    if scores:
        return max(scores, key=scores.get)

    return "misc"


# ── 索引构建 ────────────────────────────────────────────────────────────


def build_index(force: bool = False) -> int:
    """构建 FTS5 索引。

    遍历 Des-CTF-Knowledge 知识库，将所有 .md 正文导入 SQLite FTS5。
    如果索引已存在且未指定 force，跳过不重建。

    Args:
        force: 是否强制重建（清空已有索引）。

    Returns:
        int: 导入的文档数。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    # 检查是否已有索引（表是否存在且非空）
    if not force:
        try:
            existing = conn.execute(
                "SELECT count(*) FROM writeups"
            ).fetchone()[0]
            if existing > 0:
                conn.close()
                return existing
        except sqlite3.OperationalError:
            pass  # 表不存在，继续创建

    # 重建索引
    try:
        conn.execute("DROP TABLE IF EXISTS writeups")
    except sqlite3.OperationalError:
        pass
    conn.execute(CREATE_TABLE_SQL)

    count = 0
    errors = 0

    for md_file in sorted(KB_PATH.rglob("*.md")):
        # 跳过索引文件
        if md_file.name in SKIP_FILES:
            continue
        if md_file.name.endswith(IDX_SUFFIX):
            continue
        # 跳过 .git 目录内的文件
        if ".git" in md_file.parts:
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            if not content.strip():
                continue

            title = md_file.stem
            category = _guess_category(md_file, content)
            # 限制 content 长度（FTS5 文档大小限制通常在 1GB 内，但保持合理）
            content_trunc = content[:200_000]

            conn.execute(
                "INSERT INTO writeups (title, category, content, source_path) "
                "VALUES (?, ?, ?, ?)",
                (title, category, content_trunc, str(md_file)),
            )
            count += 1
        except Exception:  # noqa: BLE001
            errors += 1
            continue

    conn.commit()
    conn.close()

    if errors:
        print(f"[knowledge] build_index: {count} indexed, {errors} skipped (errors)")

    return count


# ── 检索 ────────────────────────────────────────────────────────────────


def search(
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
    auto_build: bool = True,
) -> list[dict]:
    """FTS5 全文搜索。

    Args:
        query: 搜索关键词（FTS5 MATCH 语法，支持短语和布尔操作符）。
        category: 可选分类过滤（web/crypto/reverse/pwn/forensics/misc）。
        limit: 返回结果数（默认 5）。
        auto_build: 索引不存在时自动构建（默认 True）。

    Returns:
        list[dict]: [{"title", "category", "snippet", "source_path"}, ...]
    """
    if not DB_PATH.exists() or _is_empty_index():
        if auto_build:
            build_index()
        else:
            return []

    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            # FTS5 trigram 查询：对查询词做 trigram 化处理
            # trigram tokenizer 会自动将查询拆成 3-gram，所以直接传原始查询
            sql = """
                SELECT title, category,
                       snippet(writeups, 2, '[', ']', '...', 15) AS snip,
                       source_path
                FROM writeups
                WHERE writeups MATCH ?
            """
            params: list = [query]

            if category:
                sql += " AND category = ?"
                params.append(category)

            sql += " ORDER BY bm25(writeups, 10.0, 5.0, 2.0, 1.0) LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
        finally:
            # 无论 FTS5 查询是否抛错都关闭连接，再走 LIKE 回退，避免连接泄漏
            conn.close()
    except sqlite3.OperationalError:
        # FTS5 语法错误（如查询含特殊字符），回退到 LIKE 搜索
        return _fallback_like_search(query, category, limit)

    return [
        {
            "title": r[0],
            "category": r[1],
            "snippet": r[2],
            "source_path": r[3],
        }
        for r in rows
    ]


def _is_empty_index() -> bool:
    """检查索引是否为空。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        count = conn.execute("SELECT count(*) FROM writeups").fetchone()[0]
        conn.close()
        return count == 0
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return True


def _fallback_like_search(
    query: str, category: Optional[str] = None, limit: int = 5
) -> list[dict]:
    """FTS5 语法错误时的 LIKE 回退搜索。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        sql = r"""
            SELECT title, category,
                   substr(content, 1, 200) AS snip,
                   source_path
            FROM writeups
            WHERE content LIKE ? ESCAPE '\'
        """
        # 转义 LIKE 通配符，防止 query 中的 % 和 _ 被当作通配符
        escaped = (
            query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        params = [f"%{escaped}%"]

        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()

        return [
            {
                "title": r[0],
                "category": r[1],
                "snippet": r[2][:200] + ("..." if len(r[2]) > 200 else ""),
                "source_path": r[3],
            }
            for r in rows
        ]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def get_index_stats() -> dict:
    """获取索引统计信息。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        total = conn.execute("SELECT count(*) FROM writeups").fetchone()[0]
        cats = conn.execute(
            "SELECT category, count(*) FROM writeups GROUP BY category ORDER BY 2 DESC"
        ).fetchall()
        conn.close()
        return {
            "total_docs": total,
            "by_category": dict(cats),
            "db_path": str(DB_PATH),
        }
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return {"total_docs": 0, "by_category": {}, "db_path": str(DB_PATH)}


def list_categories() -> list[str]:
    """列出知识库中存在的分类。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute(
            "SELECT DISTINCT category FROM writeups ORDER BY category"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


__all__ = [
    "KB_PATH",
    "DB_PATH",
    "build_index",
    "search",
    "get_index_stats",
    "list_categories",
    "_guess_category",
]