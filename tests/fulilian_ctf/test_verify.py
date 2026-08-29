"""三重校验门 (F1-001) 单元测试。

覆盖：4 种置信级别（EXACT/REWRITTEN/BAIT/HALLUCINATION）
      4 种验证结果（CONFIRMED/HALLUCINATION/REJECTED/PENDING）
      对抗门注入（Phase 2 delegate_task 适配）、声明式提交路径适配。
"""

from __future__ import annotations

from fulilian_ctf.verify import (
    ConfidenceLevel,
    VerificationResult,
    check_output_for_flag,
    classify_confidence,
    extract_flag_candidates,
    is_flag_shaped,
    verify_flag,
    verify_flag_with_report,
)


# ── 文档自带 5 个用例 ────────────────────────────────────────────────────────

def test_exact_match():
    """逐字命中真实输出的 flag → CONFIRMED（直接提交）。"""
    assert verify_flag("flag{abc123}", "output: flag{abc123}") == VerificationResult.CONFIRMED


def test_hallucination():
    """凭空出现的幻觉 flag → HALLUCINATION（直接拒）。"""
    assert verify_flag("flag{xyz}", "output: nothing here") == VerificationResult.HALLUCINATION


def test_case_insensitive():
    """大小写改写的 flag → 走对抗门，通过 → CONFIRMED。"""
    result = verify_flag("Flag{ABC}", "output: flag{abc}")
    assert result == VerificationResult.CONFIRMED


def test_bait():
    """不完整 flag（无闭合花括号）即使逐字命中也是诱饵 → REJECTED。"""
    assert verify_flag("flag{", "output: flag{") == VerificationResult.REJECTED


def test_wrong_format():
    """非 flag 字符串逐字命中也不提交 → REJECTED。"""
    assert verify_flag("abc123", "output: abc123") == VerificationResult.REJECTED


# ── 4 种验证结果全覆盖 ───────────────────────────────────────────────────────

def test_pending_when_format_unknown():
    """结构是 flag 但不匹配任何已知格式 → PENDING（降级待定，不提交）。"""
    # CTF{zzz}：前缀合法但内容 zzz 不匹配 hex/字母数字模式
    assert verify_flag("CTF{zzz}", "output: CTF{zzz}") == VerificationResult.PENDING


def test_all_four_results_covered():
    """4 种验证结果均可到达。"""
    assert verify_flag("flag{abc}", "out: flag{abc}") == VerificationResult.CONFIRMED
    assert verify_flag("flag{abc}", "out: nothing") == VerificationResult.HALLUCINATION
    assert verify_flag("abc", "out: abc") == VerificationResult.REJECTED
    assert verify_flag("CTF{zzz}", "out: CTF{zzz}") == VerificationResult.PENDING


# ── 4 种置信级别全覆盖（classify_confidence） ───────────────────────────────

def test_confidence_levels():
    """4 种置信级别均可到达。"""
    assert classify_confidence("flag{abc}", "out: flag{abc}") == ConfidenceLevel.EXACT_MATCH
    assert classify_confidence("Flag{ABC}", "out: flag{abc}") == ConfidenceLevel.REWRITTEN
    # 仅归一化命中（截断片段）：flag{123} 是 flag{123456} 的前缀 → BAIT 弱匹配
    assert classify_confidence("flag{123}", "out: flag{123456}") == ConfidenceLevel.BAIT
    assert classify_confidence("flag{abc}", "out: nothing") == ConfidenceLevel.HALLUCINATION


# ── 对抗门（Negation）路径 ──────────────────────────────────────────────────

def test_rewritten_non_flag_rejected_by_negation():
    """改写命中但结构不成 flag → 对抗门反驳 → REJECTED。"""
    assert verify_flag("flag{", "output: FLAG{") == VerificationResult.REJECTED


def test_negation_disabled_skips_gate():
    """use_negation_llm=False：改写命中跳过对抗门，格式合规即 CONFIRMED。"""
    assert verify_flag("Flag{ABC}", "output: flag{abc}", use_negation_llm=False) == VerificationResult.CONFIRMED


def test_custom_negator_rebuts():
    """注入反驳一切的反驳者（Phase 2 delegate_task 适配）→ REJECTED。"""
    result = verify_flag("Flag{ABC}", "output: flag{abc}", negator=lambda c, e: True)
    assert result == VerificationResult.REJECTED


def test_custom_negator_passes():
    """注入从不反驳的反驳者 → 对抗通过 → CONFIRMED。"""
    result = verify_flag("Flag{ABC}", "output: flag{abc}", negator=lambda c, e: False)
    assert result == VerificationResult.CONFIRMED


def test_negator_not_called_on_exact_match():
    """逐字命中直接提交，不调用对抗门。"""
    calls: list = []

    def negator(c, e):
        calls.append(c)
        return True

    assert verify_flag("flag{abc}", "out: flag{abc}", negator=negator) == VerificationResult.CONFIRMED
    assert calls == []


# ── 声明式提交路径适配（步骤 03：evidence 不可用） ───────────────────────────

def test_empty_evidence_is_hallucination():
    """默认 require_grounding=True 且无证据 → HALLUCINATION（严格模式）。"""
    assert verify_flag("flag{abc}", "") == VerificationResult.HALLUCINATION


def test_require_grounding_false_accepts_valid_flag():
    """声明式提交（FLAG 文件，无 tool 输出作证据）：require_grounding=False。"""
    assert verify_flag("flag{abc123}", "", require_grounding=False) == VerificationResult.CONFIRMED


def test_require_grounding_false_rejects_non_flag():
    """声明式提交路径下非 flag 结构仍被对抗门拦截。"""
    assert verify_flag("abc123", "", require_grounding=False) == VerificationResult.REJECTED


# ── 格式门（Interrogation） ─────────────────────────────────────────────────

def test_custom_patterns():
    """自定义格式模式。"""
    custom = [r"MYCTF\{[0-9]{4}\}"]
    assert verify_flag("MYCTF{2026}", "out: MYCTF{2026}", flag_patterns=custom) == VerificationResult.CONFIRMED
    assert verify_flag("MYCTF{abc}", "out: MYCTF{abc}", flag_patterns=custom) == VerificationResult.PENDING


def test_known_prefix_families():
    """各常见 flag 前缀族均被识别。"""
    assert verify_flag("CTF{abcd1234}", "out: CTF{abcd1234}") == VerificationResult.CONFIRMED
    assert verify_flag("HTB{abc_def}", "out: HTB{abc_def}") == VerificationResult.CONFIRMED
    assert verify_flag("gctf{abc_123}", "out: gctf{abc_123}") == VerificationResult.CONFIRMED
    assert verify_flag("hkcert24{abc_1}", "out: hkcert24{abc_1}") == VerificationResult.CONFIRMED


def test_unknown_prefix_pending():
    """未知前缀但结构完整 → 不直接拒，降级待定。"""
    assert verify_flag("NSSCTF{abc}", "out: NSSCTF{abc}") == VerificationResult.PENDING


# ── 形状检查 ────────────────────────────────────────────────────────────────

def test_is_flag_shaped():
    assert is_flag_shaped("flag{abc}")
    assert is_flag_shaped("Flag{ABC}")
    assert is_flag_shaped("hkcert24{xyz_1}")
    assert not is_flag_shaped("flag{")          # 未闭合
    assert not is_flag_shaped("abc123")         # 无前缀/花括号
    assert not is_flag_shaped("flag{}")         # 内容为空
    assert not is_flag_shaped("")               # 空串


# ── 候选提取 ────────────────────────────────────────────────────────────────

def test_extract_candidates_dedupe_and_order():
    out = "got flag{abc} and flag{abc} again, CTF{123} then hkcert24{xyz_1}"
    assert extract_flag_candidates(out) == ["flag{abc}", "CTF{123}", "hkcert24{xyz_1}"]


def test_extract_candidates_case_and_prefix():
    assert extract_flag_candidates("FLAG{ABC} and NSSCTF{xyz}") == ["FLAG{ABC}", "NSSCTF{xyz}"]


def test_extract_candidates_no_flags():
    assert extract_flag_candidates("nothing here") == []
    assert extract_flag_candidates("") == []
    # 前缀太短（x{1}）不是 flag 形状
    assert extract_flag_candidates("print(x{1})") == []


# ── 占位符拒绝（题干/描述中的 flag{...} 示例不得误认）──────────────────────

def test_placeholder_ellipsis_not_shaped():
    assert not is_flag_shaped("flag{...}")
    assert not is_flag_shaped("flag{xxx}")
    assert not is_flag_shaped("flag{X}")


def test_placeholder_verify_rejected():
    # 题干描述里写了 flag{...} 示例 → 逐字命中也被拒，不能算解出
    assert verify_flag("flag{...}", "description: flag{...} 格式") == VerificationResult.REJECTED


def test_check_output_for_flag_skips_placeholder(tmp_path):
    """输出里只有占位符 → 不写 FLAG 文件、返回 None。"""
    flag_file = tmp_path / "FLAG"
    out = "题干示例 flag{...}，请解出真实标记"
    assert check_output_for_flag(out, str(flag_file)) is None
    assert not flag_file.exists()


def test_check_output_for_flag_real_flag_after_placeholder(tmp_path):
    """占位符在前、真实 flag 在后 → 返回真实 flag。"""
    flag_file = tmp_path / "FLAG"
    out = "示例 flag{...}，实际发现 flag{abc123}"
    assert check_output_for_flag(out, str(flag_file)) == "flag{abc123}"
    assert flag_file.read_text() == "flag{abc123}\n"


# ── solver 集成点 ───────────────────────────────────────────────────────────

def test_check_output_for_flag_writes_file(tmp_path):
    flag_file = tmp_path / "FLAG"
    out = "scan done. flag{abc123} found. also flag{decaf}"
    result = check_output_for_flag(out, str(flag_file))
    assert result == "flag{abc123}"  # 保序：首个 CONFIRMED
    assert flag_file.read_text() == "flag{abc123}\n"


def test_check_output_for_flag_no_candidates(tmp_path):
    flag_file = tmp_path / "FLAG"
    assert check_output_for_flag("nothing here", str(flag_file)) is None
    assert not flag_file.exists()


def test_check_output_for_flag_rejects_bad_format(tmp_path):
    flag_file = tmp_path / "FLAG"
    assert check_output_for_flag("value: abc123", str(flag_file)) is None
    assert not flag_file.exists()


def test_check_output_for_flag_attempts_log():
    attempts: list = []
    out = "noise CTF{zzz} and real flag{abc123}"
    result = check_output_for_flag(out, attempts=attempts)
    assert result == "flag{abc123}"
    assert len(attempts) == 2
    assert attempts[0].result is VerificationResult.PENDING
    assert attempts[1].result is VerificationResult.CONFIRMED


# ── 门级报告 ────────────────────────────────────────────────────────────────

def test_report_gates_exact_path():
    report = verify_flag_with_report("flag{abc123}", "out: flag{abc123}")
    assert report.result is VerificationResult.CONFIRMED
    assert report.confidence is ConfidenceLevel.EXACT_MATCH
    names = [g.name for g in report.gates]
    assert names == ["grounding", "interrogation"]  # 逐字命中跳过对抗门
    assert report.gates[0].passed
    assert report.gates[1].passed


def test_report_gates_rewritten_path():
    report = verify_flag_with_report("Flag{ABC}", "out: flag{abc}")
    assert report.result is VerificationResult.CONFIRMED
    assert report.confidence is ConfidenceLevel.REWRITTEN
    names = [g.name for g in report.gates]
    assert names == ["grounding", "negation", "interrogation"]


def test_report_summary_smoke():
    report = verify_flag_with_report("flag{abc123}", "out: flag{abc123}")
    s = report.summary()
    assert "candidate='flag{abc123}'" in s
    assert "result=confirmed" in s
    assert "grounding=pass" in s


# ── 边界 ────────────────────────────────────────────────────────────────────

def test_empty_candidate():
    assert verify_flag("", "out: flag{abc}") == VerificationResult.REJECTED
    assert verify_flag(None, "out: flag{abc}") == VerificationResult.REJECTED


def test_whitespace_candidate():
    assert verify_flag("  flag{abc}  ", "out: flag{abc}") == VerificationResult.CONFIRMED
