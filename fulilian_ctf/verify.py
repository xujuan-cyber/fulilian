"""三重校验门核心模块 (F1-001)。

候选 flag 出现 → Grounding 门（纯代码）→ Negation 门（LLM 怀疑者）
             → Interrogation 门（格式校验）→ 提交
                                         ↓ 失败
                                     待定（不提交）

设计遵循「宁可漏、不可误判」原则：
- 幻觉（不存于任何输出）→ HALLUCINATION，直接拒
- 诱饵 / 弱匹配（片段、截断、非 flag 结构）→ REJECTED，不交
- 逐字命中真实输出 → EXACT_MATCH，跳过对抗门直接进格式门
- 大小写/改写命中 → REWRITTEN，走对抗门
- 格式不符 → PENDING，降级待定（不提交但保留）

参考：hxbai（https://github.com/inwpu/hxbai）
实现指南：02-实施指南/02-P1-三重校验门.md
模块设计：03-代码设计/00-hermes_ctf模块设计.md（fulilian_ctf/verify.py）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

__all__ = [
    "VerificationResult",
    "ConfidenceLevel",
    "GateOutcome",
    "VerificationReport",
    "DEFAULT_FLAG_PATTERNS",
    "verify_flag",
    "verify_flag_with_report",
    "classify_confidence",
    "extract_flag_candidates",
    "check_output_for_flag",
    "is_flag_shaped",
]


class VerificationResult(Enum):
    """三重校验门最终结果。"""

    CONFIRMED = "confirmed"  # 通过所有门，可以提交
    HALLUCINATION = "hallucination"  # 第一门失败，直接拒
    REJECTED = "rejected"  # 第二门失败 / 诱饵，多数反驳
    PENDING = "pending"  # 第三门失败，降级待定


class ConfidenceLevel(Enum):
    """第一门（Grounding）输出的置信分级。"""

    EXACT_MATCH = "exact_match"  # 逐字命中真实输出，直接提交
    REWRITTEN = "rewritten"  # 改写/大小写命中，走对抗
    BAIT = "bait"  # 诱饵/弱匹配（片段、截断、仅归一化命中），不交
    HALLUCINATION = "hallucination"  # 不存于任何输出，直接拒


# Flag 格式模式（可配置；第三门 Interrogation 使用，匹配时忽略大小写）
DEFAULT_FLAG_PATTERNS = [
    r"flag\{[a-fA-F0-9\-]+\}",
    r"flag\{[^{}\s]{1,256}\}",  # catch-all：修正原设计字符类（含空格/花括号）的问题
    r"CTF\{[a-fA-F0-9\-]+\}",
    r"HTB\{[a-zA-Z0-9_]+\}",
    r"gctf\{[a-z0-9_]+\}",
    r"hkcert\d*\{[a-z0-9_]+\}",
]

# 结构形状：前缀(≥2 字符) + { + 非空内容(不含花括号/换行，≤256) + }
# 内容捕获组用于占位符检测（flag{...} / flag{xxx} 等题干示例）
_FLAG_SHAPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}\{([^{}\r\n]{1,256})\}$")
_FLAG_CANDIDATE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,31}\{[^{}\r\n]{1,256}\}")
# 占位符内容：全是 . / x / X（题干描述中的 flag{...} 示例）
_PLACEHOLDER_CONTENT_RE = re.compile(r"^[.xX]+$")


def _normalize(s: str) -> str:
    """去掉所有非字母数字字符并小写（用于弱匹配检测）。"""
    return re.sub(r"[^a-zA-Z0-9]", "", s).lower()


def is_flag_shaped(candidate: str) -> bool:
    """结构形状检查：是否为 ``prefix{...}`` 形态的完整字符串。

    只检查结构（有前缀、有花括号、内容非空且闭合），不校验具体格式——
    具体格式由第三门（Interrogation）负责。``flag{`` / ``abc123`` /
    ``session-42`` 之类均不通过；占位符内容（``flag{...}`` / ``flag{xxx}``）
    是题干示例而非真实 flag，同样不通过。
    """
    if not candidate:
        return False
    match = _FLAG_SHAPE_RE.fullmatch(candidate.strip())
    if not match:
        return False
    return not _PLACEHOLDER_CONTENT_RE.fullmatch(match.group(1))


def _grounding_check(candidate: str, evidence: str) -> ConfidenceLevel:
    """第一门：Grounding 定位 — 纯代码验证。

    分级逻辑（严格到宽松）：
    1. 逐字匹配（大小写敏感）→ EXACT_MATCH
    2. 大小写不敏感子串命中 → REWRITTEN（改写命中，走对抗门）
    3. 仅归一化（去符号+小写）子串命中 → BAIT（弱匹配：可能是截断片段）
    4. 前缀命中（候选前 4 字符出现在证据中）→ BAIT（诱饵）
    5. 否则 → HALLUCINATION

    注：归一化命中归为 BAIT 而非 REWRITTEN，是为了堵住「截断 flag」
    漏洞——``flag{123}`` 会归一化命中 ``flag{123456}``，若当作改写命中
    可能误交截断 flag。宁可漏、不可误判。
    """
    if not evidence:
        return ConfidenceLevel.HALLUCINATION
    if candidate in evidence:
        return ConfidenceLevel.EXACT_MATCH
    if candidate.lower() in evidence.lower():
        return ConfidenceLevel.REWRITTEN
    if len(candidate) >= 4 and _normalize(candidate) in _normalize(evidence):
        return ConfidenceLevel.BAIT
    if len(candidate) >= 4 and candidate[:4] in evidence:
        return ConfidenceLevel.BAIT
    return ConfidenceLevel.HALLUCINATION


def classify_confidence(candidate: str, evidence: str) -> ConfidenceLevel:
    """对候选 flag 进行置信分级（与第一门共用同一实现，避免逻辑漂移）。"""
    return _grounding_check(candidate, evidence)


def _negation_check(candidate: str, evidence: str) -> bool:
    """第二门：Negation 否定质疑 — Phase 1 规则实现。

    返回 True 表示被反驳（拒绝），False 表示通过。

    Phase 1 简化：候选不具备完整 flag 结构 → 反驳（拒绝）。
    Phase 2 将替换为 ``delegate_task`` 起「怀疑者」子 agent 的真实对抗，
    通过 ``verify_flag(..., negator=...)`` 注入即可，本函数签名保持不变。
    """
    return not is_flag_shaped(candidate)


def _interrogation_check(candidate: str, patterns: List[str]) -> bool:
    """第三门：Interrogation 追问复核 — 格式校验。

    使用 fullmatch（整串匹配，杜绝尾部垃圾）且忽略大小写
    （改写命中在对抗门通过后，大小写变体视为同一 flag）。
    """
    for pattern in patterns:
        if re.fullmatch(pattern, candidate, re.IGNORECASE):
            return True
    return False


@dataclass
class GateOutcome:
    """单扇门的判定记录。"""

    name: str  # grounding / negation / interrogation
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    """完整验证轨迹（供 solver 日志 / 黑板 / 轨迹 JSON 使用）。"""

    candidate: str
    result: VerificationResult
    confidence: Optional[ConfidenceLevel] = None
    gates: List[GateOutcome] = field(default_factory=list)

    def summary(self) -> str:
        """单行摘要，便于写入轨迹。"""
        parts = [f"candidate={self.candidate!r}", f"result={self.result.value}"]
        if self.confidence is not None:
            parts.append(f"confidence={self.confidence.value}")
        for gate in self.gates:
            parts.append(f"{gate.name}={'pass' if gate.passed else 'FAIL'}")
        return " | ".join(parts)


def _verify(
    candidate: str,
    evidence: str,
    flag_patterns: List[str],
    use_negation_llm: bool,
    require_grounding: bool,
    negator: Optional[Callable[[str, str], bool]],
) -> VerificationReport:
    """三重校验门内部实现（verify_flag / verify_flag_with_report 共用）。"""
    candidate = (candidate or "").strip()
    evidence = evidence or ""
    gates: List[GateOutcome] = []

    if not candidate:
        return VerificationReport(candidate, VerificationResult.REJECTED, gates=gates)

    # ========== 第一门：Grounding（定位）— 纯代码 ==========
    if require_grounding:
        confidence = _grounding_check(candidate, evidence)
        gates.append(
            GateOutcome("grounding", confidence is not ConfidenceLevel.HALLUCINATION,
                        f"level={confidence.value}")
        )
        if confidence is ConfidenceLevel.HALLUCINATION:
            return VerificationReport(candidate, VerificationResult.HALLUCINATION,
                                      confidence, gates)
        if confidence is ConfidenceLevel.BAIT:
            return VerificationReport(candidate, VerificationResult.REJECTED,
                                      confidence, gates)
    else:
        # 声明式提交路径（evidence 不可用，如 FLAG 文件提交）：
        # 跳过第一门，直接进入对抗门 + 格式门。
        confidence = None

    # ========== 第二门：Negation（否定质疑）— LLM / 规则 ==========
    # 仅改写命中（REWRITTEN）与声明式提交路径（无证据）走对抗门；
    # 逐字命中（EXACT_MATCH）直接提交，不调用对抗门。
    if confidence is not ConfidenceLevel.EXACT_MATCH and use_negation_llm:
        negator_fn = negator if negator is not None else _negation_check
        rebutted = negator_fn(candidate, evidence)
        gates.append(GateOutcome("negation", not rebutted,
                                 "rebutted" if rebutted else "passed"))
        if rebutted:
            return VerificationReport(candidate, VerificationResult.REJECTED,
                                      confidence, gates)

    # ========== 第三门：Interrogation（追问复核）— 格式校验 ==========
    if not is_flag_shaped(candidate):
        # 逐字/改写命中但结构不成 flag（诱饵，如 "flag{"、截断片段）
        gates.append(GateOutcome("interrogation", False, "not flag-shaped"))
        return VerificationReport(candidate, VerificationResult.REJECTED,
                                  confidence, gates)

    format_ok = _interrogation_check(candidate, flag_patterns)
    gates.append(GateOutcome("interrogation", format_ok,
                             "format ok" if format_ok else "no pattern matched"))
    if not format_ok:
        return VerificationReport(candidate, VerificationResult.PENDING,
                                  confidence, gates)

    return VerificationReport(candidate, VerificationResult.CONFIRMED,
                              confidence, gates)


def verify_flag_with_report(
    candidate: str,
    evidence: str,
    flag_patterns: Optional[List[str]] = None,
    use_negation_llm: bool = True,
    require_grounding: bool = True,
    negator: Optional[Callable[[str, str], bool]] = None,
) -> VerificationReport:
    """三重校验门主入口（带完整门级报告）。

    Args:
        candidate: 候选 flag 字符串
        evidence: 产生该候选的命令输出（用于 grounding 定位）
        flag_patterns: 可选的 flag 格式正则列表（默认 DEFAULT_FLAG_PATTERNS）
        use_negation_llm: 是否启用对抗门（默认 True；Phase 1 为规则实现，
            Phase 2 可注入 delegate_task 实现的 negator）
        require_grounding: 是否要求 grounding 定位。声明式提交（FLAG 文件
            提交，步骤 03）无 tool 输出可作证据时应传 False，此时只走
            对抗门 + 格式门。
        negator: 可插拔对抗函数 ``(candidate, evidence) -> bool``，返回
            True 表示反驳。Phase 2 注入 delegate_task 怀疑者。
    """
    if flag_patterns is None:
        flag_patterns = DEFAULT_FLAG_PATTERNS
    return _verify(candidate, evidence, flag_patterns,
                   use_negation_llm, require_grounding, negator)


def verify_flag(
    candidate: str,
    evidence: str,
    flag_patterns: Optional[List[str]] = None,
    use_negation_llm: bool = True,
    require_grounding: bool = True,
    negator: Optional[Callable[[str, str], bool]] = None,
) -> VerificationResult:
    """三重校验门主入口（返回 VerificationResult 枚举）。

    语义：
    - 幻觉（不存于任何输出）→ HALLUCINATION
    - 诱饵 / 弱匹配 / 结构不成 flag / 对抗被反驳 → REJECTED
    - 逐字命中真实输出且格式合规 → CONFIRMED（直接提交，跳过对抗门）
    - 改写命中 → 对抗门 → 通过且格式合规 → CONFIRMED
    - 结构是 flag 但格式不匹配任何已知模式 → PENDING（降级待定）
    """
    return verify_flag_with_report(
        candidate, evidence, flag_patterns=flag_patterns,
        use_negation_llm=use_negation_llm, require_grounding=require_grounding,
        negator=negator,
    ).result


def extract_flag_candidates(output: str, limit: int = 20) -> List[str]:
    """从工具输出中提取候选 flag（结构形状匹配，保序去重）。

    提取是宽松的（任何 ``prefix{...}`` 形状都收），具体是否成立由
    三重校验门裁决——宁可多收再由门过滤，也不漏掉未知前缀的真实 flag
    （如 NSSCTF{...}）。
    """
    if not output:
        return []
    seen: set[str] = set()
    result: List[str] = []
    for match in _FLAG_CANDIDATE_RE.finditer(output):
        cand = match.group(0)
        if cand not in seen:
            seen.add(cand)
            result.append(cand)
            if len(result) >= limit:
                break
    return result


def check_output_for_flag(
    output: str,
    flag_file: Optional[str] = None,
    *,
    flag_patterns: Optional[List[str]] = None,
    use_negation_llm: bool = True,
    require_grounding: bool = True,
    negator: Optional[Callable[[str, str], bool]] = None,
    attempts: Optional[List[VerificationReport]] = None,
) -> Optional[str]:
    """solver 集成点：检查工具输出中是否包含 flag，通过校验门后写 FLAG 文件。

    供 Phase 2 solver 在每次工具调用后调用；也是步骤 03「声明式提交」
    的前置筛选。首个 CONFIRMED 即返回（保序），其余候选的完整门级
    报告追加到 ``attempts``（若提供），供日志/黑板/轨迹使用。

    Args:
        output: 工具输出文本
        flag_file: 工作区 FLAG 文件路径（通过后写入 candidate + "\\n"）
        attempts: 可选的 VerificationReport 收集列表（每个候选一条）

    Returns:
        验证通过的 flag 字符串，或 None
    """
    for candidate in extract_flag_candidates(output):
        report = verify_flag_with_report(
            candidate, output, flag_patterns=flag_patterns,
            use_negation_llm=use_negation_llm,
            require_grounding=require_grounding, negator=negator,
        )
        if attempts is not None:
            attempts.append(report)
        if report.result is VerificationResult.CONFIRMED:
            if flag_file:
                path = Path(flag_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(candidate + "\n", encoding="utf-8")
            return candidate
    return None
