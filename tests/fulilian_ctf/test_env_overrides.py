"""env_overrides 通用解析器测试。

覆盖矩阵：未设 / 空串 / 空白 / 非数字 / 负数 / 0 / 越界 / 边界 / 畸形条目 / 部分覆盖。
接线级测试（timebox / stopper / loop_guard / probe / dispatcher / cli）在各模块
落地时追加到本文件末尾。

注意：本文件的 autouse fixture 会把登记表里的**全部** env 名清掉，因此本文件可以
独立运行，不依赖 ``tests/conftest.py`` 的清理名单。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fulilian_ctf import cli
from fulilian_ctf import dispatcher as dp
from fulilian_ctf import env_overrides as eo
from fulilian_ctf import loop_guard as lg
from fulilian_ctf import probe as pr
from fulilian_ctf import stopper as st
from fulilian_ctf import timebox as tb


@pytest.fixture(autouse=True)
def _clean_override_env(monkeypatch):
    """清掉登记表里的每一个 env，保证每个用例从"全未设"开始。"""
    for entry in eo.OVERRIDE_REGISTRY:
        monkeypatch.delenv(entry.env, raising=False)


# ── env_int ──────────────────────────────────────────────────────────────────


def test_env_int_unset_returns_default():
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7) == 7


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_env_int_blank_returns_default(monkeypatch, raw):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", raw)
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7) == 7


@pytest.mark.parametrize("raw", ["abc", "7.5", "0x10", "12abc", "--3"])
def test_env_int_malformed_returns_default(monkeypatch, raw):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", raw)
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7) == 7


def test_env_int_valid_parses(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", "42")
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7) == 42


def test_env_int_whitespace_tolerated(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", "  42  ")
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7) == 42


def test_env_int_below_min_falls_back(monkeypatch):
    """显式 0 / 负数对多数旋钮表示"未指定"→ 回退默认。"""
    for raw in ("0", "-1", "-999"):
        monkeypatch.setenv("FULILIAN_CTF_TEST_INT", raw)
        assert eo.env_int("FULILIAN_CTF_TEST_INT", 7, min_value=1) == 7, raw


def test_env_int_min_boundary_accepted(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", "1")
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7, min_value=1) == 1


def test_env_int_above_max_falls_back(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", "11")
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7, max_value=10) == 7


def test_env_int_max_boundary_accepted(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", "10")
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7, max_value=10) == 10


def test_env_int_zero_min_allows_zero(monkeypatch):
    """min_value=0 时 0 是合法值（timebox_override 这类哨兵旋钮）。"""
    monkeypatch.setenv("FULILIAN_CTF_TEST_INT", "0")
    assert eo.env_int("FULILIAN_CTF_TEST_INT", 7, min_value=0) == 0


# ── env_float ────────────────────────────────────────────────────────────────


def test_env_float_unset_returns_default():
    assert eo.env_float("FULILIAN_CTF_TEST_FLOAT", 1.5) == 1.5


@pytest.mark.parametrize("raw", ["", "  ", "abc", "1.2.3"])
def test_env_float_bad_returns_default(monkeypatch, raw):
    monkeypatch.setenv("FULILIAN_CTF_TEST_FLOAT", raw)
    assert eo.env_float("FULILIAN_CTF_TEST_FLOAT", 1.5) == 1.5


def test_env_float_valid_parses(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_FLOAT", "2.25")
    assert eo.env_float("FULILIAN_CTF_TEST_FLOAT", 1.5) == 2.25


def test_env_float_integer_string_parses(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_FLOAT", "3")
    assert eo.env_float("FULILIAN_CTF_TEST_FLOAT", 1.5) == 3.0


def test_env_float_below_min_falls_back(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_FLOAT", "0.5")
    assert eo.env_float("FULILIAN_CTF_TEST_FLOAT", 1.5, min_value=1.0) == 1.5


# ── env_int_list ─────────────────────────────────────────────────────────────


def test_env_int_list_unset_returns_default_copy():
    default = [300, 900]
    result = eo.env_int_list("FULILIAN_CTF_TEST_LIST", default)
    assert result == default
    assert result is not default  # 新列表，不回传调用方的可变对象


def test_env_int_list_mutating_result_does_not_touch_default():
    default = [300, 900]
    result = eo.env_int_list("FULILIAN_CTF_TEST_LIST", default)
    result.append(1800)
    assert default == [300, 900]


def test_env_int_list_valid_sorted_deduped(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", "900,300,900,1800")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [1]) == [300, 900, 1800]


def test_env_int_list_whitespace_tolerated(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", " 300 , 900 ,, 1800 ")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [1]) == [300, 900, 1800]


def test_env_int_list_skips_malformed_entries(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", "300,abc,900")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [1]) == [300, 900]


def test_env_int_list_all_malformed_returns_default(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", "abc,def")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [300, 900]) == [300, 900]


def test_env_int_list_single_value(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", "600")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [1]) == [600]


def test_env_int_list_min_value_filters(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", "0,-5,300")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [1], min_value=1) == [300]


def test_env_int_list_all_below_min_returns_default(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_LIST", "0,-5")
    assert eo.env_int_list("FULILIAN_CTF_TEST_LIST", [300], min_value=1) == [300]


# ── env_int_map ──────────────────────────────────────────────────────────────

_MAP_DEFAULT = {"easy": 300, "medium": 900, "hard": 600}


def test_env_int_map_unset_returns_default_copy():
    result = eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT)
    assert result == _MAP_DEFAULT
    assert result is not _MAP_DEFAULT


def test_env_int_map_partial_override_keeps_other_keys(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "medium:1800")
    assert eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT) == {
        "easy": 300,
        "medium": 1800,
        "hard": 600,
    }


def test_env_int_map_does_not_mutate_default(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "medium:1800")
    eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT)
    assert _MAP_DEFAULT == {"easy": 300, "medium": 900, "hard": 600}


def test_env_int_map_key_case_insensitive(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "HARD:1000, Medium : 1200")
    assert eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT) == {
        "easy": 300,
        "medium": 1200,
        "hard": 1000,
    }


def test_env_int_map_skips_malformed_but_keeps_valid(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "nope,medium:abc,hard:1000")
    assert eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT) == {
        "easy": 300,
        "medium": 900,
        "hard": 1000,
    }


def test_env_int_map_all_malformed_returns_default(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "nope,alsonope")
    assert eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT) == _MAP_DEFAULT


def test_env_int_map_min_value_filters(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "easy:0,hard:1000")
    assert eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT, min_value=1) == {
        "easy": 300,
        "medium": 900,
        "hard": 1000,
    }


def test_env_int_map_adds_new_key(monkeypatch):
    monkeypatch.setenv("FULILIAN_CTF_TEST_MAP", "expert:3600")
    assert eo.env_int_map("FULILIAN_CTF_TEST_MAP", _MAP_DEFAULT)["expert"] == 3600


# ── env_cooldowns 已随递增冷却机制一同移除（2026-09-17）────────────────────
# 它依赖"平台判错"能正确记账，而该判定的极性是错的 → 冷却从未真正生效。
# 平台提交已整体移除（2026-09-17），本文件不再有提交相关的旋钮。


# ── 登记表完整性 ─────────────────────────────────────────────────────────────


def _env_names_from_all() -> set:
    return {
        getattr(eo, name)
        for name in eo.__all__
        if name.startswith("ENV_") and isinstance(getattr(eo, name), str)
    }


def test_registry_covers_every_env_constant():
    """登记表必须覆盖模块导出的每一个 ENV_* 名，防漏登记。"""
    assert _env_names_from_all() == {entry.env for entry in eo.OVERRIDE_REGISTRY}


def test_registry_env_names_unique():
    names = [entry.env for entry in eo.OVERRIDE_REGISTRY]
    assert len(names) == len(set(names))


def test_registry_env_names_use_project_prefix():
    for entry in eo.OVERRIDE_REGISTRY:
        assert entry.env.startswith("FULILIAN_CTF_"), entry.env


def test_describe_overrides_lists_every_env():
    text = eo.describe_overrides()
    for entry in eo.OVERRIDE_REGISTRY:
        assert entry.env in text, entry.env


def test_conftest_blank_lists_every_env():
    """``tests/conftest.py`` 的清理名单必须覆盖登记表全部 env。

    漏一个就意味着：只要开发者 shell 里 export 了它，断言具体数值的既有测试
    （test_timebox / test_stopper / test_usage_budget_tiers / test_loop_guard /
    test_submit_guard / test_harvest_escalation）会以"数值或字符串不匹配"的形式
    挂掉，而现象离真因很远。这条测试把"加了旋钮但忘了登记清理"挡在 CI 里。
    """
    conftest = Path(__file__).resolve().parents[1] / "conftest.py"
    source = conftest.read_text(encoding="utf-8")
    for entry in eo.OVERRIDE_REGISTRY:
        assert f'"{entry.env}"' in source, f"{entry.env} 未加入 _FULILIAN_BEHAVIORAL_VARS"


# ── 接线：timebox ────────────────────────────────────────────────────────────


def test_timebox_regression_no_env_matches_constants():
    """零行为变更护栏：env 全未设时，构造结果与既有常量逐字段一致。"""
    assert tb.tier_thresholds() == tb.TIER_THRESHOLDS
    assert tb.difficulty_budgets() == tb.DIFFICULTY_BUDGETS
    assert tb.difficulty_adjusted_budget("easy") == 300
    assert tb.difficulty_adjusted_budget("medium") == 900
    assert tb.difficulty_adjusted_budget("hard") == 600
    assert tb.Timebox().budgets == [300, 900, 1800, 3600]
    assert tb.Timebox().initial_budget == 300


def test_timebox_tier_thresholds_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_TIER_THRESHOLDS, "120,600")
    assert tb.tier_thresholds() == [120, 600]
    assert tb.Timebox(initial_budget=120).budgets == [120, 600]


def test_timebox_difficulty_budgets_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_DIFFICULTY_BUDGETS, "hard:1500")
    assert tb.difficulty_adjusted_budget("hard") == 1500
    assert tb.difficulty_adjusted_budget("medium") == 900  # 未覆盖项保持默认


def test_timebox_difficulty_budgets_env_partial_keeps_other_keys(monkeypatch):
    monkeypatch.setenv(eo.ENV_DIFFICULTY_BUDGETS, "easy:120")
    assert tb.difficulty_budgets() == {"easy": 120, "medium": 900, "hard": 600}


def test_timebox_unknown_difficulty_follows_easy(monkeypatch):
    """未知难度（含空串、expert）回退到生效的 easy 档。"""
    monkeypatch.setenv(eo.ENV_DIFFICULTY_BUDGETS, "easy:180")
    for difficulty in ("unknown", "", "expert", "EASY"):
        assert tb.difficulty_adjusted_budget(difficulty) == 180, difficulty


def test_timebox_default_initial_budget_follows_easy_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_DIFFICULTY_BUDGETS, "easy:600")
    box = tb.Timebox()
    assert box.initial_budget == 600
    assert box.budgets == [600, 900, 1800, 3600]


def test_timebox_off_tier_first_budget_keeps_intermediate_tier():
    """首档落在两个标准档之间时，后一档标准档仍会入选（既有阶梯语义）。

    首档 240 → 240 与 300 都 < 300 的标准档起点，故 300 也满足 ``t >= first``。
    这是既有行为，不是 env 覆盖引入的；锁住它以防将来误改。
    """
    assert tb.Timebox(initial_budget=240).budgets == [240, 300, 900, 1800, 3600]


def test_timebox_explicit_initial_budget_beats_env(monkeypatch):
    """CLI/显式构造 > env。"""
    monkeypatch.setenv(eo.ENV_DIFFICULTY_BUDGETS, "easy:240")
    assert tb.Timebox(initial_budget=999).budgets == [999, 1800, 3600]


def test_timebox_non_incremental_uses_single_tier(monkeypatch):
    monkeypatch.setenv(eo.ENV_TIER_THRESHOLDS, "120,600")
    assert tb.Timebox(initial_budget=120, incremental=False).budgets == [120]


# ── 接线：stopper ────────────────────────────────────────────────────────────


def test_stopper_regression_no_env_matches_constants():
    """零行为变更护栏。"""
    assert st.max_no_output_rounds_default() == 7
    assert st.max_variant_failures_default() == 7
    assert st.partial_flag_multiplier() == 2
    assert st.token_budgets() == st.DIFFICULTY_TOKEN_BUDGETS
    assert st.difficulty_token_budget("easy") == 200_000
    assert st.difficulty_token_budget("medium") == st.DEFAULT_MAX_TOKENS
    assert st.difficulty_token_budget("hard") == 1_000_000
    assert st.difficulty_token_budget("expert") == 1_500_000
    stopper = st.Stopper()
    assert stopper.max_no_output_rounds == 7
    assert stopper.max_variant_failures == 7
    assert stopper.max_tokens is None


def test_stopper_thresholds_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "3")
    monkeypatch.setenv(eo.ENV_MAX_VARIANT_FAILURES, "9")
    stopper = st.Stopper()
    assert stopper.max_no_output_rounds == 3
    assert stopper.max_variant_failures == 9


def test_stopper_explicit_beats_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "3")
    assert st.Stopper(max_no_output_rounds=11).max_no_output_rounds == 11


def test_stopper_env_zero_falls_back_to_default(monkeypatch):
    """显式 0 视为未指定（min_value=1）。"""
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "0")
    assert st.Stopper().max_no_output_rounds == 7


def test_stopper_max_tokens_none_still_means_unlimited(monkeypatch):
    """max_tokens 的 None 语义不能被 env 层污染。"""
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "3")
    assert st.Stopper().max_tokens is None


def test_stopper_partial_flag_multiplier_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_PARTIAL_FLAG_MULTIPLIER, "3")
    stopper = st.Stopper(max_tokens=1000)
    # 有 partial flag 时预算放大 3 倍 → 2999 放行、3000 触发
    assert stopper.check(2999, 0, 0, False, True) is None
    assert stopper.check(3000, 0, 0, False, True) == "BUDGET_EXCEEDED"


def test_stopper_token_budgets_env_partial_override(monkeypatch):
    monkeypatch.setenv(eo.ENV_TOKEN_BUDGETS, "easy:123456")
    assert st.token_budgets() == {
        "easy": 123456,
        "medium": st.DEFAULT_MAX_TOKENS,
        "hard": 1_000_000,
        "expert": 1_500_000,
    }


def test_stopper_unknown_difficulty_keeps_default_max_tokens(monkeypatch):
    """未知难度回退常量 DEFAULT_MAX_TOKENS（刻意不同于 timebox 的"回退生效 easy"）。"""
    monkeypatch.setenv(eo.ENV_TOKEN_BUDGETS, "easy:1")
    assert st.difficulty_token_budget("unknown") == st.DEFAULT_MAX_TOKENS


# ── 接线：loop_guard ─────────────────────────────────────────────────────────


def test_loop_guard_regression_no_env_matches_defaults():
    detector = lg.LoopDetector()
    assert (detector.window, detector.warn_threshold, detector.break_threshold) == (12, 3, 5)


def test_loop_guard_env_thresholds(monkeypatch):
    monkeypatch.setenv(eo.ENV_LOOP_WINDOW, "20")
    monkeypatch.setenv(eo.ENV_LOOP_WARN, "2")
    monkeypatch.setenv(eo.ENV_LOOP_BREAK, "4")
    detector = lg.LoopDetector()
    assert (detector.window, detector.warn_threshold, detector.break_threshold) == (20, 2, 4)
    assert detector._recent.maxlen == 20


def test_loop_guard_explicit_beats_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_LOOP_WINDOW, "20")
    assert lg.LoopDetector(window=7).window == 7


def test_loop_guard_env_zero_falls_back(monkeypatch):
    monkeypatch.setenv(eo.ENV_LOOP_WINDOW, "0")
    monkeypatch.setenv(eo.ENV_LOOP_BREAK, "0")
    detector = lg.LoopDetector()
    assert (detector.window, detector.break_threshold) == (12, 5)


def test_loop_guard_break_below_warn_falls_back_whole_pair(monkeypatch):
    """break < warn 会让 warn 永不触发 → warn/break 整组回退默认。"""
    monkeypatch.setenv(eo.ENV_LOOP_WARN, "5")
    monkeypatch.setenv(eo.ENV_LOOP_BREAK, "2")
    monkeypatch.setenv(eo.ENV_LOOP_WINDOW, "9")
    detector = lg.LoopDetector()
    assert (detector.warn_threshold, detector.break_threshold) == (3, 5)
    assert detector.window == 9  # window 独立解析，不受该回退影响


def test_loop_guard_env_break_equal_warn_is_kept(monkeypatch):
    """break == warn 合法（warn 级被跳过但 break 仍可达）。"""
    monkeypatch.setenv(eo.ENV_LOOP_WARN, "4")
    monkeypatch.setenv(eo.ENV_LOOP_BREAK, "4")
    detector = lg.LoopDetector()
    assert (detector.warn_threshold, detector.break_threshold) == (4, 4)


def test_loop_guard_env_thresholds_drive_behavior(monkeypatch):
    monkeypatch.setenv(eo.ENV_LOOP_WARN, "1")
    monkeypatch.setenv(eo.ENV_LOOP_BREAK, "2")
    detector = lg.LoopDetector(window=5)
    assert detector.check("terminal", {"cmd": "ls"}) == lg.WARN
    assert detector.check("terminal", {"cmd": "ls"}) == lg.BREAK


def test_loop_guard_default_detector_picks_up_env_after_reset(monkeypatch):
    """单例是每进程构造一次：改 env 后必须 reset 才生效。"""
    monkeypatch.setenv(eo.ENV_LOOP_WINDOW, "30")
    try:
        lg.reset_default_detector()
        assert lg.default_detector().window == 30
    finally:
        monkeypatch.delenv(eo.ENV_LOOP_WINDOW, raising=False)
        lg.reset_default_detector()


def test_loop_guard_kill_switch_still_opt_out(monkeypatch):
    """FULILIAN_LOOP_GUARD=0 的 opt-out 语义不受本次改动影响。"""
    monkeypatch.setenv(lg.ENV_LOOP_GUARD, "0")
    assert lg.LoopDetector().check("terminal", {"cmd": "ls"}) is None




# ── 接线：probe ──────────────────────────────────────────────────────────────


def test_probe_regression_no_env_matches_defaults():
    assert pr.probe_timeout_default() == 60
    assert pr.probe_scan_timeout_default() == 5.0
    assert pr.DEFAULT_PROBE_TIMEOUT == 60
    assert pr.DEFAULT_PROBE_SCAN_TIMEOUT == 5.0


def test_probe_timeout_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "12")
    assert pr.probe_timeout_default() == 12


def test_probe_timeout_env_zero_falls_back(monkeypatch):
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "0")
    assert pr.probe_timeout_default() == 60


def test_probe_scan_timeout_env_and_zero(monkeypatch):
    monkeypatch.setenv(eo.ENV_PROBE_SCAN_TIMEOUT, "0.25")
    assert pr.probe_scan_timeout_default() == 0.25
    monkeypatch.setenv(eo.ENV_PROBE_SCAN_TIMEOUT, "0")
    assert pr.probe_scan_timeout_default() == 5.0


def test_probe_challenge_no_host_short_circuits_without_network():
    assert pr.probe_challenge("", 0) == pr.ProbeResult.REACHABLE


def test_probe_challenge_timeout_env_reaches_socket_layer(monkeypatch):
    """env 超时必须真的落到 socket.settimeout（且被 min(...,10) 夹住）。"""
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "3")
    seen = []

    class _Sock:
        def settimeout(self, value):
            seen.append(value)

        def connect_ex(self, addr):
            return 0

        def close(self):
            pass

    monkeypatch.setattr(pr.socket, "socket", lambda *a, **k: _Sock())
    assert pr.probe_challenge("127.0.0.1", 80) == pr.ProbeResult.REACHABLE
    assert seen == [3]


def test_probe_challenge_socket_timeout_clamped_to_10(monkeypatch):
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "600")
    seen = []

    class _Sock:
        def settimeout(self, value):
            seen.append(value)

        def connect_ex(self, addr):
            return 0

        def close(self):
            pass

    monkeypatch.setattr(pr.socket, "socket", lambda *a, **k: _Sock())
    pr.probe_challenge("127.0.0.1", 80)
    assert seen == [10], "socket 层有效上限是 10s，登记表已注明"


def test_probe_challenge_explicit_timeout_beats_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "3")
    seen = []

    class _Sock:
        def settimeout(self, value):
            seen.append(value)

        def connect_ex(self, addr):
            return 0

        def close(self):
            pass

    monkeypatch.setattr(pr.socket, "socket", lambda *a, **k: _Sock())
    pr.probe_challenge("127.0.0.1", 80, timeout=7)
    assert seen == [7]


# ── 接线：dispatcher ─────────────────────────────────────────────────────────


def _dispatcher(**kwargs):
    return dp.Dispatcher(quiet=True, **kwargs)


def test_dispatcher_regression_no_env_matches_defaults():
    """零行为变更护栏：既有默认值一个不变。"""
    assert dp.max_workers_default() == 3
    assert dp.max_attempts_default() == 5
    assert dp.no_output_round_seconds_default() == 60
    assert dp.probe_concurrency() == 4
    assert dp.timebox_override_default() == 0
    assert dp.escalation_timebox_multiplier() == 1.5
    assert dp.PROBE_CONCURRENCY == 4
    dispatcher = _dispatcher()
    assert dispatcher.max_workers == 3
    assert dispatcher.probe_timeout == 60
    assert dispatcher.max_attempts == 5
    assert dispatcher.timebox_override == 0
    assert dispatcher.no_output_round_seconds == 60
    assert dispatcher.stopper.max_no_output_rounds == 7
    assert dispatcher.stopper.max_variant_failures == 7
    assert dispatcher.stopper.max_tokens is None


def test_dispatcher_env_applies(monkeypatch):
    monkeypatch.setenv(eo.ENV_WORKERS, "8")
    monkeypatch.setenv(eo.ENV_MAX_ATTEMPTS, "2")
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "15")
    monkeypatch.setenv(eo.ENV_NO_OUTPUT_ROUND_SECONDS, "30")
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "4")
    monkeypatch.setenv(eo.ENV_MAX_VARIANT_FAILURES, "11")
    dispatcher = _dispatcher()
    assert dispatcher.max_workers == 8
    assert dispatcher.max_attempts == 2
    assert dispatcher.probe_timeout == 15
    assert dispatcher.no_output_round_seconds == 30
    assert dispatcher.stopper.max_no_output_rounds == 4
    assert dispatcher.stopper.max_variant_failures == 11


def test_dispatcher_explicit_beats_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_WORKERS, "8")
    monkeypatch.setenv(eo.ENV_MAX_ATTEMPTS, "2")
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "4")
    dispatcher = _dispatcher(max_workers=1, max_attempts=9, max_no_output_rounds=13)
    assert dispatcher.max_workers == 1
    assert dispatcher.max_attempts == 9
    assert dispatcher.stopper.max_no_output_rounds == 13


def test_dispatcher_env_zero_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(eo.ENV_WORKERS, "0")
    monkeypatch.setenv(eo.ENV_MAX_ATTEMPTS, "0")
    dispatcher = _dispatcher()
    assert dispatcher.max_workers == 3
    assert dispatcher.max_attempts == 5


def test_dispatcher_timebox_override_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_TIMEBOX, "600")
    assert _dispatcher().timebox_override == 600


def test_dispatcher_timebox_override_zero_sentinel_not_swallowed(monkeypatch):
    """0 是 timebox_override 的合法哨兵（按难度自适应），env 与显式都不能吞它。"""
    monkeypatch.setenv(eo.ENV_TIMEBOX, "600")
    assert _dispatcher(timebox_override=0).timebox_override == 0
    monkeypatch.delenv(eo.ENV_TIMEBOX, raising=False)
    assert _dispatcher(timebox_override=0).timebox_override == 0
    monkeypatch.setenv(eo.ENV_TIMEBOX, "0")
    assert _dispatcher().timebox_override == 0


def test_dispatcher_timebox_override_explicit_beats_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_TIMEBOX, "600")
    assert _dispatcher(timebox_override=120).timebox_override == 120


def test_dispatcher_probe_concurrency_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_PROBE_CONCURRENCY, "9")
    assert dp.probe_concurrency() == 9
    monkeypatch.setenv(eo.ENV_PROBE_CONCURRENCY, "0")
    assert dp.probe_concurrency() == 4


def test_dispatcher_escalation_multiplier_env(monkeypatch):
    monkeypatch.setenv(eo.ENV_ESCALATION_TIMEBOX_MULTIPLIER, "2.5")
    assert dp.escalation_timebox_multiplier() == 2.5
    monkeypatch.setenv(eo.ENV_ESCALATION_TIMEBOX_MULTIPLIER, "0.5")
    assert dp.escalation_timebox_multiplier() == 1.5  # min_value=1.0 → 回退


# ── 接线：cli（solve-all 路径的 CLI > env > 默认）────────────────────────────


def _run_solve_all(monkeypatch, tmp_path, **cli_flags):
    """以最小平台目录驱动 handle_solve_all_command，返回传给 Dispatcher 的 kwargs。

    平台目录极简：``<tmp>/chal1/challenge.json`` 只需含 ``id``（其余字段有默认值）。
    """
    import argparse
    import json as _json

    challenge_dir = tmp_path / "chal1"
    challenge_dir.mkdir()
    (challenge_dir / "challenge.json").write_text(
        _json.dumps({"id": "c1", "title": "t"}), encoding="utf-8"
    )

    captured: dict = {}

    class _FakeDispatcher:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.max_workers = kwargs.get("max_workers")
            self.projects = []

        def add_project(self, project):
            self.projects.append(project)

        def run(self, limit=None):
            return {"projects": [], "totals": {"solved": 0}, "duration": 0, "spawns": 0}

        def save_state(self, summary, path):
            return None

        def stop_all(self):
            return None

    monkeypatch.setattr("fulilian_ctf.dispatcher.Dispatcher", _FakeDispatcher)
    args = argparse.Namespace(platform=str(tmp_path), limit=1, **cli_flags)
    with pytest.raises(SystemExit):
        cli.handle_solve_all_command(args)
    return captured


def test_cli_solve_all_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv(eo.ENV_WORKERS, "7")
    monkeypatch.setenv(eo.ENV_MAX_ATTEMPTS, "2")
    monkeypatch.setenv(eo.ENV_PROBE_TIMEOUT, "11")
    monkeypatch.setenv(eo.ENV_TIMEBOX, "300")
    monkeypatch.setenv(eo.ENV_MAX_NO_OUTPUT_ROUNDS, "4")
    monkeypatch.setenv(eo.ENV_MAX_VARIANT_FAILURES, "9")

    kwargs = _run_solve_all(monkeypatch, tmp_path)

    assert kwargs["max_workers"] == 7
    assert kwargs["max_attempts"] == 2
    assert kwargs["probe_timeout"] == 11
    assert kwargs["max_no_output_rounds"] == 4
    assert kwargs["max_variant_failures"] == 9
    # timebox_override 是刻意例外：cli 透传 None，解析发生在真实
    # Dispatcher.__init__（0 是合法哨兵，不能用 `or` 在这里吞掉）。
    # 两半分别验证：这里是透传，下面验证解析。
    assert kwargs["timebox_override"] is None
    assert dp.timebox_override_default() == 300


def test_cli_solve_all_flag_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv(eo.ENV_WORKERS, "7")
    monkeypatch.setenv(eo.ENV_MAX_ATTEMPTS, "2")
    monkeypatch.setenv(eo.ENV_TIMEBOX, "300")

    kwargs = _run_solve_all(
        monkeypatch, tmp_path, workers=1, max_attempts=9, timebox=45
    )

    assert kwargs["max_workers"] == 1
    assert kwargs["max_attempts"] == 9
    assert kwargs["timebox_override"] == 45


def test_cli_solve_all_explicit_timebox_zero_beats_env(monkeypatch, tmp_path):
    """显式 ``--timebox 0``（按难度自适应）不能被 env 的 300 顶掉。"""
    monkeypatch.setenv(eo.ENV_TIMEBOX, "300")
    kwargs = _run_solve_all(monkeypatch, tmp_path, timebox=0)
    assert kwargs["timebox_override"] == 0


def test_cli_solve_all_no_env_uses_defaults(monkeypatch, tmp_path):
    kwargs = _run_solve_all(monkeypatch, tmp_path)
    assert kwargs["max_workers"] == 3
    assert kwargs["max_attempts"] == 5
    assert kwargs["probe_timeout"] == 60
    assert kwargs["timebox_override"] is None  # 由 Dispatcher 解析 env → 默认 0
    assert kwargs["max_no_output_rounds"] == 7
    assert kwargs["max_variant_failures"] == 7
    assert kwargs["max_tokens"] is None
