"""专题技术文档分段索引（P4.3 v1）。

语料库（``~/.fulilian/ctf-knowledge``）的用法约定是"按需分段读取"（
``Read offset=行号 limit=行数``），但手工维护的 ``*.idx.md`` 行号与文档
实际标题漂移严重（P4.3 探针：108 段抽检 35 段不符，如「宽字节」实际在
SQL.md L928、索引写 L450）——所以本模块运行时直接从文档 ``#{1,3}`` 标题
自建索引，永不漂移，也不依赖手工索引的新鲜度。

设计取舍：
- 段索引只有几百条标题，内存 token 子串匹配足够，不上 FTS5（避开
  trigram 对 2 字 CJK 的已知坑，见 §3.E）。
- 相关性闸门（噪声比沉默更贵，与 ``_wp_refs_block`` 同哲学）：命中资格
  = >=2 个不同查询 token 出现在标题，或单个 len>=3 的具体 token 命中；
  2 字泛词（「绕过」「注入」等）单独出现不入选。
- ASCII token 用词边界匹配（``ida`` 不得命中 ``IDAT``），CJK 保持子串。
- 专题库只覆盖 web/forensics-misc 域；域外查询（pwn/crypto/reverse）
  正确沉默而非硬凑，评测见计划书 §9 P4.3 条目。
"""

from __future__ import annotations

import os
import re
from typing import NamedTuple, Optional

_HEAD_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")
_TOKEN_RE = re.compile(r"[\w一-鿿]+")
# ASCII/数字 token 要求词边界：子串匹配会把 "ida" 匹配进 "IDAT"
_ASCII_TOKEN_RE = re.compile(r"^[a-z0-9_]+$")

# 非专题文档：目录/变更记录/搜索索引，标题无技术含义
_SKIP_DOCS = frozenset({"README.md", "CHANGELOG.md", "AI-SEARCH-INDEX.md"})

# 专题文档 → 题目分类（口径与 DIR_CATEGORY_MAP 一致：隐写=forensics）。
# 不在此表中的 .md 不进索引（域外保持沉默）。
DOC_CATEGORY_MAP: dict[str, str] = {
    "SQL": "web",
    "SSRF漏洞": "web",
    "SSTI": "web",
    "JWT": "web",
    "文件包含": "web",
    "文件上传漏洞": "web",
    "php代码审计": "web",
    "命令执行": "web",
    "PHP反序列化漏洞总结": "web",
    "PAYLOAD-CHEATSHEET": "web",
    "图片隐写": "forensics",
    "音频隐写": "forensics",
    "压缩包总结": "misc",
}

_MAX_TITLE_CHARS = 45  # 过长标题多为叙述句/代码行；句号结尾的直接排除

# path -> ((mtime, size), segments)，mtime 校验保证编辑后自动失效
_cache: dict[str, tuple[tuple[int, int], list["TopicSegment"]]] = {}


class TopicSegment(NamedTuple):
    """一个可直达的分段：Read offset=line 即从该标题开始读。"""

    doc: str  # 文档名（不含 .md），即 DOC_CATEGORY_MAP 的键
    doc_path: str
    line: int  # 标题所在行（1-based）
    title: str


def _parse_doc(doc_path: str) -> list[TopicSegment]:
    stem = os.path.basename(doc_path)[:-3]
    segs: list[TopicSegment] = []
    try:
        with open(doc_path, encoding="utf-8", errors="replace") as f:
            for i, ln in enumerate(f, 1):
                m = _HEAD_RE.match(ln)
                if not m:
                    continue
                title = m.group(1).strip()
                # 句子级标题（以句号收尾）不进索引；上限内复合技术标题保留
                if not title or title.endswith("。") or len(title) > _MAX_TITLE_CHARS:
                    continue
                segs.append(TopicSegment(stem, doc_path, i, title))
    except OSError:
        return []
    return segs


def _cached_segments(doc_path: str) -> list[TopicSegment]:
    try:
        st = os.stat(doc_path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return []
    hit = _cache.get(doc_path)
    if hit and hit[0] == key:
        return hit[1]
    segs = _parse_doc(doc_path)
    _cache[doc_path] = (key, segs)
    return segs


def _token_in(token: str, title_lower: str) -> bool:
    if _ASCII_TOKEN_RE.match(token):
        return re.search(
            r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", title_lower
        ) is not None
    return token in title_lower


def match_topic_segments(
    query_text: str,
    category: Optional[str] = None,
    limit: int = 2,
) -> list[TopicSegment]:
    """按查询 token 与标题的重叠匹配专题分段，按相关度降序。

    Args:
        query_text: 查询文本（题面关键词，或 sanitize 后的 OR 查询串——
            本模块的 tokenizer 对两种形态都适用）。
        category: 题目分类；非空时只返回该分类的专题文档命中的段。
        limit: 最多返回条数。

    Returns:
        list[TopicSegment]：无命中/域外查询/语料库缺失时返回空表。
    """
    if not query_text or limit <= 0:
        return []
    # 查询串可能是 sanitize 后的 OR 连接形态，剔除字面操作符并去重
    from .knowledge_retriever import _MATCH_OPERATOR_WORDS

    tokens = [
        t
        for t in _TOKEN_RE.findall(query_text.lower())
        if len(t) >= 2 and t not in _MATCH_OPERATOR_WORDS
    ]
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        return []
    cat = (category or "").strip().lower()

    try:
        from .knowledge_retriever import _resolve_kb_path

        kb_root = _resolve_kb_path()
    except Exception:  # noqa: BLE001 — 语料库解析失败静默降级
        return []
    if not kb_root or not os.path.isdir(kb_root):
        return []

    scored: list[tuple[int, int, int, TopicSegment]] = []
    for stem, cat_of in DOC_CATEGORY_MAP.items():
        if cat and cat_of != cat:
            continue
        doc_path = os.path.join(kb_root, stem + ".md")
        for seg in _cached_segments(doc_path):
            title_lower = seg.title.lower()
            matched = [t for t in tokens if _token_in(t, title_lower)]
            if not matched:
                continue
            # 资格闸门：>=2 个不同 token，或单个 len>=3 的具体 token
            if len(matched) < 2 and max(len(t) for t in matched) < 3:
                continue
            scored.append(
                (
                    len(set(matched)),
                    max(len(t) for t in matched),
                    -seg.line,
                    seg,
                )
            )
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [s[3] for s in scored[:limit]]
