"""对照模式（``ctf_path_baseline.py --compare``）的回归测试。

为什么需要它：2c 把噪声地板算出来了，但**没有任何代码去用它** —— 地板印在
报告里，判断"这次改动有没有效"仍然是肉眼看两个数字。更危险的是把两组批目录
塞进一次 ``--runs``：那样算出的地板会把两组之间的真实差异一起算进去，等于
拿被测量的东西当尺子，差异越大尺子越长，永远测不出显著。

所以这里锁两件事：
  ① 地板必须只从**各组内部**的摆动估，不许被组间差异污染；
  ② 任何"没法对照"的情形（单侧题目、参考步数变了、采样不足）都必须
     **说出来**，不许静默丢题 —— 丢题会让"没测到"读成"没效果"。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_collector():
    spec = importlib.util.spec_from_file_location(
        "ctf_path_baseline", REPO / "benchmarks" / "ctf_path_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector = _load_collector()


def _make_sample(batch: Path, fixture: str, api_calls: int) -> Path:
    d = batch / fixture
    d.mkdir(parents=True, exist_ok=True)
    (d / "usage.json").write_text(json.dumps({
        "api_calls": api_calls, "total_tokens": api_calls * 1000,
        "input_tokens": api_calls * 900, "output_tokens": api_calls * 100,
        "cost": 0.01, "attempts": 1,
    }), encoding="utf-8")
    lines = [f"🔄 Making API call #{i + 1}/{api_calls}" for i in range(api_calls)]
    (d / "solver.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "FLAG").write_text("flag{x}\n", encoding="utf-8")
    return d


def _archive(tmp_path, label: str, spec: dict[str, list[int]],
             ref_steps: int = 5) -> dict:
    """用真实生产者路径造一份 2-repeat 归档：{fixture: [api_calls, ...]}。

    spec 里的第 i 个数是该 fixture 第 i 个**跑批**的 api_calls —— 合并指标的
    噪声地板按跑批量算，所以批次的划分必须在样本里体现出来（``batch`` 键）。
    逐次采样与统计都走采集器自己的函数，不手搓字段名。
    """
    batch = tmp_path / label
    groups: dict[str, list[dict]] = {}
    for fixture, apis in spec.items():
        for i, api in enumerate(apis):
            d = _make_sample(batch / f"s{i}", fixture, api)
            row = collector.analyze(d, "flag{x}", ref_steps)
            row["batch"] = f"{label}-b{i}"
            groups.setdefault(fixture, []).append(row)
    return {"schema": "ctf-path-baseline/2-repeat",
            "stats": collector.repeat_stats(groups),
            "samples": groups}


def test_compare_floor_comes_from_within_side_spread_only(tmp_path):
    """⚠️ 核心回归锁：地板不许被组间差异污染。

    改动前 2.0–2.4×，改动后 6.0–6.2×。真实地板是两组内部跨度的较大者
    （0.4×），不是「合并后的总跨度」（4.2×）。若实现退化成把两组混在一起
    算范围，这个 3.9× 的巨大改动会被自己撑大的地板判成"分辨不了" ——
    正是这条错误会让真正的改进永远无法验收。
    """
    base = _archive(tmp_path, "base", {"alpha-01": [10, 12]})       # 2.0× / 2.4×
    changed = _archive(tmp_path, "changed", {"alpha-01": [30, 31]})  # 6.0× / 6.2×
    cmp = collector.compare_archives(base, changed)
    (row,) = cmp["rows"]
    assert row["floor"] == pytest.approx(0.4, abs=0.05)
    assert row["mult_delta"] == pytest.approx(3.9, abs=0.05)
    assert row["resolvable"] is True


def test_compare_calls_small_delta_unresolvable(tmp_path):
    """差异落在自身摆幅以内 → 明说分辨不了，不许当成"有效"。"""
    base = _archive(tmp_path, "base", {"alpha-01": [10, 20]})       # 2.0× / 4.0×
    changed = _archive(tmp_path, "changed", {"alpha-01": [16, 17]})  # 3.2× / 3.4×
    cmp = collector.compare_archives(base, changed)
    (row,) = cmp["rows"]
    assert row["floor"] == pytest.approx(2.0, abs=0.05)
    assert abs(row["mult_delta"]) == pytest.approx(0.3, abs=0.05)
    assert row["resolvable"] is False


def test_compare_excludes_fixture_whose_reference_steps_changed(tmp_path):
    """参考步数变了 = 题目变了，两侧跑的不是同一道题，差值无意义。"""
    base = _archive(tmp_path, "base", {"alpha-01": [10, 12]}, ref_steps=5)
    changed = _archive(tmp_path, "changed", {"alpha-01": [30, 31]}, ref_steps=7)
    cmp = collector.compare_archives(base, changed)
    assert cmp["rows"] == []
    assert cmp["steps_mismatch"] == [("alpha-01", 5, 7)]

    out = _capture(collector.print_comparison, cmp)
    assert "参考步数在两组间不一致" in out
    assert "没有任何一题是可对照的" in out


def test_compare_lists_one_sided_fixtures_instead_of_dropping_them(tmp_path):
    """只在单侧出现的题必须被点名 —— 静默丢题会让"没测到"读成"没效果"。"""
    base = _archive(tmp_path, "base", {"alpha-01": [10, 11], "gone-01": [9, 9]})
    changed = _archive(tmp_path, "changed", {"alpha-01": [20, 21],
                                             "new-01": [8, 8]})
    cmp = collector.compare_archives(base, changed)
    assert cmp["only_base"] == ["gone-01"]
    assert cmp["only_changed"] == ["new-01"]

    out = _capture(collector.print_comparison, cmp)
    assert "gone-01" in out and "无法对照" in out
    assert "new-01" in out


def test_compare_says_nothing_is_proven_when_samples_too_few(tmp_path):
    """全 n=1 → 不是"无效果"，是"这份对照什么都没证明"。"""
    base = _archive(tmp_path, "base", {"alpha-01": [10]})
    changed = _archive(tmp_path, "changed", {"alpha-01": [30]})
    cmp = collector.compare_archives(base, changed)
    (row,) = cmp["rows"]
    assert row["resolvable"] is None       # 不是 False —— 没测 ≠ 测到 0
    assert row["floor"] is None

    out = _capture(collector.print_comparison, cmp)
    assert "采样不足" in out
    assert "什么都没证明" in out
    assert "无效果" in out                  # 明确否掉这个读法


def test_pooled_floor_is_the_per_batch_swing(tmp_path):
    """合并指标的地板按**跑批量**：同一份代码逐批的合并值摆动。

    这里两题的摆动不同步（alpha 10→20→30，beta 10→30→20），逐批合并值
    是 2.0 / 5.0 / 5.0 → 地板 3.0×，而逐题地板是 4.0×。合并不是简单取小，
    是**各题噪声部分抵消** —— 这正是合并指标更灵敏的原因，也是必须按
    跑批量实测而不能靠公式推的原因。
    """
    spec = {"alpha-01": [10, 20, 30], "beta-01": [10, 30, 20]}
    cmp = collector.compare_archives(_archive(tmp_path, "base", spec),
                                     _archive(tmp_path, "changed", spec))
    p = cmp["pooled"]
    assert p["batches_base"] == {"base-b0": 2.0, "base-b1": 5.0, "base-b2": 5.0}
    assert p["floor"] == pytest.approx(3.0, abs=0.01)
    assert all(r["floor"] == pytest.approx(4.0, abs=0.05) for r in cmp["rows"])


def test_pooled_floor_needs_two_batches_per_side(tmp_path):
    """每侧只有 1 个跑批时，合并地板**不存在** —— 不许报 0 当"高度一致"。"""
    base = _archive(tmp_path, "base", {"alpha-01": [10]})
    changed = _archive(tmp_path, "changed", {"alpha-01": [10]})
    cmp = collector.compare_archives(base, changed)
    p = cmp["pooled"]
    assert p["floor"] is None
    assert p["resolvable"] is None
    out = _capture(collector.print_comparison, cmp)
    assert "每侧至少要 2 个跑批" in out


def test_incomplete_batch_is_reported_not_silently_dropped(tmp_path):
    """没跑齐对照题集的批不参与地板，但必须点名 —— 静默少一批 = 偷偷缩样本。"""
    spec = {"alpha-01": [10, 20, 30], "beta-01": [10, 30, 20]}
    base = _archive(tmp_path, "base", spec)
    changed = _archive(tmp_path, "changed", spec)
    del base["samples"]["beta-01"][2]        # 第 3 批里少了 beta-01
    cmp = collector.compare_archives(base, changed)
    # 两侧的批常同名，必须带侧别前缀，否则"哪侧少了批"读不出来
    assert cmp["incomplete_batches"] == ["改动前/base-b2"]
    out = _capture(collector.print_comparison, cmp)
    assert "没跑齐对照题集" in out


def test_compare_records_where_each_side_came_from(tmp_path):
    """⚠️ 回归锁：对照结论只在"两侧差异 = 你要测的那个改动"时成立。

    归档记不下代码差异（v1 没记过 commit）。实测踩过：一份 09-12 的对照与
    一份 09-11 的基线比出 +0.40×，中间夹着六个提交 —— 不手工 diff 就不知道
    这 0.40× 该记给谁。所以至少把跑批来源固定进档案，并在报告里把"另半个
    前提要你自己核对"说出来。
    """
    base = _archive(tmp_path, "base", {"alpha-01": [10, 12]})
    base["generated_at"] = "2026-09-11T15:28:42+00:00"
    base["batches"] = ["/tmp/ctf-n3/run1", "/tmp/ctf-n3/run2"]
    cmp = collector.compare_archives(base,
                                     _archive(tmp_path, "changed", {"alpha-01": [30, 31]}))
    assert cmp["sources"]["base"]["generated_at"] == "2026-09-11T15:28:42+00:00"
    assert cmp["sources"]["base"]["batches"] == ["/tmp/ctf-n3/run1", "/tmp/ctf-n3/run2"]

    out = _capture(collector.print_comparison, cmp)
    assert "采集来源" in out
    assert "/tmp/ctf-n3/run1" in out
    assert "代码差了什么" in out      # 那半个前提被明说，而不是留白


def test_compare_needs_both_archives_in_repeat_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError):
        collector.load_repeat_archive(bad)


def test_compare_mode_is_mutually_exclusive_with_dirs_and_runs(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for p in (a, b):
        p.write_text(json.dumps({"schema": "ctf-path-baseline/2-repeat",
                                 "stats": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        collector.main(["--compare", str(a), str(b), "--runs", str(tmp_path)])
    with pytest.raises(SystemExit):
        collector.main(["--compare", str(a), str(b), "--dirs", str(tmp_path)])
    with pytest.raises(SystemExit):
        collector.main(["--compare", str(a)])       # 必须正好两份


def test_compare_json_archive_round_trips(tmp_path, capsys):
    base = _archive(tmp_path, "base", {"alpha-01": [10, 12]})
    changed = _archive(tmp_path, "changed", {"alpha-01": [30, 31]})
    for name, payload in (("base.json", base), ("changed.json", changed)):
        (tmp_path / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    out_json = tmp_path / "out" / "cmp.json"
    rc = collector.run_compare_mode(tmp_path / "base.json",
                                    tmp_path / "changed.json", out_json)
    assert rc == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema"] == "ctf-path-baseline/2-compare"
    assert payload["comparison"]["rows"][0]["fixture"] == "alpha-01"


def _capture(fn, *a) -> str:
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*a)
    return buf.getvalue()
