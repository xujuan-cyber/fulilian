"""Reasoner 类别判定与 flag 透传的回归锁。

改动前三个耦合缺陷：

1. ``_detect_category`` 用**子串**匹配扩展名与文件类型
   （``cat.value in ext.lower()``）——``.webp`` 含 "web" 被判成 WEB。
2. probe / benchmark / cli / knowledge 各层写的类别名是 ``"reverse"``，
   而本模块的 ``TaskCategory.REV == "rev"``。交界处按 ``cat.value == hint``
   严格相等比较，于是 probe 给出的 ``category_hint="reverse"`` **永远匹配
   不上**，逆向题一路掉到 MISC；planner 随后取不到 ``"rev"`` executor
   （specialists/factory.py 以 "rev" 为键注册）。
3. ``evaluate_and_revise`` 在 ``flag_found`` 但 ``flag`` 为空时补字面量
   ``"found"``。下游（racer 的 ``bool(self.flag)``、plan/flag 落盘）把「非空
   flag」当作已解出的凭据 —— 等于凭空虚报一个 flag。
"""

from __future__ import annotations

import pytest

from fulilian_ctf.probe import EnvInfo, FileInfo
from fulilian_ctf.reasoner import (
    Plan,
    Reasoner,
    TaskCategory,
    _normalize_category,
)


def _reasoner() -> Reasoner:
    return Reasoner.__new__(Reasoner)  # 只测纯函数，跳过 __init__ 的依赖装配


def _detect(hint="", files=(), category=None):
    env = EnvInfo(files=list(files))
    env.category_hint = hint

    class _Challenge:
        pass

    challenge = None
    if category is not None:
        challenge = _Challenge()
        challenge.category = category
    return _reasoner()._detect_category(challenge, env)


# ── 1. 词表归一：probe 的 "reverse" 必须落到 TaskCategory.REV ─────────────

@pytest.mark.parametrize(
    "raw", ["reverse", "Reverse", "REVERSE", "reversing", "reverse-engineering", "reverse_engineering"]
)
def test_reverse_hint_normalizes_to_rev(raw):
    """probe 层用 "reverse"，本模块用 "rev" —— 交界处必须归一。"""
    assert _detect(hint=raw) is TaskCategory.REV


def test_reverse_challenge_category_normalizes_to_rev():
    """challenge.category（benchmark CATEGORIES 也是 "reverse"）同样要归一。"""
    assert _detect(category="reverse") is TaskCategory.REV


def test_normalize_rejects_unknown_and_empty():
    for raw in ("", None, "   ", "blockchain", "quantum"):
        assert _normalize_category(raw) is None


def test_category_values_match_specialist_registry():
    """枚举值即 specialist 注册键；改名会静默丢掉 executor，这里钉死。"""
    from fulilian_ctf.specialists.factory import SpecialistFactory

    registered = set(SpecialistFactory.list_categories())
    assert {cat.value for cat in TaskCategory} <= registered, (
        f"枚举与注册表脱节：{ {c.value for c in TaskCategory} - registered }"
    )


# ── 2. 扩展名/文件类型：整段精确匹配，不再子串误判 ────────────────────────

def test_webp_is_not_classified_as_web():
    """`.webp` 含 "web" 子串，但 WebP 是取证类图片，不是 Web 题。"""
    got = _detect(files=[FileInfo(extension=".webp", file_type="RIFF (little-endian) data, Web/P image")])
    assert got is not TaskCategory.WEB
    assert got is TaskCategory.FORENSICS  # RIFF 命中 probe 的类型表


@pytest.mark.parametrize(
    "ext, file_type, want",
    [
        (".php", "PHP script, ASCII text", TaskCategory.WEB),
        (".html", "HTML document, ASCII text", TaskCategory.WEB),
        (".elf", "ELF 64-bit LSB executable", TaskCategory.REV),
        (".exe", "PE32 executable (console) Intel 80386", TaskCategory.REV),
        (".apk", "Zip archive data", TaskCategory.REV),
        (".pcap", "tcpdump capture file", TaskCategory.FORENSICS),
        ("php", "PHP script, ASCII text", TaskCategory.WEB),      # 无前导点也认
        ("", "PNG image data, 800 x 600", TaskCategory.FORENSICS),  # 靠类型表
    ],
)
def test_extension_and_type_inference(ext, file_type, want):
    assert _detect(files=[FileInfo(extension=ext, file_type=file_type)]) is want


def test_hint_wins_over_files():
    """category_hint 优先级高于文件推断（docstring 承诺的顺序）。"""
    files = [FileInfo(extension=".php", file_type="PHP script")]
    assert _detect(hint="crypto", files=files) is TaskCategory.CRYPTO


def test_unknown_everything_falls_back_to_misc():
    assert _detect() is TaskCategory.MISC
    assert _detect(files=[FileInfo(extension=".xyz", file_type="data")]) is TaskCategory.MISC


# ── 3. 不编造 flag ────────────────────────────────────────────────────────

def test_evaluate_and_revise_does_not_fabricate_flag():
    """flag_found 但 flag 为空时不得补一个 "found" 占位串。"""
    r = _reasoner()
    r._round = 0
    r._stuck_rounds = 0

    class _Feedback:
        task_id = "t1"
        success = True
        flag_found = True
        flag = ""
        is_stuck = False

    plan = r.evaluate_and_revise([_Feedback()])
    assert isinstance(plan, Plan)
    assert plan.is_done is True
    assert plan.flag == "", f"凭空补了一个 flag: {plan.flag!r}"


def test_evaluate_and_revise_passes_real_flag_through():
    r = _reasoner()
    r._round = 0
    r._stuck_rounds = 0

    class _Feedback:
        task_id = "t1"
        success = True
        flag_found = True
        flag = "flag{real}"
        is_stuck = False

    assert r.evaluate_and_revise([_Feedback()]).flag == "flag{real}"
