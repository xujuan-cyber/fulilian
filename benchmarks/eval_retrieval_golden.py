#!/usr/bin/env python3
"""检索金标评估入口（P4.5）。

跑 fulilian_ctf.benchmark.run_retrieval_suite（三档：smoke 接线自检 /
realistic 正文标注 / robustness 敌意 query），打印 JSON，可选落基线。

用法：
    python3 benchmarks/eval_retrieval_golden.py                    # 只跑
    python3 benchmarks/eval_retrieval_golden.py --save-baseline    # 落基线 JSON
    python3 benchmarks/eval_retrieval_golden.py --baseline baselines/xxx.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fulilian_ctf.benchmark import BASELINE_DIR, run_retrieval_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=None,
                        help="对比的基线 JSON；缺省只打分不对比")
    parser.add_argument("--save-baseline", action="store_true",
                        help="把本次结果落为 baselines/<date>-retrieval.json")
    args = parser.parse_args()

    summary = run_retrieval_suite()
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n────────── 摘要 ──────────")
    print(f"smoke       hit@5 = {summary['tier_hit_at_5'].get('smoke', 0):.0%}"
          "  （接线自检，高分≠检索好）")
    print(f"realistic   hit@5 = {summary['tier_hit_at_5'].get('realistic', 0):.0%}"
          "  ← 结论看这档")
    print(f"robustness  不抛异常 = {summary['robustness_all_ok']}")

    if args.save_baseline:
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        out = BASELINE_DIR / f"{date.today().isoformat()}-retrieval.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[eval] 基线已写入 {out}")
    if args.baseline:
        old = json.loads(args.baseline.read_text(encoding="utf-8"))
        for tier in ("smoke", "realistic"):
            now = summary["tier_hit_at_5"].get(tier, 0.0)
            base = old.get("tier_hit_at_5", {}).get(tier, 0.0)
            mark = "↑" if now > base else ("↓" if now < base else "=")
            print(f"[eval] {tier}: 基线 {base:.0%} → 现在 {now:.0%} {mark}")
        if old.get("robustness_all_ok") and not summary["robustness_all_ok"]:
            print("[eval] robustness 档出现异常 —— search() 对敌意 query 崩了")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
