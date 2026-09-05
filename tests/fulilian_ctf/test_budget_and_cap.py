"""P1-1 回归锁：止损预算口径合并（H-3）+ CTF 压缩阈值封顶一等化（M-1）。

H-3：运行中预算判定 = usage.json（已完成尝试累计）+ log 估算（当前尝试），
相加而非互斥取一；任何情况下判定值不得小于修复前（只会更早触发，安全侧）。
M-1：CTF 模式 0.6 封顶写在 _config_threshold_percent（重派生源头），
update_model 换模型后不回弹；非 CTF 模式零变化。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from fulilian_ctf.dispatcher import Dispatcher

try:
    from fulilian_ctf.stopper import USAGE_FILE
except ImportError:  # 旧版 stopper 无 usage.json 支持
    USAGE_FILE = "usage.json"

try:
    from fulilian_ctf.stopper import usage_tokens as _usage_tokens
    _HAS_USAGE_TOKENS = True
except ImportError:  # 旧版 stopper：预算判定退化为纯 log 估算
    _HAS_USAGE_TOKENS = False

# 依赖 usage.json 精确口径的用例在旧版 stopper 下跳过
_requires_usage = pytest.mark.skipif(
    not _HAS_USAGE_TOKENS, reason="stopper.usage_tokens 不存在（旧版 stopper）"
)


@pytest.fixture
def dispatcher():
    return Dispatcher(quiet=True)


# ── H-3：预算口径相加 ────────────────────────────────────────────────

@_requires_usage
def test_budget_tokens_sums_usage_and_log(dispatcher, tmp_path):
    (tmp_path / USAGE_FILE).write_text(
        json.dumps({"total_tokens": 100000}), encoding="utf-8"
    )
    (tmp_path / "solver.log").write_text("x" * 200_000, encoding="utf-8")  # ≈50k
    tokens = dispatcher._budget_tokens(tmp_path, None)
    assert tokens == 150_000
    # 验收原文场景：usage.json=100k + 大 log → 应命中 BUDGET（100k 预算下）
    stopper = dispatcher.stopper
    stopper.max_tokens = 120_000
    assert stopper.check(project_tokens=tokens, rounds_without_new_fact=0,
                         variant_failures=0, is_infra_blocked=False,
                         has_partial_flag=False) == "BUDGET_EXCEEDED"


def test_budget_tokens_without_usage_file(dispatcher, tmp_path):
    (tmp_path / "solver.log").write_text("x" * 40_000, encoding="utf-8")
    assert dispatcher._budget_tokens(tmp_path, None) == 10_000  # 0 + est


@_requires_usage
def test_budget_tokens_with_empty_log(dispatcher, tmp_path):
    (tmp_path / USAGE_FILE).write_text(
        json.dumps({"total_tokens": 77_000}), encoding="utf-8"
    )
    assert dispatcher._budget_tokens(tmp_path, None) == 77_000  # exact + 0


@_requires_usage
def test_budget_tokens_never_below_either_source(dispatcher, tmp_path):
    # 契约 2：判定值 >= max(exact, est)（双计窗口只提前不推迟）
    (tmp_path / USAGE_FILE).write_text(
        json.dumps({"total_tokens": 30_000}), encoding="utf-8"
    )
    (tmp_path / "solver.log").write_text("x" * 80_000, encoding="utf-8")  # est 20k
    assert dispatcher._budget_tokens(tmp_path, None) >= 30_000


def test_budget_tokens_counter_still_wins(dispatcher, tmp_path):
    assert dispatcher._budget_tokens(tmp_path, lambda wd: 12345) == 12345


# ── M-1：压缩阈值封顶一等化 ──────────────────────────────────────────

def _make_compressor(threshold_percent=0.8):
    from agent.context_compressor import ContextCompressor

    c = ContextCompressor(model="cap-test-model", threshold_percent=threshold_percent)
    # 1M 大窗口：小窗口 floor（<512K 抬到 ≥0.6）不生效，阈值语义最纯粹
    c.context_length = 1_000_000
    return c


def test_cap_at_config_source_survives_update_model():
    from run_agent import _cap_ctf_compression_threshold

    c = _make_compressor(0.8)
    assert c.threshold_percent == 0.8
    _cap_ctf_compression_threshold(SimpleNamespace(context_compressor=c))
    assert getattr(c, "_config_threshold_percent") == 0.6  # 源头封顶
    assert c.threshold_percent <= 0.6
    # 换模型 / fallback 激活 → 派生自封顶后的源头，不回弹
    c.update_model("other-model", context_length=1_000_000)
    assert c.threshold_percent <= 0.6


def test_cap_noop_when_below_cap():
    from run_agent import _cap_ctf_compression_threshold

    c = _make_compressor(0.5)
    _cap_ctf_compression_threshold(SimpleNamespace(context_compressor=c))
    assert c.threshold_percent == 0.5  # 未被封顶改动


def test_non_ctf_path_untouched():
    # 非 CTF：不走 cap → update_model 后保持 0.8（零变化）
    c = _make_compressor(0.8)
    c.update_model("other-model", context_length=1_000_000)
    assert c.threshold_percent == 0.8
