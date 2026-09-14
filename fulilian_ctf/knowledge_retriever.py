"""Des-CTF-Knowledge FTS5 检索桥接 (F3-002).

把 Des-CTF-Knowledge 的 1156 篇 WP Markdown 文件导入 SQLite FTS5，
支持全文搜索（中英文）、分类过滤、BM25 排序。

知识库结构（KB_PATH 由 _resolve_kb_path() 解析，见下）：
- CTF大赛WP集合/articles/  — 1156 篇 WP（主来源）
- WP汇总/                  — 分类 WP（文件包含、SSTI 等）
- 根目录 *.md              — 知识文章（命令执行、SQL、SSRF 等）
- 根目录 *.idx.md          — 分段索引（跳过）

FTS5 使用 trigram tokenizer 兼顾中英文搜索。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

from fulilian_constants import FULILIAN_HOME

# ── 路径常量 ─────────────────────────────────────────────────────────────

# 随源码树分发的 KB 快照：<repo>/ctf-knowledge/。与 skills/ctf-cards/
# （技能卡）同名但不同物——这里是 WP 语料本体。
BUNDLED_KB_PATH = Path(__file__).resolve().parent.parent / "ctf-knowledge"

_KB_FALLBACK_PATHS = (
    # 上游 Des-CTF-Knowledge 的克隆目录（历史位置，仅作最后兜底）
    Path.home() / "Des-CTF-Knowledge" / "Des-CTF-Knowledge-main",
)


# ── P4.2: sanitize 下沉 —— search() 是所有调用方共用的唯一收口 ──────────
# 与 knowledge._sanitize_query 同口径（后者现为兼容壳，委托到这里）：
# 题面/payload 里随手就有的引号、括号、裸操作符词（admin' OR 1=1）进
# MATCH 是语法错误或语义错乱。sanitize 放在 search() 内部而不是让每个
# 调用方自己记得洗，"不洗就崩"从调用方契约变成检索器不变量。
# 对已清洗形态（"tok1" OR "tok2"）幂等：token 再提取结果不变。
_MAX_QUERY_TOKENS = 8     # 查询最多取前 N 个 token
_SANITIZE_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_MATCH_OPERATOR_WORDS = {"and", "or", "not", "near"}


def sanitize_match_query(text: str) -> str:
    """把任意文本清洗成 FTS5 MATCH 友好的查询串。

    只保留字母数字/下划线/中文字符 token（去掉标点、引号等会触发 FTS5
    语法错误的字符），丢 FTS 保留操作符词，取前 _MAX_QUERY_TOKENS 个，
    用 " OR " 连接 —— 多词隐式 AND 太严格（任一词不命中即空结果），OR
    提高召回，排序仍由 BM25 兜底。清洗后为空返回空串。
    """
    if not text:
        return ""
    tokens = _SANITIZE_TOKEN_RE.findall(text)
    tokens = [t for t in tokens if t.lower() not in _MATCH_OPERATOR_WORDS]
    tokens = tokens[:_MAX_QUERY_TOKENS]
    if not tokens:
        return ""
    # 每个 token 加双引号短语包裹，token 本身已无引号字符（正则只留
    # 字母数字/下划线/中文），杜绝其余边界字符触发 MATCH 语法错误。
    return " OR ".join(f'"{t}"' for t in tokens)


def _resolve_kb_path() -> Path:
    """解析知识库根目录。

    优先级：环境变量 FULILIAN_CTF_KB_PATH > ~/.fulilian/ctf-knowledge >
    随源码分发的 <repo>/ctf-knowledge > 已知的 Des-CTF-Knowledge 克隆位置。

    ``~/.fulilian/ctf-knowledge`` 是活库（做题写回的 WP 落在它的
    ``self-solved/``），随源码分发的那份是快照，故排在其后。放它在克隆
    位置之前，是为了让新克隆的机器不必先手工复制 41M 语料。默认目录不
    存在时回退到仓库路径，避免 build_index 对着不存在的目录静默产出 0 条、
    把已有索引清空。
    """
    env = os.environ.get("FULILIAN_CTF_KB_PATH", "").strip()
    if env:
        return Path(env)
    default = FULILIAN_HOME / "ctf-knowledge"
    if default.exists():
        return default
    for cand in (BUNDLED_KB_PATH, *_KB_FALLBACK_PATHS):
        if cand.is_dir():
            return cand
    return default


KB_PATH = _resolve_kb_path()

# Obsidian 知识库（唯一知识写入源）。2026-09-06 起直接索引 vault，
# 不再经本地镜像目录（镜像已删除，写入一律进 vault）。
# 路径可经 FULILIAN_OBSIDIAN_VAULT 覆盖；默认值中的 vault 目录名是
# 用户自己的资产命名（不在本项目品牌清理范围内）。
OBSIDIAN_VAULT = Path(
    os.environ.get(
        "FULILIAN_OBSIDIAN_VAULT",
        "/mnt/e/Program Files/Obsidian/Document/Markdown/Hermes知识库",
    ).strip()
)


def _kb_roots():
    roots = [KB_PATH]
    if OBSIDIAN_VAULT.exists():
        roots.append(OBSIDIAN_VAULT)
    return roots

DB_PATH = FULILIAN_HOME / "knowledge.db"

# skills/ctf-cards/snippets/ — 可复用攻击片段（.py，头部注释元数据）
SNIPPETS_DIR = Path(__file__).resolve().parent.parent / "skills" / "ctf-cards" / "snippets"

# 技术标签索引（WP → tags），存在时供 similar_by_technique 使用
TECHNIQUE_INDEX_RELPATH = Path("CTF大赛WP集合") / "wp_technique_index.json"

# 结构化元数据 sidecar（WP → year/contest/vuln_type/source_url/source_id）。
# 从文件名 + 正文头部客观抽取，不经任何 LLM 标注；build_index 重建时直接
# 内联调用抽取器，本文件只是给外部（人 / 其他 RAG）消费的导出产物。
META_INDEX_RELPATH = Path("CTF大赛WP集合") / "wp_meta_index.json"

# 大赛聚合索引（人类可读，由 META_INDEX_RELPATH 聚合而来）
CONTEST_INDEX_RELPATH = Path("CTF大赛WP集合") / "contest_index.md"

# 需要跳过的文件（非正文）。
# 注意：build_index 只 rglob("*.md")，因此只保留 .md 条目——
# "LICENSE"、".gitignore" 等非 .md 文件永远不会被遍历到（死条目已移除）。
SKIP_FILES = {
    "AI-SEARCH-INDEX.md",
    "README.md",
    "CHANGELOG.md",
    "SCRIPTS-INDEX.md",
    "SELF-SOLVED-INDEX.md",
    # 本工具自己生成的聚合产物：落在 build_meta_index 正扫的目录里，
    # 不排除就会每跑一次吞一次自己的输出（自噬式污染）。
    "contest_index.md",
    "wp_meta_index.json",
    # hermes-vault 导航/元数据页：无技术内容，索引进来只会污染检索结果
    "log.md",
    "SCHEMA.md",
    "知识库索引.md",
    "index.md",
    "ctf-index.md",
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

# FTS5 建表 SQL（trigram tokenizer 支持中文）。
# year / contest / vuln_type 走 UNINDEXED：它们是**过滤列**不是检索列，
# 参与 FTS 索引只会稀释 BM25 权重。
#
# 注意：FTS5 是虚表，SQLite 明确禁止在其上建普通索引
# （"virtual tables may not be indexed"），所以过滤**无法**走索引。实际执行
# 计划是「MATCH 先用倒排索引收窄结果集，再在结果集上套 year/contest 谓词」，
# 在 2584 行的规模下开销可忽略，故刻意不做 side table + JOIN 的索引方案。
# year 以文本形态存（未知为空串而非 NULL，让 `= ?` 与 `!= ''` 语义简单）。
CREATE_TABLE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS writeups USING fts5(
    title,
    category,
    content,
    source_path UNINDEXED,
    year UNINDEXED,
    contest UNINDEXED,
    vuln_type UNINDEXED,
    tokenize='trigram'
);
"""

# 本模块当前期望的过滤列（缺任一列 → 索引需要重建）
_META_COLUMNS = ("year", "contest", "vuln_type")

# 兼容旧版 schema（unicode61），如果表已存在且是 unicode61 则重建
LEGACY_TABLE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS writeups USING fts5(
    title,
    category,
    content,
    source_path UNINDEXED
);
"""

# 可复用攻击片段表（.py 片段，元数据在文件头注释）
CREATE_SNIPPETS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS snippets USING fts5(
    title,
    category,
    code,
    source_wp UNINDEXED,
    snippet_path UNINDEXED,
    tokenize='trigram'
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


# ── WP 元数据抽取（sidecar 索引）────────────────────────────────────────
#
# 目标：给大赛 WP 补上 year / contest / vuln_type 三个可用于**过滤**的结构化
# 字段，让「2022-2025 年所有 SQL 二次注入的 WP」这类多维查询能走索引，
# 而不是逐篇 grep。全部来自文件名 + 正文头部的客观抽取，不做 LLM 标注
# （difficulty/quality 这类主观字段刻意不做）。
#
# contest 为什么用「词表优先 + 频次兜底」而不是解析文件名首段：
# articles/ 里混着非大赛内容（新闻、教程、系列文），首段抽取实测在 1156 篇
# 上产出 862 个不同 token，绝大多数是一次性噪声（"官方WP" / "好题分享系列" /
# "web选手入门pwn"）。宁可留空，不猜错——错的元数据比没有元数据更有害，
# 它会让 `search(contest=...)` 静默返回错误结果。

# 已知赛事词表。覆盖文章点名的 强网杯/西湖论剑/网鼎杯/HITCON/SECCON/N1CTF/
# RCTF/长城杯/羊城杯，加上国内赛与国际赛常见项。
CONTEST_LEXICON: tuple[str, ...] = (
    # 国内
    "强网杯", "强网拟态", "西湖论剑", "网鼎杯", "羊城杯", "长城杯", "祥云杯",
    "安洵杯", "安询杯", "鹏程杯", "湖湘杯", "红明谷", "领航杯", "蓝帽杯",
    "泰山杯", "巅峰极客", "数字中国", "工业信息安全", "黄河流域", "湾区杯",
    "数信杯", "美亚杯", "看雪", "KCTF", "春秋杯", "春秋云镜", "DataCon",
    "极客大挑战", "CISCN", "DASCTF", "N1CTF", "RCTF", "0CTF", "ACTF",
    "ByteCTF", "WMCTF", "SUCTF", "SCTF", "MRCTF", "TQLCTF", "NKCTF",
    "D3CTF", "L3HCTF", "NCTF", "XCTF", "ISCTF", "SHCTF", "SWPUCTF",
    "LitCTF", "磐石CTF", "阿里云CTF", "阿里CTF", "腾讯游戏安全", "腾訊遊戲安全",
    "IChunQiu", "云境", "Realworld", "RWCTF", "HKCERT", "網安奪旗",
    "网安夺旗", "VSEC", "AVSS", "BUUCTF", "CTFshow", "虎符CTF", "柏鹭杯",
    "强国杯", "MTCTF", "国际赛", "全国网络安全行业职业技能大赛",
    "电信和互联网", "车联网", "智能网联汽车", "软件系统安全赛", "高校网络安全",
    # 国际
    "HITCON", "SECCON", "DEFCON", "PlaidCTF", "GoogleCTF", "HackTheBox",
    "TryHackMe", "Intigriti", "Hack.lu", "Hackvent", "corCTF", "idekCTF",
    "DiceCTF", "CakeCTF", "CrewCTF", "NahamCon", "DownUnderCTF",
    "ImaginaryCTF", "PatriotCTF", "UIUCTF", "bi0sCTF", "inctf", "ASIS",
    "Midnight", "SunshineCTF", "HackPack", "ångstromCTF", "angstromCTF",
    "TetCTF", "DIVER", "37C3", "Potluck", "AlpacaHack", "PARADIGM",
    "Apiculture", "UTCTF", "Sekai", "m0leCon", "SourceZeroCon", "Flare",
    "0xGame", "USTCHackergame", "Hackergame", "1337UP", "BlackHat",
)
# 长词条优先尝试，避免短词抢先命中（"阿里CTF" vs "阿里云CTF"）。
# 保留 (小写匹配形, 展示原形) 二元组：匹配大小写不敏感，但落库/展示必须
# 用原形，否则 `--contest DASCTF` 永远匹配不上库里的 "dasctf"。
CONTEST_LEXICON_SORTED: tuple[tuple[str, str], ...] = tuple(
    sorted({(c.lower(), c) for c in CONTEST_LEXICON}, key=lambda x: len(x[0]), reverse=True)
)

# 频次兜底阶段要排除的通用词（归一化后的小写形态）。这些是「看起来像赛名
# 但其实是文档类型/题材」的高频 token。
CONTEST_STOPWORDS: frozenset[str] = frozenset({
    "wp", "writeup", "write", "ctf", "hack", "the", "windows", "google",
    "real", "fe", "house", "frida", "security", "pwn", "web", "misc",
    "crypto", "reverse", "android", "ios", "iot", "ai", "llm",
    "官方wp", "官方write", "好题分享系列", "pwn入门", "web选手入门pwn",
    "漏洞学习之pwn", "冠军writeup大放送", "buuctf刷题记录", "ctf学习交流群",
    "题解", "解析", "复现", "学习", "总结", "入门", "系列", "部分",
    "决赛", "初赛", "线上", "线下", "赛后", "小记", "记录", "笔记",
})

# 年份：2005-2026 之外的 4 位数字不认（避免把题号、端口、CVE 编号当年份）
_YEAR_RE = re.compile(r"(?<![0-9])(20[0-2][0-9]|19[89][0-9])(?![0-9])")
_YEAR_MIN, _YEAR_MAX = 2005, 2026

# 正文头部结构：实测 1156/1156 篇都以 `# 标题` 开头，且都带 `> 原文:` / `> ID:`。
# 冒号有半角/全角两种写法，必须都收。
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SRC_RE = re.compile(r"^>\s*原文\s*[:：]\s*(\S+)\s*$", re.MULTILINE)
_ID_RE = re.compile(r"^>\s*ID\s*[:：]\s*(\d+)\s*$", re.MULTILINE)

# vuln_type：比 category 更细的考点标签。**顺序敏感**，先具体后宽泛，
# 首个命中即取（"SSTI" 必须排在 "RCE" 之前，否则被宽泛词吃掉）。无命中留空。
VULN_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ssti", ("ssti", "模板注入", "template injection", "jinja", "twig", "freemarker")),
    ("deserialization", ("反序列化", "deserializ", "unserialize", "pop链", "phar", "pickle")),
    ("xxe", ("xxe", "xml外部实体", "external entity")),
    ("jwt", ("jwt", "json web token")),
    ("ssrf", ("ssrf", "服务端请求伪造")),
    ("file-inclusion", ("文件包含", "lfi", "rfi", "php://filter", "伪协议", "包含漏洞")),
    ("file-upload", ("文件上传", "上传漏洞", "upload", "webshell", "一句话木马")),
    ("sql-injection", ("sql注入", "sqli", "sql injection", "堆叠注入", "盲注", "报错注入",
                       "宽字节", "二次注入")),
    ("command-injection", ("命令执行", "rce", "远程命令", "代码执行", "无字母", "disable_functions",
                           "反弹shell", "命令注入")),
    ("xss", ("xss", "跨站脚本", "cross site scripting")),
    ("csrf", ("csrf", "跨站请求伪造")),
    ("path-traversal", ("目录穿越", "路径穿越", "path traversal", "directory traversal")),
    ("race-condition", ("条件竞争", "race condition")),
    ("prototype-pollution", ("原型链污染", "prototype pollution")),
    ("prng", ("mt19937", "随机数预测", "种子还原", "prng", "随机数")),
    ("rsa", ("rsa", "coppersmith", "wiener", "franklin", "格攻击", "lattice")),
    ("aes", ("aes", "aes-cbc", "aes-ecb", "aes-gcm")),
    ("des", ("des加密", "3des", "轮密钥")),
    ("classical-cipher", ("凯撒", "维吉尼亚", "古典密码", "替换密码", "栅栏")),
    ("hash", ("md5", "sha1", "sha256", "哈希碰撞", "hash长度扩展", "crc32")),
    ("stego-image", ("图片隐写", "lsb", "盲水印", "隐写图片", "png隐写", "宽高")),
    ("stego-audio", ("音频隐写", "频谱", "dtmf", "mp3stego", "sstv")),
    ("traffic-analysis", ("流量分析", "pcap", "wireshark", "tshark", "usb流量")),
    ("memory-forensics", ("内存取证", "volatility", "内存镜像")),
    ("disk-forensics", ("磁盘取证", "镜像取证", "数据恢复", "文件雕刻", "mft")),
    ("pwn-heap", ("堆溢出", "heap", "tcache", "fastbin", "uaf", "use after free",
                  "double free", "unsorted bin", "house of")),
    ("pwn-stack", ("栈溢出", "stack overflow", "ret2libc", "ret2win", "rop", "格式化字符串",
                   "format string", "canary", "shellcode", "缓冲区溢出")),
    ("reverse-algorithm", ("逆向", "算法还原", "反混淆", "脱壳", "花指令", "vm混淆")),
    ("apk-reverse", ("apk", "android逆向", "smali", "frida", "dex")),
    ("blockchain", ("区块链", "智能合约", "solidity", "以太坊")),
)

# 频次兜底用的首段切分符
_LEAD_SEP_RE = re.compile(r"[_\-—–\s（(·、,，]")


def _lex_hit(low_stem: str, term: str) -> bool:
    """赛事词表命中判定。

    ASCII 词条要求词边界，否则短词会误命中："kctf" 会命中 "HackCTF"，
    "realworld" 会命中 "realworlds"。CJK 词条不设边界——中文没有词边界，
    "西湖论剑" 出现在 "第八届西湖论剑初赛" 里正是要命中的情况。
    """
    need_left = bool(term) and term[0].isascii() and term[0].isalnum()
    need_right = bool(term) and term[-1].isascii() and term[-1].isalnum()
    start = 0
    while True:
        i = low_stem.find(term, start)
        if i < 0:
            return False
        j = i + len(term)
        if need_left and i > 0 and low_stem[i - 1].isalnum():
            start = i + 1
            continue
        if need_right and j < len(low_stem) and low_stem[j].isalnum():
            start = i + 1
            continue
        return True


def _extract_year(stem: str) -> Optional[int]:
    """从文件名抽取年份；抽不到返回 None（不猜）。"""
    for m in _YEAR_RE.finditer(stem):
        y = int(m.group(1))
        if _YEAR_MIN <= y <= _YEAR_MAX:
            return y
    return None


def _extract_contest_by_lexicon(stem: str) -> str:
    """词表匹配赛事名；未命中返回空串。返回值是词表里的展示原形。"""
    low = stem.lower()
    for low_term, display in CONTEST_LEXICON_SORTED:
        if _lex_hit(low, low_term):
            return display
    return ""


def _lead_token(stem: str) -> Optional[str]:
    """剥掉前导年份后取首个分隔符前的片段（保留原始大小写，供展示）。

    返回 token；纯数字/过长/过短返回 None。大小写不敏感的比较由调用方
    自行 lower()——"DASCTF" 与 "dasctf" 要算同一个赛事，但展示时要留原形。
    """
    m = _YEAR_RE.search(stem)
    s = stem
    if m and m.start() == 0:          # 年份在开头 → 剥掉（"2024年羊城杯" → "羊城杯"）
        s = stem[m.end():]
        s = re.sub(r"^[年\s_\-—–·]+", "", s)
    if not s:
        return None
    tok = _LEAD_SEP_RE.split(s, maxsplit=1)[0].strip()
    if not tok or len(tok) < 2 or len(tok) > 24:
        return None
    if re.fullmatch(r"[0-9]+", tok):
        return None
    return tok


def _extract_vuln_type(stem: str, content: str) -> str:
    """按关键词表推断考点标签；无命中返回空串。"""
    hay = stem + "\n" + content[:3000]
    for vtype, keywords in VULN_TYPE_KEYWORDS:
        if any(_kw_hit(hay, kw) for kw in keywords):
            return vtype
    return ""


def parse_wp_meta(md_file: Path, content: str) -> dict:
    """从单篇 WP 的文件名 + 正文头部客观抽取结构化元数据。

    抽不到就留空，不用猜测填充——空值在检索侧只是「不参与该维度过滤」，
    错值会让 ``--contest MOVEment`` 这类查询返回完全无关的笔记。

    注意词表里的**单个英文单词**型赛名：它们会和英文复合词撞车，
    ``lateral-movement`` 里的 "movement" 就曾把「横向移动」笔记标成
    MOVEment 战队赛。加词表条目时务必先在两个 root 上量一遍真/假阳性。

    Returns:
        dict: {title, contest, year, vuln_type, source_url, source_id, source_file}
        year 抽不到为 None；contest / vuln_type 抽不到为空串。
    """
    stem = md_file.stem
    head = content[:4000]

    m = _H1_RE.search(head)
    title = m.group(1).strip() if m else stem
    m = _SRC_RE.search(head)
    source_url = m.group(1) if m else ""
    m = _ID_RE.search(head)
    source_id = m.group(1) if m else ""

    return {
        "title": title,
        "contest": _extract_contest_by_lexicon(stem),
        "year": _extract_year(stem),
        "vuln_type": _extract_vuln_type(stem, content),
        "source_url": source_url,
        "source_id": source_id,
        "source_file": md_file.name,
    }


def _discover_contests(stems: "list[str]", min_count: int = 3) -> dict[str, str]:
    """频次兜底：为词表未命中的 WP 发现赛事名。

    返回 {原文件名 stem: 赛名}。只收录全库出现 ≥min_count 次、且不在
    CONTEST_STOPWORDS 里的首段 token（大小写不敏感比较，展示用首次出现的原形）。

    这是「宁可留空不猜错」的折中：一次性的省级赛/校内赛抽不出来就留空，
    总比把 "好题分享系列" 当成赛事名强。
    """
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for stem in stems:
        if _extract_contest_by_lexicon(stem):
            continue
        tok = _lead_token(stem)
        if not tok:
            continue
        low = tok.lower()
        if low in CONTEST_STOPWORDS:
            continue
        counts[low] = counts.get(low, 0) + 1
        display.setdefault(low, tok)

    keep = {t for t, n in counts.items() if n >= min_count}
    out: dict[str, str] = {}
    for stem in stems:
        if _extract_contest_by_lexicon(stem):
            continue
        tok = _lead_token(stem)
        if tok and tok.lower() in keep:
            out[stem] = display[tok.lower()]
    return out


# ── 索引构建 ────────────────────────────────────────────────────────────


def _load_authoritative_categories() -> "tuple[dict[str, str], dict[str, str]]":
    """读取 wp_technique_index.json 的权威分类，返回 (按路径, 按文件名) 两张表。

    wp_technique_index.json 是 WP 元数据的**单源**：kb_writeback 回灌时写入的
    category 就是权威值。但 build_index 重建走 _guess_category 按目录名/关键词
    推断，两条路径口径不一致——实测 13 条里有 3 条被推断成别的分类
    （multiSQL→pwn、WEB2→crypto、Shiro→crypto），于是 `search(category=...)`
    对这几个分类**静默漏检**（检索不到等于知识不存在）。

    本函数只负责读表；匹配策略见 _authoritative_category。

    读失败 / 无索引文件 → 返回两个空 dict，调用方回退 _guess_category。
    这一点很重要：没有 wp_technique_index.json 的知识库（例如测试用合成库）
    行为必须与从前完全一致。
    """
    index_file = KB_PATH / TECHNIQUE_INDEX_RELPATH
    if not index_file.exists():
        return {}, {}
    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}

    by_path: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        cat = entry.get("category")
        if not isinstance(cat, str) or not cat.strip():
            continue
        cat = cat.strip()
        src = entry.get("source_path")
        if isinstance(src, str) and src.strip():
            src = src.strip()
            by_path[src] = cat
            # source_path 的 basename 是前缀无关的键：KB_PATH 迁移
            # （FULILIAN_CTF_KB_PATH / 软链）后绝对路径对不上，名字还能对上。
            by_name.setdefault(Path(src).name, cat)
        # JSON 的键就是 wp_path.name（kb_writeback._register_technique_index
        # 用 wp_path.name 当键），同样登记进名字表作为兜底来源。
        if isinstance(key, str) and key.strip():
            by_name.setdefault(key.strip(), cat)
    return by_path, by_name


def _authoritative_category(
    md_file: Path,
    content: str,
    by_path: "dict[str, str]",
    by_name: "dict[str, str]",
    unique_names: "set[str]",
) -> str:
    """分类解析：wp_technique_index.json 权威值优先，未命中回退 _guess_category。

    双键匹配，顺序有讲究：
    1. `str(md_file)` 精确匹配 source_path（今天 13/13 命中，最精确）；
    2. 未命中 → 按文件名匹配，**仅当该 basename 在本轮扫描集里唯一**
       （重名文件不许靠名字认领别人的分类）；
    3. 都没命中 → _guess_category（JSON 只有十几条，绝大多数文档走这里）。

    为什么不能只用 source_path：_kb_roots() 有两个根（KB_PATH 与
    OBSIDIAN_VAULT，本机 vault 贡献了 2584 行里的 1378 行），vault 根的
    文档天然不会有 KB_PATH 前缀的 source_path；且 KB_PATH 一旦经环境变量
    或软链迁移，所有绝对路径前缀同时失效。
    """
    cat = by_path.get(str(md_file))
    if cat:
        return cat
    if md_file.name in unique_names:
        cat = by_name.get(md_file.name)
        if cat:
            return cat
    return _guess_category(md_file, content)


def _schema_is_current(conn: "sqlite3.Connection") -> bool:
    """writeups 表是否已含全部过滤列。

    老库（4 列）必须重建才能用 year/contest/vuln_type 过滤；不检查就会出现
    「索引看着是满的、过滤查询却报 no such column」的静默失效。
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(writeups)")}
    except sqlite3.DatabaseError:
        return False
    return all(c in cols for c in _META_COLUMNS)


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
            if existing > 0 and _schema_is_current(conn):
                # writeups 已有索引且 schema 最新，仍顺带确保 snippets 片段表构建
                snippets = _build_snippets_index(conn, force=False)
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

    _md_files = sorted({p for root in _kb_roots() for p in root.rglob("*.md")})
    # 权威分类表在本次调用内构建（局部变量，不用模块级缓存：缓存会跨
    # build_index 调用存活，测试重写 JSON 后仍读旧值）。
    _auth_by_path, _auth_by_name = _load_authoritative_categories()
    _name_seen: dict[str, int] = {}
    for _p in _md_files:
        _name_seen[_p.name] = _name_seen.get(_p.name, 0) + 1
    _unique_names = {n for n, c in _name_seen.items() if c == 1}
    # 频次兜底赛名：**统计与回填都只在 WP 合集内**。
    # Hermes vault 是个人笔记库，文件名是主题式的（CVE-xxxx / php-xxx / s2-xxx），
    # 拿它做频次发现会把 "CVE" / "s2" / "php" 当成赛事名污染索引——实测
    # 全库统计时 CVE 以 382 篇冲上榜首。词表匹配（高精度）不受此限。
    _wp_prefix = str(KB_PATH / "CTF大赛WP集合")
    _discovered_contests = _discover_contests(
        [p.stem for p in _md_files if str(p).startswith(_wp_prefix)]
    )
    for md_file in _md_files:
        # hermes-vault 本地镜像已废弃；残留时跳过，防止重复索引
        if "hermes-vault" in md_file.parts:
            continue
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
            category = _authoritative_category(
                md_file, content, _auth_by_path, _auth_by_name, _unique_names
            )
            # 限制 content 长度（FTS5 文档大小限制通常在 1GB 内，但保持合理）
            content_trunc = content[:200_000]

            meta = parse_wp_meta(md_file, content)
            contest = meta["contest"]
            if not contest and str(md_file).startswith(_wp_prefix):
                contest = _discovered_contests.get(md_file.stem, "")
            year = meta["year"]

            conn.execute(
                "INSERT INTO writeups "
                "(title, category, content, source_path, year, contest, vuln_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    category,
                    content_trunc,
                    str(md_file),
                    str(year) if year else "",
                    contest,
                    meta["vuln_type"],
                ),
            )
            count += 1
        except Exception:  # noqa: BLE001
            errors += 1
            continue

    conn.commit()

    # 顺带构建 snippets 片段表（force 时一并重建）
    snippets = _build_snippets_index(conn, force=force)

    conn.close()

    if errors:
        print(f"[knowledge] build_index: {count} indexed, {errors} skipped (errors)")
    if snippets:
        print(f"[knowledge] snippets: {snippets} indexed")

    return count


def index_writeup_file(md_file: Path) -> bool:
    """把单篇 Markdown 增量插入 writeups 索引（kb_writeback 回灌用）。

    行结构与 build_index 完全同构（title=文件名 stem、category 走
    _guess_category、content 截 200k）。SQL 为常量字面量 + 占位符，
    所有运行时值经 sqlite3 参数绑定传入。表不存在/DB 锁等失败返回
    False（调用方降级：文件已在库内，下次 force 重建自然入索引）。
    幂等性由调用方保证（回灌前有文件级去重，每篇至多插入一次）。
    """
    if not DB_PATH.exists():
        return False
    try:
        content = md_file.read_text(encoding="utf-8", errors="ignore")
        if not content.strip():
            return False
        title = md_file.stem
        # 与 build_index 同口径：JSON 权威分类优先。该函数目前全仓库零调用者，
        # 但它是 build_index 的增量孪生实现——不一起改，将来有人启用它时
        # 同一个「推断分类覆盖权威分类」的缺陷会原样复活。
        _auth_by_path, _auth_by_name = _load_authoritative_categories()
        category = _authoritative_category(
            md_file, content, _auth_by_path, _auth_by_name, {md_file.name}
        )
        content_trunc = content[:200_000]
        source = str(md_file)
        # 元数据同口径抽取。注意：频次兜底赛名（_discover_contests）需要全库
        # 统计，单文件增量插入拿不到，故这里只填词表命中的赛名；未命中的等
        # 下次 force 重建自然补齐。year / vuln_type 不受影响（纯单文件推断）。
        meta = parse_wp_meta(md_file, content)
        year = meta["year"]
        row = (
            title,
            category,
            content_trunc,
            source,
            str(year) if year else "",
            meta["contest"],
            meta["vuln_type"],
        )
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.executemany(
                "INSERT INTO writeups "
                "(title, category, content, source_path, year, contest, vuln_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [row],
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001 — 增量索引失败由调用方告警降级
        return False


# ── 片段（snippets）索引 ────────────────────────────────────────────────

# 片段文件头部元数据注释的解析规则
_SNIPPET_META_RE = re.compile(r"^#\s*(SOURCE|TITLE|CATEGORY)\s*:\s*(.*)$", re.MULTILINE)


def _parse_snippet_file(path: Path) -> Optional[dict]:
    """解析单个片段 .py 文件的头部元数据。

    头部约定（由片段生成器写入）：
        # SOURCE: <来源 WP 绝对路径>
        # TITLE:  <片段标题>
        # CATEGORY: <分类>

    Returns:
        dict | None: {"source_wp", "title", "category", "code", "snippet_path"}
        无效文件（空/读失败）返回 None。
    """
    try:
        code = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not code.strip():
        return None

    meta = {m.group(1).lower(): m.group(2).strip() for m in _SNIPPET_META_RE.finditer(code)}
    title = meta.get("title") or path.stem
    category = meta.get("category") or (path.parent.name or "misc")
    source_wp = meta.get("source") or ""
    return {
        "source_wp": source_wp,
        "title": title,
        "category": category,
        "code": code,
        "snippet_path": str(path),
    }


def _build_snippets_index(conn: "sqlite3.Connection", force: bool = False) -> int:
    """构建 snippets 片段表（在已打开的连接上执行）。

    扫描 SNIPPETS_DIR 下所有 .py 片段入库。目录缺失时返回 0（静默）。
    非 force 且表已有数据时跳过。
    """
    try:
        if not force:
            existing = conn.execute("SELECT count(*) FROM snippets").fetchone()[0]
            if existing > 0:
                return existing
    except sqlite3.OperationalError:
        pass  # 表不存在，继续创建

    try:
        conn.execute("DROP TABLE IF EXISTS snippets")
        conn.execute(CREATE_SNIPPETS_SQL)
    except sqlite3.OperationalError:
        return 0

    if not SNIPPETS_DIR.is_dir():
        return 0

    count = 0
    for py_file in sorted(SNIPPETS_DIR.rglob("*.py")):
        if ".git" in py_file.parts:
            continue
        try:
            item = _parse_snippet_file(py_file)
            if not item:
                continue
            conn.execute(
                "INSERT INTO snippets (title, category, code, source_wp, snippet_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (item["title"], item["category"], item["code"],
                 item["source_wp"], item["snippet_path"]),
            )
            count += 1
        except Exception:  # noqa: BLE001 — 单个片段失败不阻断
            continue
    try:
        conn.commit()
    except sqlite3.OperationalError:
        pass
    return count


# ── 检索 ────────────────────────────────────────────────────────────────

# FTS5 trigram 分词器的最小可命中长度：短于 3 字符的 token 一律零命中
_TRIGRAM_MIN_CHARS = 3


def _meta_fields(row, offset: int = 4) -> dict:
    """从查询行提取 year/contest/vuln_type。

    三条查询路径（FTS5 / token 兜底 / LIKE 兜底）共用，避免某一处漏读列
    导致结果 dict 字段漂移。year 在库里是空串表示未知，这里归一成 None。
    """
    return {
        "year": int(row[offset]) if row[offset] else None,
        "contest": row[offset + 1] or "",
        "vuln_type": row[offset + 2] or "",
    }


def _append_meta_filters(
    sql: str,
    params: list,
    *,
    year: Optional[int] = None,
    contest: Optional[str] = None,
    vuln_type: Optional[str] = None,
) -> "tuple[str, list]":
    """给查询追加 year/contest/vuln_type 过滤条件（None/空串 = 不过滤）。"""
    if year is not None:
        sql += " AND year = ?"
        params.append(str(year))
    if contest:
        sql += " AND contest = ?"
        params.append(contest)
    if vuln_type:
        sql += " AND vuln_type = ?"
        params.append(vuln_type)
    return sql, params


def _index_has_meta() -> bool:
    """当前索引是否已含过滤列（老库返回 False）。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            return _schema_is_current(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def search(
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
    auto_build: bool = True,
    year: Optional[int] = None,
    contest: Optional[str] = None,
    vuln_type: Optional[str] = None,
) -> list[dict]:
    """FTS5 全文搜索。

    Args:
        query: 自由文本关键词。**内部先过 sanitize_match_query**（P4.2
            下沉）：引号/括号/payload 片段/裸操作符词一律清洗成
            `"tok1" OR "tok2"` 形态，调用方无需也不应自己构造 MATCH 语法；
            清洗后为空（纯标点等）直接返回 []，不触发索引构建。
        category: 可选分类过滤（web/crypto/reverse/pwn/forensics/misc）。
        limit: 返回结果数（默认 5）。
        auto_build: 索引不存在时自动构建（默认 True）。
        year: 可选年份过滤（如 2022）。
        contest: 可选赛事过滤（如 "DASCTF"；须与库中写法一致）。
        vuln_type: 可选考点过滤（如 "sql-injection"）。

    Returns:
        list[dict]: [{"title", "category", "snippet", "source_path",
                      "year", "contest", "vuln_type"}, ...]
    """
    # P4.2：先洗再查。放在 DB 检查之前 —— 垃圾 query 不值得为它建索引。
    query = sanitize_match_query(query)
    if not query:
        return []

    want_meta = year is not None or bool(contest) or bool(vuln_type)
    if not DB_PATH.exists() or _is_empty_index():
        if auto_build:
            build_index()
        else:
            return []
    elif want_meta and not _index_has_meta():
        # 老 schema（4 列）下 year/contest 过滤会抛 no such column，被下面的
        # DatabaseError 兜底吞成空结果——静默返回空比报错更坏。先重建。
        if auto_build:
            build_index(force=True)
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
                       source_path, year, contest, vuln_type
                FROM writeups
                WHERE writeups MATCH ?
            """
            params: list = [query]

            if category:
                sql += " AND category = ?"
                params.append(category)
            sql, params = _append_meta_filters(
                sql, params, year=year, contest=contest, vuln_type=vuln_type
            )

            # 7 列权重，与 SELECT 的列序一一对应；后 4 个 UNINDEXED 列不参与
            # 检索（词频恒为 0），权重给 0 是为了让列数对应关系显式可读。
            sql += (" ORDER BY bm25(writeups, 10.0, 5.0, 2.0, 0.0, 0.0, 0.0, 0.0)"
                    " LIMIT ?")
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
        finally:
            # 无论 FTS5 查询是否抛错都关闭连接，再走 LIKE 回退，避免连接泄漏
            conn.close()
    except sqlite3.DatabaseError:
        # OperationalError（FTS5 语法错误）是其子类；DatabaseError 一并兜住
        # 损坏/非 SQLite 的 DB 文件，避免裸 traceback 穿透到 CLI 调用方
        return _fallback_like_search(
            query, category, limit,
            year=year, contest=contest, vuln_type=vuln_type,
        )

    results = [
        {
            "title": r[0],
            "category": r[1],
            "snippet": r[2],
            "source_path": r[3],
            **_meta_fields(r),
        }
        for r in rows
    ]
    if not results:
        # FTS5 trigram 对 **短于 3 字符** 的 token 零命中，而中文题面最高频的
        # 恰恰是「注入」「上传」「逆向」这类二字词 —— 短词查询会静默返回空。
        # 真实无命中与短词失效在 FTS 层无法区分，统一用 LIKE 兜底再试一次。
        results = _fallback_token_search(
            _query_tokens(query), category, limit,
            year=year, contest=contest, vuln_type=vuln_type,
        )

    return results


def _is_empty_index() -> bool:
    """检查索引是否为空。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        count = conn.execute("SELECT count(*) FROM writeups").fetchone()[0]
        conn.close()
        return count == 0
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return True


# FTS5 的布尔/邻近操作符，还原裸 token 时须剔除，否则会被当成检索词。
_FTS_OPERATORS = frozenset({"or", "and", "not", "near"})


def _query_tokens(query: str) -> list[str]:
    """从 FTS5 查询串里还原裸 token（去掉短语引号与 ``OR`` 操作符）。

    ``knowledge._sanitize_query`` 产出的是 ``"tok1" OR "tok2"`` 形态；LIKE
    兜底需要的是裸 token，直接拿整串去 LIKE 只会匹配到含引号的文本。

    裸查询（CLI 的 ``knowledge query 注入`` 直传原串）没有任何引号，只按
    引号正则会一无所获——返回空列表就把短词兜底短路成静默零命中，而中文
    二字词正是最高频的查询形态。故引号里捞不到时，退回按空白/括号拆裸词。
    """
    quoted = [t for t in re.findall(r'"([^"]*)"', query) if t.strip()]
    if quoted:
        return quoted
    return [
        t.strip("*")
        for t in re.split(r"[\s()]+", query)
        if t.strip("*") and t.strip("*").lower() not in _FTS_OPERATORS
    ]


def _fallback_token_search(
    tokens: list[str],
    category: Optional[str] = None,
    limit: int = 5,
    year: Optional[int] = None,
    contest: Optional[str] = None,
    vuln_type: Optional[str] = None,
) -> list[dict]:
    """按 token 做 LIKE OR 匹配的兜底检索。

    用途：FTS5 trigram 对短于 3 字符的 token 零命中（中文二字词题面几乎
    全是这种词），FTS 返回空时用它保证召回。长 token 区分度高，优先只用
    它们；全是短词时才退化为短词匹配（可能偏宽，仍由 LIMIT 兜住）。

    排序：LIKE OR 本身无相关性序，裸 LIMIT 会按 rowid 顺序返回"任意
    命中任一 token 的前 N 行"——题面高频词（注入/上传）命中几百行时，
    那 N 行与题面的相关度约等于随机。这里多取一批候选，按「命中的
    不同 token 数」降序后取前 limit 条，并给每条附 ``score``（命中
    token 数）供调用方做相关性闸门。
    """
    clean = [t.strip() for t in tokens if t and t.strip()]
    if not clean:
        return []
    use = [t for t in clean if len(t) >= _TRIGRAM_MIN_CHARS] or clean

    where = " OR ".join(r"content LIKE ? ESCAPE '\'" for _ in use)
    params: list = [
        "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for t in use
    ]
    sql = f"""
        SELECT title, category,
               substr(content, 1, 200) AS snip,
               source_path, year, contest, vuln_type
        FROM writeups
        WHERE ({where})
    """
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql, params = _append_meta_filters(
        sql, params, year=year, contest=contest, vuln_type=vuln_type
    )
    # 候选池取 limit 的倍数 + 底值，排序后截断；排序键是 Python 侧算的
    # token 命中数，SQL 侧无法表达。
    fetch_n = max(limit * 20, 100)
    sql += " LIMIT ?"
    params.append(fetch_n)

    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return []

    use_lower = [t.lower() for t in use]
    scored = []
    for r in rows:
        hay = f"{r[0] or ''} {r[2] or ''}".lower()
        score = sum(1 for t in use_lower if t in hay)
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "title": r[0],
            "category": r[1],
            "snippet": (r[2] or "")[:200] + ("..." if r[2] and len(r[2]) > 200 else ""),
            "source_path": r[3],
            "score": score,
            **_meta_fields(r),
        }
        for score, r in scored[:limit]
    ]


def _fallback_like_search(
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
    year: Optional[int] = None,
    contest: Optional[str] = None,
    vuln_type: Optional[str] = None,
) -> list[dict]:
    """FTS5 语法错误时的 LIKE 回退搜索。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        sql = r"""
            SELECT title, category,
                   substr(content, 1, 200) AS snip,
                   source_path, year, contest, vuln_type
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
        sql, params = _append_meta_filters(
            sql, params, year=year, contest=contest, vuln_type=vuln_type
        )

        sql += " LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()

        return [
            {
                "title": r[0],
                "category": r[1],
                "snippet": (r[2] or "")[:200] + ("..." if r[2] and len(r[2]) > 200 else ""),
                "source_path": r[3],
                **_meta_fields(r),
            }
            for r in rows
        ]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def search_snippets(
    query: str,
    category: Optional[str] = None,
    limit: int = 3,
    auto_build: bool = True,
) -> list[dict]:
    """FTS5 检索可复用攻击片段（snippets 表）。

    Args:
        query: 搜索关键词。
        category: 可选分类过滤。
        limit: 返回结果数（默认 3）。
        auto_build: 片段表为空时自动构建（默认 True）。

    Returns:
        list[dict]: [{"title", "category", "code", "source_wp", "snippet_path"}, ...]
        任何失败（DB 缺失/表为空/语法错误）返回 []，绝不抛异常。
    """
    try:
        if not DB_PATH.exists():
            if auto_build:
                build_index()
            else:
                return []
        if _snippets_count() == 0:
            if not auto_build:
                return []
            conn = sqlite3.connect(str(DB_PATH))
            try:
                _build_snippets_index(conn, force=False)
            finally:
                conn.close()
            if _snippets_count() == 0:
                return []

        conn = sqlite3.connect(str(DB_PATH))
        try:
            sql = """
                SELECT title, category, code, source_wp, snippet_path
                FROM snippets
                WHERE snippets MATCH ?
            """
            params: list = [query]
            if category:
                sql += " AND category = ?"
                params.append(category)
            sql += " ORDER BY bm25(snippets, 5.0, 3.0, 1.0, 1.0, 1.0) LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # FTS5 语法错误 → LIKE 回退（按 code 列模糊匹配）
            try:
                sql = """
                    SELECT title, category, code, source_wp, snippet_path
                    FROM snippets
                    WHERE code LIKE ? ESCAPE '\\'
                """
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
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                return []
        finally:
            conn.close()
        return [
            {
                "title": r[0],
                "category": r[1],
                "code": r[2],
                "source_wp": r[3],
                "snippet_path": r[4],
            }
            for r in rows
        ]
    except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError):
        return []


def _snippets_count() -> int:
    """snippets 表行数（表不存在/DB 缺失返回 0）。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        count = conn.execute("SELECT count(*) FROM snippets").fetchone()[0]
        conn.close()
        return count
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return 0


def similar_by_technique(tags: list[str], limit: int = 3) -> list[dict]:
    """按技术标签交集查找相似历史 WP。

    读知识库的 CTF大赛WP集合/wp_technique_index.json（存在时），对每个
    WP 的标签集合与给定 tags 求交集，按交集大小排序返回 top-N。

    Args:
        tags: 技术标签列表（如 ["SSTI", "jinja2", "bypass"]）。
        limit: 返回结果数（默认 3）。

    Returns:
        list[dict]: [{"title", "source_path"}, ...]（按交集大小降序）。
        JSON 缺失/解析异常时返回 []，绝不抛异常。
    """
    if not tags:
        return []
    index_file = KB_PATH / TECHNIQUE_INDEX_RELPATH
    if not index_file.exists():
        return []
    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return []

    wanted = {str(t).strip().lower() for t in tags if str(t).strip()}
    if not wanted:
        return []

    # 兼容多种 JSON 形态：
    # 1) {wp键(标题或路径): [tag, ...]}
    # 2) {wp键: {"title":..., "source_path":..., "tags":[...]}}
    # 3) [{"title":..., "source_path":..., "tags":[...]}, ...]
    entries: list[tuple[set, str, str]] = []  # (tags_set, title, source_path)
    try:
        if isinstance(data, dict):
            iterator = data.items()
        elif isinstance(data, list):
            iterator = [(None, item) for item in data if isinstance(item, dict)]
        else:
            return []

        for key, val in iterator:
            if isinstance(val, dict):
                raw_tags = val.get("tags") or val.get("techniques") or []
                title = str(val.get("title") or key or "")
                src = str(val.get("source_path") or val.get("path") or key or "")
            elif isinstance(val, (list, tuple)):
                raw_tags = val
                title = str(key or "")
                src = str(key or "")
            else:
                continue
            tag_set = {str(t).strip().lower() for t in raw_tags if str(t).strip()}
            if tag_set:
                entries.append((tag_set, title, src))
    except (AttributeError, TypeError):
        return []

    scored: list[tuple[int, str, str]] = []
    for tag_set, title, src in entries:
        overlap = len(tag_set & wanted)
        if overlap > 0:
            scored.append((overlap, title, src))
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {"title": title, "source_path": src}
        for _, title, src in scored[: max(1, limit)]
    ]


def get_index_stats() -> dict:
    """获取索引统计信息。

    返回体在旧字段之外补充元数据覆盖度（by_year / by_contest / by_vuln_type
    以及 contest_count）。老 schema 库缺这些列时，元数据部分返回空而不是
    整体报错——统计接口不应该因为库没重建就整个不可用。
    """
    stats: dict = {
        "total_docs": 0,
        "by_category": {},
        "db_path": str(DB_PATH),
        "by_year": {},
        "by_vuln_type": {},
        "top_contests": {},
        "contest_count": 0,
        "year_known": 0,
        "contest_known": 0,
        "schema_current": False,
    }
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            stats["total_docs"] = conn.execute(
                "SELECT count(*) FROM writeups"
            ).fetchone()[0]
            stats["by_category"] = dict(conn.execute(
                "SELECT category, count(*) FROM writeups "
                "GROUP BY category ORDER BY 2 DESC"
            ).fetchall())
            if not _schema_is_current(conn):
                return stats
            stats["schema_current"] = True
            stats["by_year"] = dict(conn.execute(
                "SELECT year, count(*) FROM writeups WHERE year != '' "
                "GROUP BY year ORDER BY year DESC"
            ).fetchall())
            stats["by_vuln_type"] = dict(conn.execute(
                "SELECT vuln_type, count(*) FROM writeups WHERE vuln_type != '' "
                "GROUP BY vuln_type ORDER BY 2 DESC"
            ).fetchall())
            stats["top_contests"] = dict(conn.execute(
                "SELECT contest, count(*) FROM writeups WHERE contest != '' "
                "GROUP BY contest ORDER BY 2 DESC LIMIT 15"
            ).fetchall())
            row = conn.execute(
                "SELECT count(DISTINCT contest) FROM writeups WHERE contest != ''"
            ).fetchone()
            stats["contest_count"] = row[0] if row else 0
            stats["year_known"] = conn.execute(
                "SELECT count(*) FROM writeups WHERE year != ''"
            ).fetchone()[0]
            stats["contest_known"] = conn.execute(
                "SELECT count(*) FROM writeups WHERE contest != ''"
            ).fetchone()[0]
        finally:
            conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass
    return stats


def build_meta_index(min_count: int = 3) -> int:
    """导出结构化元数据 sidecar：CTF大赛WP集合/wp_meta_index.json。

    只扫 KB_PATH 下 CTF大赛WP集合/ 的 WP（articles + self-solved），
    每条记录含 title / contest / year / vuln_type / source_url / source_id。

    这是**导出产物**，不是 build_index 的输入——build_index 内联调用同一套
    抽取器，所以删掉本文件不影响检索。它的用途是给外部系统（人、其他 RAG
    平台）消费，以及给 contest_index.md 聚合提供数据源。

    Returns:
        int: 写入的记录数（KB 目录不存在时为 0）。
    """
    wp_root = KB_PATH / "CTF大赛WP集合"
    if not wp_root.is_dir():
        return 0

    md_files = sorted(
        p for p in wp_root.rglob("*.md")
        if p.name not in SKIP_FILES and not p.name.endswith(IDX_SUFFIX)
    )
    entries: list[dict] = []
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not content.strip():
            continue
        entries.append(parse_wp_meta(md_file, content))

    # 频次兜底：补词表未命中的赛事名
    discovered = _discover_contests([Path(e["source_file"]).stem for e in entries],
                                    min_count=min_count)
    for e in entries:
        if not e["contest"]:
            e["contest"] = discovered.get(Path(e["source_file"]).stem, "")

    out = KB_PATH / META_INDEX_RELPATH
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(entries, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return 0
    return len(entries)


def build_contest_index() -> int:
    """聚合 wp_meta_index.json 生成人类可读的 CTF大赛WP集合/contest_index.md。

    Returns:
        int: 收录的赛事数（无元数据时为 0）。
    """
    meta_file = KB_PATH / META_INDEX_RELPATH
    if not meta_file.exists():
        return 0
    try:
        entries = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    if not isinstance(entries, list):
        return 0

    by_contest: dict[str, list[dict]] = {}
    unlabeled = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = (e.get("contest") or "").strip()
        if not name:
            unlabeled += 1
            continue
        by_contest.setdefault(name, []).append(e)

    def _sort_key(item):
        name, items = item
        years = [i["year"] for i in items if isinstance(i.get("year"), int)]
        return (-len(items), name.lower())

    lines = [
        "# CTF 大赛索引（contest_index）",
        "",
        f"> 由 `wp_meta_index.json` 聚合生成，共 **{len(by_contest)}** 个赛事、"
        f"**{len(entries) - unlabeled}** 篇已标注 WP。",
        f"> 另有 {unlabeled} 篇未识别出赛事名（一次性赛事/非大赛内容），"
        "保留为空而不猜测。",
        ">",
        "> 重新生成：`fulilian knowledge meta build`",
        "",
        "| 赛事 | 篇数 | 年份跨度 |",
        "|------|------|----------|",
    ]
    for name, items in sorted(by_contest.items(), key=_sort_key):
        years = sorted({i["year"] for i in items if isinstance(i.get("year"), int)})
        span = f"{years[0]}–{years[-1]}" if len(years) > 1 else (
            str(years[0]) if years else "—"
        )
        lines.append(f"| {name} | {len(items)} | {span} |")

    lines += ["", "## 按赛事列 WP", ""]
    for name, items in sorted(by_contest.items(), key=_sort_key):
        lines.append(f"### {name}（{len(items)} 篇）")
        lines.append("")
        for e in sorted(items, key=lambda x: (x.get("year") or 9999,
                                              x.get("source_file", ""))):
            y = e.get("year")
            vt = e.get("vuln_type") or ""
            suffix = " · ".join(x for x in (str(y) if y else "", vt) if x)
            src = e.get("source_file", "")
            lines.append(f"- [{e.get('title') or src}](articles/{src})"
                         + (f" — {suffix}" if suffix else ""))
        lines.append("")

    out = KB_PATH / CONTEST_INDEX_RELPATH
    try:
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return 0
    return len(by_contest)


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
    "SNIPPETS_DIR",
    "META_INDEX_RELPATH",
    "CONTEST_INDEX_RELPATH",
    "build_index",
    "build_meta_index",
    "build_contest_index",
    "parse_wp_meta",
    "search",
    "search_snippets",
    "similar_by_technique",
    "get_index_stats",
    "list_categories",
    "_guess_category",
]