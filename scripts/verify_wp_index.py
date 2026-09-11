#!/usr/bin/env python3
"""统一验收 wp_technique_index.json + FTS 索引 + 双检索路径。

一条命令跑完全部哨兵，全绿时输出 `ALL SENTINELS OK`。

背景（2026-09 月度自查）：索引曾有三类畸形（Shiro 键缺 .md、WEB5 条目缺
difficulty/flag/exp、WEB2 的 exp 是空串而非空列表），且 build_index 用
_guess_category 覆盖了 JSON 里的权威 category（13 条里 3 条与 JSON 冲突），
导致 `search(category=...)` 对这 3 篇静默漏检。本脚本把修复后的期望值固化成
可重复执行的断言，防止回归。

用法：
    python scripts/verify_wp_index.py            # 只校验，不重建索引
    python scripts/verify_wp_index.py --rebuild   # 先 force 重建 FTS 再校验（约 35s）

注意：kr.search 走 FTS5 trigram，**短于 3 字符的 token 零命中**，所以哨兵词
一律 ≥3 字符且必须与正文逐字一致。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fulilian_ctf import knowledge_retriever as kr  # noqa: E402

INDEX = kr.KB_PATH / kr.TECHNIQUE_INDEX_RELPATH

# 期望条目数（新增 WP 后同步 +1，否则视为验收失败——数量变化必须是有意识的）
EXPECTED_ENTRIES = 13

# 必须存在的字段
REQUIRED_FIELDS = ("title", "source_path", "category", "difficulty", "flag", "exp")

# (WP 文件名, 期望 flag) —— 防"索引里 flag 被误改/丢失"
FLAG_ASSERTIONS = {
    "DASCTF_2026_WEB5_Flask_SSTI_attr无getitem回退.md":
        "CTF2{80f23122-5828-459f-a49b-1fb71a4e2cba}",
    "DASCTF_2026_WEB2_CVE-44268与mt_rand种子还原.md":
        "CTF2{d7e72881-82cc-4f20-b31a-bc20b1d0977d}",
}

# 2026-09 修复的 3 条：JSON 权威 category 必须与 FTS 里的一致（web）
CATEGORY_ASSERTIONS = {
    "DASCTF_multiSQL_堆叠注入REPLACE改成绩": "web",
    "DASCTF_2026_WEB2_CVE-44268与mt_rand种子还原": "web",
    "BUUCTF_2026_Shiro_黑盒渗透4flag_GCM版Shiro550打点": "web",
    "DASCTF_2026_WEB5_Flask_SSTI_attr无getitem回退": "web",
}

# (哨兵词, category) —— kr.search 路径；修复前这几条因分类错位而漏检
SEARCH_SENTINELS = [
    ("GCM版Shiro550", "web"),
    ("堆叠注入", "web"),
    ("mt_rand", "web"),
    ("getitem回退", "web"),
]

# 期望命中的 tags —— similar_by_technique 路径（只读 JSON，不读 category）
TECHNIQUE_SENTINELS = [
    (["shiro", "shiro-550"], "Shiro"),
    (["ssti", "jinja2"], "SSTI"),
]

ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    mark = "✅" if cond else "❌"
    if not cond:
        ok = False
    print(f"  {mark} {label}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="先 build_index(force=True) 再校验（改过 retriever 后必须加）")
    args = ap.parse_args()

    print(f"索引文件: {INDEX}")
    if not INDEX.exists():
        print("❌ 索引文件不存在")
        return 1

    # ── 1. JSON 结构 ────────────────────────────────────────────────
    print("\n[1] wp_technique_index.json 结构")
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    check(f"条目数 == {EXPECTED_ENTRIES}", len(data) == EXPECTED_ENTRIES,
          f"实际 {len(data)}")

    bad_keys = [k for k in data if not k.endswith(".md")]
    check("所有键以 .md 结尾", not bad_keys, f"异常: {bad_keys}")

    # source_path 必须存在，且 basename 与键一致（键/文件名不一致会让
    # similar_by_technique 按 key 匹配时漏掉该篇）
    missing_files, key_mismatch = [], []
    for k, v in data.items():
        sp = v.get("source_path", "")
        if not sp or not Path(sp).exists():
            missing_files.append(k)
        elif Path(sp).name != k:
            key_mismatch.append(f"{k} != {Path(sp).name}")
    check("source_path 全部存在", not missing_files, f"断链: {missing_files}")
    check("键与文件名一致", not key_mismatch, f"不一致: {key_mismatch}")

    incomplete = [(k, [f for f in REQUIRED_FIELDS if f not in v])
                  for k, v in data.items()]
    incomplete = [x for x in incomplete if x[1]]
    check("必需字段齐全", not incomplete, f"缺字段: {incomplete}")

    bad_exp = [k for k, v in data.items() if not isinstance(v.get("exp"), list)]
    check("exp 均为 list（空列表而非 \"\" / None）", not bad_exp, f"异常: {bad_exp}")

    # ── 2. flag 值断言 ──────────────────────────────────────────────
    print("\n[2] flag 值断言")
    for name, expect in FLAG_ASSERTIONS.items():
        got = data.get(name, {}).get("flag")
        check(f"{name[:38]}…", got == expect,
              "" if got == expect else f"期望 {expect!r} 实得 {got!r}")

    # ── 3. FTS 索引 ─────────────────────────────────────────────────
    if args.rebuild:
        print("\n[3] 重建 FTS 索引（force=True）")
        n = kr.build_index(force=True)
        check(f"build_index 入库 {n} 篇", n > 0)
    else:
        print("\n[3] FTS 索引（跳过重建；改过 retriever 请加 --rebuild）")

    if not kr.DB_PATH.exists():
        check("索引 DB 存在", False, str(kr.DB_PATH))
        return 1

    # ── 4. 分类一致（修复前这里是 3/13 冲突） ────────────────────────
    print("\n[4] 权威 category 与 FTS 一致")
    conn = sqlite3.connect(str(kr.DB_PATH))
    try:
        db_cats = {t: c for t, c in
                   conn.execute("SELECT title, category FROM writeups")}
    finally:
        conn.close()
    for title, expect in CATEGORY_ASSERTIONS.items():
        got = db_cats.get(title)
        check(f"{title[:40]}…", got == expect,
              "" if got == expect else f"期望 {expect} 实得 {got}")

    # ── 5. search 路径哨兵（含 category 过滤） ──────────────────────
    print("\n[5] kr.search 双路径哨兵")
    for kw, cat in SEARCH_SENTINELS:
        hits = kr.search(kw, category=cat, limit=5)
        check(f"search({kw!r}, category={cat!r})", bool(hits),
              f"{len(hits)} 命中" if hits else "0 命中——分类过滤漏检或哨兵词不在正文")

    # ── 6. similar_by_technique 路径哨兵 ───────────────────────────
    print("\n[6] similar_by_technique 哨兵")
    for tags, expect_sub in TECHNIQUE_SENTINELS:
        hits = kr.similar_by_technique(tags, limit=5)
        joined = " ".join(str(h.get("title", "")) for h in hits)
        check(f"tags={tags}", expect_sub in joined,
              f"{len(hits)} 命中" if expect_sub in joined else f"未命中 {expect_sub!r}")

    print()
    if ok:
        print("ALL SENTINELS OK")
        return 0
    print("SENTINELS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
