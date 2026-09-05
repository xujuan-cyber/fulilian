#!/usr/bin/env python3
"""检索金标抽样脚本（P1-4，可复现）。

从 ~/.fulilian/knowledge.db 的 writeups 表按题型分层随机抽 20 篇，
用标题构造 FTS5 友好的 query，生成 benchmarks/retrieval-golden.yaml。

可复现性：随机种子固定（--seed，默认 20260905）；分层配额固定
（web 6 / crypto 4 / pwn 3 / reverse 3 / forensics 2 / misc 2 = 20）。
同一种子 + 同一 knowledge.db → 同一份金标。重新生成会覆盖 golden 文件，
届时应同步更新基线并在 benchmarks/README.md 记录变更原因。

只读：以 URI 只读模式连接 knowledge.db，绝不写库。

用法：
    python3 benchmarks/sampling/build_retrieval_golden.py            # 默认种子
    python3 benchmarks/sampling/build_retrieval_golden.py --seed N
"""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_PATH = REPO_ROOT / "benchmarks" / "retrieval-golden.yaml"
DEFAULT_DB = Path.home() / ".fulilian" / "knowledge.db"

# 分层配额：按库内体量加权但压缩 web 占比（web 1450 篇独大，全按比例会失衡）
STRATUM = {"web": 6, "crypto": 4, "pwn": 3, "reverse": 3, "forensics": 2, "misc": 2}
DEFAULT_SEED = 20260905

# FTS5（trigram）保留操作符词与 token 清洗，口径与 knowledge._sanitize_query 一致
_FTS_OPERATOR_WORDS = {"and", "or", "not", "near"}
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def build_query(title: str, min_len: int = 3, max_tokens: int = 6) -> str:
    """标题 → FTS5 MATCH 查询串：去重 token、丢操作符词与过短 token，
    双引号短语包裹后 OR 连接（与知识注入检索同一容错口径）。"""
    seen: list[str] = []
    for tok in _TOKEN_RE.findall(title or ""):
        low = tok.lower()
        if low in _FTS_OPERATOR_WORDS or len(low) < min_len:
            continue
        if tok not in seen:
            seen.append(tok)
        if len(seen) >= max_tokens:
            break
    return " OR ".join(f'"{t}"' for t in seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="knowledge.db 路径（只读）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="固定随机种子")
    parser.add_argument("--out", default=str(GOLDEN_PATH))
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        # 注意：writeups 是 FTS5 虚拟表，LIKE 在其列上不可用——
        # 全量取回后在 Python 侧过滤（只读，2564 行开销可忽略）。
        rows = conn.execute(
            "SELECT title, category, source_path FROM writeups"
        ).fetchall()
    finally:
        conn.close()

    # 抽样池只取正式 WP 集合文章（排除 .claude/skills 等非语料条目）
    rows = [r for r in rows if "/articles/" in (r[2] or "")]

    by_cat: dict[str, list] = {}
    for title, category, source_path in rows:
        by_cat.setdefault(category, []).append((title, source_path))

    rng = random.Random(args.seed)
    picked = []
    for cat in sorted(STRATUM, key=lambda c: -STRATUM[c]):
        pool = by_cat.get(cat, [])
        k = min(STRATUM[cat], len(pool))
        if k < STRATUM[cat]:
            print(f"[warn] category {cat}: pool has {len(pool)} < quota {STRATUM[cat]}")
        picked += rng.sample(sorted(pool), k)
    rng.shuffle(picked)  # 打乱类别顺序，避免检索器按文件序偏置

    entries = []
    skipped = 0
    for title, source_path in picked:
        query = build_query(title)
        if not query:
            skipped += 1
            continue
        cat = next(c for c, pool in by_cat.items() if (title, source_path) in pool)
        entries.append({
            "id": f"golden-{len(entries) + 1:02d}",
            "category": cat,
            "title": title,
            "query": query,
            "expected_source_path": source_path,
        })
    if skipped:
        print(f"[warn] skipped {skipped} rows with empty sanitized query")

    header = {
        "comment": (
            "P1-4 检索金标（20 条）— 由 benchmarks/sampling/build_retrieval_golden.py 生成；"
            f"种子={args.seed}; 生成日期={date.today().isoformat()}; 库={args.db}; "
            "判定: knowledge_retriever.search(query, limit=5, auto_build=False) 的 "
            "top-5 source_path 含 expected_source_path 即命中（hit@5）。只读检索。"
        ),
        "seed": args.seed,
        "stratum_quota": STRATUM,
    }
    doc = {"meta": header, "golden": entries}
    import yaml

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )

    print(f"wrote {out}: {len(entries)} golden pairs (seed={args.seed})")
    print("category distribution:", dict(Counter(e['category'] for e in entries)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
