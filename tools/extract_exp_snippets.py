#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 CTF 知识库的所有 Markdown 中提取 Python exp/exploit 代码片段。

功能:
  1. 遍历知识库所有 .md（跳过 .git），提取 ```python / ```py / ```python3 围栏代码块;
  2. 启发式过滤: 代码含任一 exp 特征（pwn/requests/socket/subprocess/sqlmap/system(/crypto 库等）
     且 >= MIN_LINES 行才保留;
  3. 按代码内容 md5 去重;
  4. 分类推断: 优先 WP 所在目录路径关键词, 其次 WP 标题关键词, 再次代码特征, 兜底 misc;
  5. 输出到 skills/ctf-knowledge/snippets/<分类>/<安全化WP名>__<序号>.py,
     每个文件头部写入 SOURCE / TITLE / CATEGORY 三行注释元数据;
  6. 幂等: 运行前清空 snippets/ 重建; 结尾打印统计。

用法:
  ~/.fulilian/fulilian-agent/venv/bin/python \
      ~/.fulilian/fulilian-agent/tools/extract_exp_snippets.py
可选参数:
  --kb-root PATH    知识库根目录（默认 Des-CTF-Knowledge-main）
  --out-dir PATH    片段输出目录（默认 skills/ctf-knowledge/snippets）
"""

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

DEFAULT_KB_ROOT = "/home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main"
DEFAULT_OUT_DIR = "/home/xujuan/.fulilian/fulilian-agent/skills/ctf-knowledge/snippets"

MIN_LINES = 6  # 代码块最少行数

CATEGORIES = ("web", "crypto", "reverse", "pwn", "forensics", "misc")

# exp 特征子串（小写匹配）: 命中任一 + 行数达标即视为 exp 片段
EXP_SIGNALS = [
    # pwn
    "from pwn import", "import pwn", "pwnlib", "remote(",
    # web / 通用利用
    "requests.", "import requests", "socket.socket", "urllib.request",
    "urlopen", "http.client", "sqlmap", "subprocess", "os.system", "system(",
    "popen(", "eval(", "exec(",
    # crypto 常见库
    "from crypto", "import crypto", "crypto.cipher", "gmpy", "libnum",
    "sympy", "long_to_bytes", "bytes_to_long", "hashlib", "binascii",
    "md5", "sha1", "sha256", "rsa", "aes", "des", "gcd(", "modinv",
    # forensics / misc
    "scapy", "rdpcap", "pil", "image.open", "cv2", "zlib.", "stego",
    "base64", "codecs.", "itertools", "bytearray", "unhex", "xor",
]

# 代码特征 -> 分类（用于内容兜底推断, 按顺序先命中先得）
CONTENT_CATEGORY_SIGNALS = [
    ("pwn", ["from pwn import", "pwnlib", "remote(", "listen("]),
    ("web", ["requests.", "sqlmap", "socket.socket", "urllib", "urlopen",
             "http.client", "os.system", "subprocess", "system("]),
    ("crypto", ["from crypto", "gmpy2", "libnum", "sympy", "long_to_bytes",
                "bytes_to_long", "hashlib", "modinv"]),
    ("forensics", ["scapy", "rdpcap", "pil", "image.open", "cv2", "zlib.",
                   "stego", "wave"]),
    ("reverse", ["dis.", "opcode", "bytearray", "unhex"]),
]

# 目录/标题关键词 -> 分类（小写匹配, 按顺序先命中先得）
PATH_CATEGORY_KEYWORDS = [
    ("web", ["sql", "注入", "sqli", "xss", "ssrf", "ssti", "文件上传",
             "文件包含", "命令执行", "反序列化", "代码审计", "jwt", "web",
             "nodejs", "php", "csrf", "xxe", "rce", "登录", "cms"]),
    ("crypto", ["crypto", "密码", "rsa", "aes", "des", "格密码", "哈希",
                "hash", "encode", "编码"]),
    ("reverse", ["reverse", "逆向", "re_", "_re", "crackme"]),
    ("pwn", ["pwn", "堆", "栈", "heap", "rop", "shellcode"]),
    ("forensics", ["forensics", "取证", "隐写", "流量", "misc_", "压缩包",
                   "图片", "音频", "usb", "ttl", "内存", "镜像", "取证"]),
    ("misc", ["misc", "杂项"]),
]

FENCE_LANG_RE = re.compile(r"^```([A-Za-z0-9_+\-]*)\s*(.*)$")
PY_LANGS = {"python", "py", "python3"}
H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")

# 裸围栏块（无语言标注）的 python 似真度判定
PY_LINE_RE = re.compile(
    r"^\s*(import\s|from\s+[\w.]+\s+import\s|def\s+\w+\s*\(|class\s+\w+"
    r"|print\s*\(|for\s+\w+\s+in\s|while\s+.*:|if\s+.*:|elif\s|@\w+"
    r"|[a-zA-Z_][\w\'\"\[\]]*\s*=[^=])"
)
PY_FIRST_LINE_RE = re.compile(
    r"^(import\s|from\s|def\s|class\s|print\s*\(|#"
    r"|#!/usr/bin/(env\s+)?python|[a-zA-Z_]\w*\s*=[^=])"
)
# 硬排除标记: PHP/JS/Bash/SQL/Java 等
NON_PYTHON_MARKERS = [
    "<?php", "#!/bin/", "console.log", "function ", "=>", "<script",
    "public static", "SELECT ", "UNION ",
]
MIN_PY_LINES = 3  # 裸块需匹配的 python 结构行数

# 文件名需要去除的字符: 路径分隔符、引号类、井号、控制类（中英文括号对称剥离）
UNSAFE_CHARS_RE = re.compile(
    r'[\\/:"*?<>|#\'`"“”‘’「」『』【】\[\]\(\)\{\}]{1}'
)


def normalize_code(code: str) -> str:
    """无害归一化: 清理网页粘贴残留的不可见字符。

    - NBSP(U+00A0)/零宽字符 → 普通空格或删除;
    - 真实 NUL 及其他控制字节删除（源码中的 b'\\x00' 是转义序列, 不受影响）。
    """
    code = code.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    code = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", code)
    return code


def looks_like_exp(code: str) -> bool:
    """启发式判断代码块是否为 exp/exploit 片段。"""
    if len([ln for ln in code.splitlines() if ln.strip()]) < MIN_LINES:
        return False
    low = code.lower()
    return any(sig in low for sig in EXP_SIGNALS)


def infer_category(md_path: Path, kb_root: Path, title: str, code: str) -> str:
    """分类推断: 目录路径关键词 > 标题关键词 > 代码特征 > misc。"""
    rel = str(md_path.relative_to(kb_root)).lower()
    for cat, kws in PATH_CATEGORY_KEYWORDS:
        if any(kw in rel for kw in kws):
            return cat
    t = title.lower()
    for cat, kws in PATH_CATEGORY_KEYWORDS:
        if any(kw in t for kw in kws):
            return cat
    low = code.lower()
    for cat, sigs in CONTENT_CATEGORY_SIGNALS:
        if any(sig in low for sig in sigs):
            return cat
    return "misc"


# 标题噪音: coding 声明 / 纯符号行（代码围栏内的 # 注释泄漏进来时排除）
TITLE_NOISE_RE = re.compile(r"(-\*-|coding\s*[:=]|^[-=*~_+#.]+$)")


def extract_title(md_text: str, md_path: Path) -> str:
    """WP 标题: 优先围栏外首个一级标题, 兜底文件名。

    跳过 ``` 围栏内的行, 避免把代码块中的 `# comment` 行误当标题;
    同时过滤 `# -*- coding: utf-8 -*-` 之类的噪音行。
    """
    in_fence = False
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.startswith("#"):
            continue
        m = H1_RE.match(line)
        if not m:
            continue
        cand = m.group(1).strip()
        if cand and not TITLE_NOISE_RE.search(cand):
            return cand
    return md_path.stem


def sanitize_name(name: str, max_len: int = 80) -> str:
    """文件名安全化: 保留中文, 去掉路径分隔符/引号类字符, 截断。"""
    cleaned = UNSAFE_CHARS_RE.sub("", name)
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_. ")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_len]


def looks_like_python_bare(code: str) -> bool:
    """裸围栏块的 python 似真度判定: 首个非空行 pythonic 起始
    + 足量 python 结构行 + 无 PHP/JS/Bash/SQL 硬排除标记。"""
    lines = [ln for ln in code.splitlines() if ln.strip()]
    if not lines or not PY_FIRST_LINE_RE.match(lines[0].strip()):
        return False
    if sum(1 for ln in lines if PY_LINE_RE.match(ln)) < MIN_PY_LINES:
        return False
    return not any(marker in code for marker in NON_PYTHON_MARKERS)


def extract_python_blocks(md_text: str):
    """逐行扫描围栏代码块, 产出 (来源类型, 代码文本) 列表。

    状态机覆盖**所有**语言的围栏（含闭合行）, 避免 bash/php 等块的闭合
    ``` 被误判为裸块开符而吞掉后续真实的 python 围栏。

    来源类型:
      - "labeled": ```python / ```py / ```python3, 或语言 token 与首行代码
        粘连的变体（```pythonimport ... 等, 剥离前缀后首行并入代码）;
      - "bare": 无语言标注的 ``` 块（后续用 python 似真度判定把关）。
    """
    blocks, cur = [], []
    inside = False      # 当前是否处于任一围栏块内（不限语言）
    tracking = False    # 当前块是否为需要收集的 python 候选
    kind = None
    for line in md_text.splitlines():
        stripped = line.strip()
        if inside:
            if stripped.startswith("```"):  # 任意语言的闭合围栏
                if tracking and kind in ("labeled", "bare"):
                    blocks.append((kind, "\n".join(cur)))
                inside, tracking, kind = False, False, None
            elif tracking:
                cur.append(line)
            continue
        if stripped.startswith("```"):  # 开围栏
            m = FENCE_LANG_RE.match(stripped)
            token = (m.group(1) if m else "").lower()
            first_line = ""
            inside, cur = True, []
            if token in PY_LANGS:
                kind, tracking = "labeled", True
            elif token.startswith("python") and len(token) > len("python"):
                kind, tracking = "labeled", True
                first_line = token[len("python"):]
            elif token.startswith("py") and len(token) > len("py"):
                kind, tracking = "labeled", True
                first_line = token[len("py"):]
            elif token == "":
                kind, tracking = "bare", True
            else:
                kind, tracking = None, False  # 其他语言: 只跟踪不收集
            if first_line:
                cur.append(first_line)
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract python exp snippets from CTF KB")
    ap.add_argument("--kb-root", default=DEFAULT_KB_ROOT)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    kb_root = Path(args.kb_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not kb_root.is_dir():
        print(f"[!] knowledge base not found: {kb_root}", file=sys.stderr)
        return 1

    # 幂等: 清空重建
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for cat in CATEGORIES:
        (out_dir / cat).mkdir(parents=True, exist_ok=True)

    md_files = sorted(
        p for p in kb_root.rglob("*.md")
        if ".git" not in p.parts and p.is_file()
    )

    seen_md5 = set()          # 代码内容 md5 去重
    used_names = set()        # 输出文件名去重
    stats = dict.fromkeys(CATEGORIES, 0)
    scanned = py_blocks = hit = written = dup = 0

    for md_path in md_files:
        try:
            md_text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"[!] skip unreadable {md_path}: {exc}", file=sys.stderr)
            continue
        scanned += 1

        title = extract_title(md_text, md_path)
        safe_title = sanitize_name(title)
        seq = 0

        for kind, raw_code in extract_python_blocks(md_text):
            code = normalize_code(raw_code)
            py_blocks += 1
            if not looks_like_exp(code):
                continue
            if kind == "bare" and not looks_like_python_bare(code):
                continue  # 无标注块需额外通过 python 似真度判定
            hit += 1
            digest = hashlib.md5(code.strip().encode("utf-8", "replace")).hexdigest()
            if digest in seen_md5:
                dup += 1
                continue
            seen_md5.add(digest)

            category = infer_category(md_path, kb_root, title, code)
            seq += 1
            fname = f"{safe_title}__{seq:03d}.py"
            if fname.lower() in used_names:  # 不同 WP 撞名时加源摘要后缀
                fname = f"{safe_title}_{digest[:6]}__{seq:03d}.py"
            used_names.add(fname.lower())

            header = (
                f"# SOURCE: {md_path}\n"
                f"# TITLE: {title}\n"
                f"# CATEGORY: {category}\n\n"
            )
            (out_dir / category / fname).write_text(
                header + code.strip() + "\n", encoding="utf-8"
            )
            stats[category] += 1
            written += 1

    # ---------------- 统计输出 ----------------
    print("=" * 60)
    print("extract_exp_snippets 运行统计")
    print("=" * 60)
    print(f"知识库根目录        : {kb_root}")
    print(f"扫描 md 文件数      : {scanned}")
    print(f"python 围栏块总数   : {py_blocks}")
    print(f"命中 exp 特征块数   : {hit}")
    print(f"去重剔除重复块数    : {dup}")
    print(f"写入片段总数        : {written}")
    print("-" * 60)
    print("按分类分布:")
    for cat in CATEGORIES:
        bar = "#" * min(stats[cat], 50)
        print(f"  {cat:<10} {stats[cat]:>6}  {bar}")
    print("=" * 60)
    print(f"输出目录: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
