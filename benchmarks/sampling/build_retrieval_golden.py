#!/usr/bin/env python3
"""检索金标生成脚本（P4.5 重构版，三档分层）。

旧版（P1-4）的致命缺陷：query 由目标文档**自己的标题**构造，检索器只要
不是全坏就必然 top-1 命中自己 —— hit@5=1.0 是自证，测不出检索质量。
且 min_len=3 把 2 字中文 query（trigram 分词器的真实短板，见计划书 P4.1）
结构性排除在样本外。

新版三档（tier 字段区分）：

  smoke       5 条 —— 仍由标题构造 query，但只作**接线自检**（索引在不在、
              search() 通不通），meta 明示"NOT relevance"。hit@5 低于 1.0
              说明索引/管线坏了，接近 1.0 不说明检索好。
  realistic  10 条 —— 人工构造的解题者视角技术 query（如 "tcache poisoning
              堆利用"），expected_source_path 由**正文内容证据**标注：
              生成时逐条用 instr() 核验期望文档正文确含标注词（FTS5 trigram
              表的 UNINDEXED 列 LIKE 走 L3 计划会错返 0 行，禁用），核验
              失败即大声报错退出 —— 标签来自语料内容而非被测系统本身。
  robustness 6 条 —— 敌意 query（FTS 语法字符、操作符词、2 字中文、单字
              符），期望仅"search() 不抛异常"，记录命中数供回归对比。
              P4.2（sanitize 下沉进 search()）落地后此档即其回归。

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
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_PATH = REPO_ROOT / "benchmarks" / "retrieval-golden.yaml"
DEFAULT_DB = Path.home() / ".fulilian" / "knowledge.db"
DEFAULT_SEED = 20260905

# FTS5（trigram）操作符词与 token 清洗，口径与 knowledge._sanitize_query 一致
_FTS_OPERATOR_WORDS = {"and", "or", "not", "near"}
_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)

# ── realistic 档：人工标注（query → 期望文档 → 正文证据词）──────────────
# 标注依据：2026-09-14 对 knowledge.db 的 instr() 正文核验（见计划书 §9⑦）。
# 换库/换语料后重跑本脚本，正文核验不过会直接报错，不会静默生成假金标。
REALISTIC_PAIRS: list[dict] = [
    {
        "category": "web",
        "query": "ssti 模板注入 payload 绕过",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/SSTI.md",
        "verify_terms": ["ssti", "payload"],
    },
    {
        "category": "web",
        "query": "文件上传 waf 绕过",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/文件上传漏洞.md",
        "verify_terms": ["文件上传", "绕过"],
    },
    {
        "category": "web",
        "query": "sql注入 union 联合查询",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/SQL.md",
        "verify_terms": ["union", "注入"],
    },
    {
        "category": "pwn",
        "query": "tcache poisoning 堆利用",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/2023强网杯warmup题解.md",
        "verify_terms": ["tcache"],
    },
    {
        "category": "pwn",
        "query": "格式化字符串漏洞 泄露 libc 基址",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/2021西湖论剑IOT_RW-WriteUp.md",
        "verify_terms": ["格式化字符串", "libc"],
    },
    {
        "category": "web",
        "query": "java 反序列化 利用链",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/2023年第八届上海市大学生网络安全大赛Writeup.md",
        "verify_terms": ["反序列化", "java"],
    },
    {
        "category": "crypto",
        "query": "维吉尼亚密码 频率分析",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/2023年“羊城杯”网络安全大赛Writeup.md",
        "verify_terms": ["维吉尼亚"],
    },
    {
        "category": "crypto",
        "query": "RSA 共模攻击",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/官方Write_Up｜DASCTF_Apr.2023_X_SU战队2023开局之战.md",
        "verify_terms": ["共模"],
    },
    {
        "category": "forensics",
        "query": "volatility 内存镜像 取证",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/【Volatility3】护网杯_Easy_dump.md",
        "verify_terms": ["volatility"],
    },
    {
        "category": "reverse",
        "query": "ida 逆向 upx 脱壳",
        "source_path": "/home/xujuan/.fulilian/ctf-knowledge/CTF大赛WP集合/articles/2026年第三届“长城杯”网数智安全大赛Reverse_AK题解（含总决赛全部题目附件）.md",
        "verify_terms": ["ida", "upx"],
    },
]

# ── robustness 档：敌意 query，期望仅"不抛异常"───────────────────────────
ROBUSTNESS_QUERIES: list[dict] = [
    {"query": "2.31", "note": "纯数字+点（trigram token 边界）"},
    {"query": "\" OR \"1\"=\"1", "note": "引号与逻辑注入形态"},
    {"query": "AND OR NOT NEAR", "note": "裸 FTS 操作符词（大写）"},
    {"query": "注入", "note": "2 字中文 —— trigram 最小 token 之下的真实短板（P4.1）"},
    {"query": "()", "note": "纯语法字符"},
    {"query": "a", "note": "单字符"},
]


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


def load_db_rows(db_path: str) -> list[tuple]:
    """全量取 (title, category, source_path, content)。

    注意：writeups 是 FTS5 trigram 虚拟表，其 UNINDEXED 列上的 LIKE 依赖
    查询计划（L3 模式会错返 0 行），内容过滤一律在 Python 侧做。
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT title, category, source_path, content FROM writeups"
        ).fetchall()
    finally:
        conn.close()


def verify_realistic_labels(rows: list[tuple]) -> None:
    """生成时核验 realistic 档每条标注：期望文档在库内、正文确含证据词。

    标签若失效（语料更新/换库）必须大声失败，而不是生成一份假金标。
    """
    by_path = {r[2]: r for r in rows}
    failures = []
    for pair in REALISTIC_PAIRS:
        row = by_path.get(pair["source_path"])
        if row is None:
            failures.append(f"  [MISSING] {pair['source_path']} 不在库内")
            continue
        content = row[3] or ""
        missing = [t for t in pair["verify_terms"] if t.lower() not in content.lower()]
        if missing:
            failures.append(
                f"  [TERMS] {pair['source_path']} 缺证据词 {missing}"
            )
    if failures:
        print("[FATAL] realistic 档标签核验失败 —— 语料与标注脱节，拒绝生成：")
        print("\n".join(failures))
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="knowledge.db 路径（只读）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="smoke 档标题抽样的固定种子")
    parser.add_argument("--out", default=str(GOLDEN_PATH))
    args = parser.parse_args()

    rows = load_db_rows(args.db)

    # realistic 档：标签核验（失败即退出）
    verify_realistic_labels(rows)

    entries: list[dict] = []

    # ── smoke 档：标题构造 query（接线自检，NOT relevance）─────────────
    article_rows = [r for r in rows if "/articles/" in (r[2] or "")]
    by_cat: dict[str, list] = {}
    for title, category, source_path, _content in article_rows:
        by_cat.setdefault(category, []).append((title, source_path))
    rng = random.Random(args.seed)
    smoke_cats = ["web", "crypto", "pwn", "reverse", "forensics"]
    for cat in smoke_cats:
        pool = sorted(by_cat.get(cat, []))
        if not pool:
            print(f"[warn] smoke: category {cat} 无样本")
            continue
        title, source_path = rng.choice(pool)
        query = build_query(title)
        if not query:
            continue
        entries.append({
            "id": f"smoke-{len([e for e in entries if e['tier'] == 'smoke']) + 1:02d}",
            "tier": "smoke",
            "category": cat,
            "title": title,
            "query": query,
            "expected_source_path": source_path,
        })

    # ── realistic 档：人工标注，query 即解题者视角 ─────────────────────
    for pair in REALISTIC_PAIRS:
        entries.append({
            "id": f"real-{len([e for e in entries if e['tier'] == 'realistic']) + 1:02d}",
            "tier": "realistic",
            "category": pair["category"],
            "title": pair["source_path"].rsplit("/", 1)[-1],
            "query": pair["query"],
            "expected_source_path": pair["source_path"],
            "label_evidence": pair["verify_terms"],
        })

    # ── robustness 档：敌意 query，只测不崩 ────────────────────────────
    for spec in ROBUSTNESS_QUERIES:
        entries.append({
            "id": f"robust-{len([e for e in entries if e['tier'] == 'robustness']) + 1:02d}",
            "tier": "robustness",
            "category": None,
            "title": None,
            "query": spec["query"],
            "expected_source_path": None,
            "note": spec["note"],
        })

    header = {
        "comment": (
            "P4.5 检索金标 v2（三档：smoke 接线自检 / realistic 正文标注 / "
            "robustness 敌意 query）— 由 benchmarks/sampling/build_retrieval_golden.py 生成；"
            f"smoke 种子={args.seed}; 生成日期={date.today().isoformat()}; 库={args.db}; "
            "判定: knowledge_retriever.search(query, limit=5, auto_build=False)。"
            "smoke/realistic 计 hit@5（smoke 高分不代表检索好，仅证明管线通）；"
            "robustness 只要求 search() 不抛异常。只读检索。"
        ),
        "seed": args.seed,
    }
    doc = {"meta": header, "golden": entries}
    import yaml

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )

    n_smoke = sum(1 for e in entries if e["tier"] == "smoke")
    n_real = sum(1 for e in entries if e["tier"] == "realistic")
    n_rob = sum(1 for e in entries if e["tier"] == "robustness")
    print(f"wrote {out}: smoke={n_smoke} realistic={n_real} robustness={n_rob}")
    print("realistic 标签已逐条经正文证据词核验（instr，不走 FTS5 LIKE）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
