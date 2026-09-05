"""P0-1 回归锁：flag 门任意前缀（S-1）修复的参数化样例表。

修复契约：
1. is_flag_shaped 且非占位符的候选，在强置信（EXACT/REWRITTEN）或
   声明式提交（无证据路径，对抗门已过）时，第三门按形状放行。
2. 占位符 / BAIT / 幻觉 / 截断等拒绝侧行为与修复前一致。
3. 显式传入 flag_patterns 的调用方保持窄表收紧语义。

样例期望值以 2026-09-05 修复前实测为准（幻觉样例实测为
HALLUCINATION 而非 REJECTED）。
"""

import pytest

from fulilian_ctf.verify import DEFAULT_FLAG_PATTERNS, verify_flag_with_report

CASES = [
    # (candidate, evidence, require_grounding, expected_result)
    # --- 放行侧（修复目标）---
    ("NSSCTF{abc-123}", "the flag is NSSCTF{abc-123}", True, "CONFIRMED"),
    ("NSSCTF{abc-123}", "", False, "CONFIRMED"),
    ("CTFshow{flag_1s_here}", "output: CTFshow{flag_1s_here}", True, "CONFIRMED"),
    ("DASCTF{x1y2z3}", "DASCTF{x1y2z3} found", True, "CONFIRMED"),
    # --- 对照组（修复前后都 CONFIRMED）---
    ("flag{abc-123}", "the flag is flag{abc-123}", True, "CONFIRMED"),
    ("HTB{simple}", "HTB{simple}", True, "CONFIRMED"),
    # --- 拒绝侧（修复前后都不许变宽松）---
    ("flag{xxx}", "flag{xxx}", True, "REJECTED"),
    ("flag{....}", "flag{....}", True, "REJECTED"),
    ("NSSCTF{xxx}", "NSSCTF{xxx}", True, "REJECTED"),
    ("flag{123}", "flag{123456}", True, "REJECTED"),
    ("NSSCTF{nope}", "nothing here", True, "HALLUCINATION"),
    ("not-a-flag", "not-a-flag", True, "REJECTED"),
    ("NSSCTF{abc", "NSSCTF{abc", True, "REJECTED"),
]


@pytest.mark.parametrize("candidate,evidence,rg,expected", CASES)
def test_flag_prefix_matrix(candidate, evidence, rg, expected):
    report = verify_flag_with_report(candidate, evidence, require_grounding=rg)
    # 用 .name（大写枚举名）对照样例表；.value 是小写 ("confirmed")
    assert report.result.name == expected, f"gates={report.gates}"


def test_explicit_patterns_still_restrict():
    # 调用方显式传窄表时保持收紧语义（契约 3）
    r = verify_flag_with_report(
        "NSSCTF{abc-123}",
        "the flag is NSSCTF{abc-123}",
        flag_patterns=list(DEFAULT_FLAG_PATTERNS),
        require_grounding=True,
    )
    assert r.result.name == "PENDING"
