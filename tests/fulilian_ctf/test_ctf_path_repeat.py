"""重复采样聚合（``ctf_path_baseline.py --runs``）的回归测试。

为什么单独测这块：2c 的全部价值在于**噪声地板** —— 同一份代码连跑几次的
×参考解 跨度。没有它，单跑差异（v1 3.7× / v2 2.9×）无法与采样噪声区分，
任何改动都能被说成"有效"。第一版实现里，只要有一题只采了 1 次，整块地板
就被静默跳过 —— 等于用"有一题没重复跑"取消了全部结论。这里锁住它。

采集器不是包内模块（在 ``benchmarks/`` 下），按文件路径导入。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_collector():
    spec = importlib.util.spec_from_file_location(
        "ctf_path_baseline", REPO / "benchmarks" / "ctf_path_baseline.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector = _load_collector()


REF_STEPS = 5


def _make_sample(batch: Path, fixture: str, api_calls: int,
                 flag: str = "flag{x}") -> Path:
    """造一个最小的 work_dir：usage.json + solver.log + FLAG。"""
    d = batch / fixture
    d.mkdir(parents=True, exist_ok=True)
    (d / "usage.json").write_text(json.dumps({
        "api_calls": api_calls, "total_tokens": api_calls * 1000,
        "input_tokens": api_calls * 900, "output_tokens": api_calls * 100,
        "cost": 0.01, "attempts": 1,
    }), encoding="utf-8")
    # 日志必须含 api_calls 条 Making API call 行，否则会被判成 overwritten
    lines = [f"🔄 Making API call #{i + 1}/{api_calls}" for i in range(api_calls)]
    lines.append("  📞 Tool 1: terminal(['command']) - {\"command\": \"ls\"}")
    (d / "solver.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "FLAG").write_text(flag + "\n", encoding="utf-8")
    return d


def _batches(tmp_path, spec: dict[str, dict[str, int]]
             ) -> tuple[list[Path], dict]:
    """spec: {batch_name: {fixture: api_calls}}。返回 (批目录, manifest meta)。

    ref_steps 走 manifest（``analyze`` 不读目录），所以这里一并造出，
    否则 ×参考解 恒为 None，整块地板判据无从触发。
    """
    out, meta = [], {}
    for bname, fixtures in spec.items():
        b = tmp_path / bname
        for fx, api in fixtures.items():
            _make_sample(b, fx, api)
            meta[fx] = {"steps": REF_STEPS, "expected_flag": "flag{x}"}
        out.append(b)
    return out, meta


def test_discover_batch_skips_runner_bookkeeping(tmp_path):
    b = tmp_path / "run1"
    for name in ("alpha-01", "beta-01"):
        _make_sample(b, name, 5)
    for junk in ("logs", "_selfproof", "_mirror", ".git"):
        (b / junk).mkdir()
    assert [d.name for d in collector.discover_batch(b)] == ["alpha-01", "beta-01"]


def test_repeat_stats_reports_range_not_just_mean(tmp_path):
    batches, meta = _batches(tmp_path, {
        "run1": {"alpha-01": 10},
        "run2": {"alpha-01": 30},
    })
    stats = collector.repeat_stats({"alpha-01": [
        collector.analyze(d, meta["alpha-01"]["expected_flag"], REF_STEPS)
        for b in batches for d in collector.discover_batch(b)
    ]})
    (s,) = stats
    assert s["n"] == 2
    assert s["api_mean"] == 20.0
    # 范围才是重点：均值 20 掩盖了 10 与 30 的三倍差
    assert (s["api_min"], s["api_max"]) == (10, 30)
    assert (s["mult_min"], s["mult_max"]) == (2.0, 6.0)


def test_noise_floor_survives_a_fixture_with_a_single_sample(tmp_path, capsys):
    """⚠️ 回归锁：一题没重复跑，不许取消其他题的噪声地板。

    第一版实现取全体的 n 最小值判「是否够算方差」，只要有一题 n=1 就
    直接 return —— 而实际跑批里新题（如 misc-chunkconcat-01）常常只在前
    一批出现过。这会让 2c 在最该出数的时候什么都不报。
    """
    batches, meta = _batches(tmp_path, {
        "run1": {"alpha-01": 10, "solo-01": 7},
        "run2": {"alpha-01": 30, "beta-01": 12},
        "run3": {"alpha-01": 20, "beta-01": 12},
    })
    rc = collector.run_repeat_mode(batches, meta, None)
    out = capsys.readouterr().out
    assert rc == 0
    # 地板 = alpha-01 的 6.0× − 2.0× = 4.0×
    assert "噪声地板" in out
    assert "4.00×" in out
    # solo-01 被明确排除，并说明理由，而不是悄悄消失
    assert "solo-01" in out and "不参与噪声地板" in out


def test_repeat_mode_warns_when_nothing_is_repeated(tmp_path, capsys):
    """全是单次采样时，必须说「算不出方差」，不能报 0 当结论。"""
    batches, meta = _batches(tmp_path, {
        "run1": {"alpha-01": 10, "beta-01": 12},
        "run2": {"gamma-01": 14},
    })
    collector.run_repeat_mode(batches, meta, None)
    out = capsys.readouterr().out
    assert "算不出方差" in out
    # 判据行本身不许出现（"噪声地板"四个字会出现在解释性文字里，故按判据断言）
    assert "验收判据" not in out


def test_repeat_mode_counts_untrusted_logs_and_keeps_solving_stats(tmp_path, capsys):
    """日志不可信只剔除工具面数字；解出率与 api_calls 不受影响。"""
    batches, meta = _batches(tmp_path, {"run1": {"alpha-01": 9},
                                        "run2": {"alpha-01": 9}})
    # 覆盖掉 run1 的日志：agent 用 write_file 写解题报告的真实形态
    (batches[0] / "alpha-01" / "solver.log").write_text(
        "# Solution\n\n## Flag\n", encoding="utf-8")

    collector.run_repeat_mode(batches, meta, None)
    out = capsys.readouterr().out
    assert "1 次采样的日志不可信" in out
    assert "2/2" in out          # 两次都解出，且 flag 都对
    assert "9" in out            # api_calls 仍来自 usage.json


def test_repeat_mode_writes_json_archive(tmp_path):
    batches, meta = _batches(tmp_path, {"run1": {"alpha-01": 10},
                                        "run2": {"alpha-01": 11}})
    out_json = tmp_path / "archive" / "n2.json"
    collector.run_repeat_mode(batches, meta, out_json)

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema"] == "ctf-path-baseline/2-repeat"
    assert payload["fixture_count"] == 1
    assert payload["stats"][0]["n"] == 2
    # 逐次采样也要留档：均值会把"哪一批异常"抹平
    assert len(payload["samples"]["alpha-01"]) == 2
    assert {s["batch"] for s in payload["samples"]["alpha-01"]} == {"run1", "run2"}


def test_stray_agent_output_dirs_are_excluded_from_the_batch(tmp_path, capsys):
    """⚠️ 回归锁：agent 写进跑批目录的目录不是题目。

    实测：misc-chunkconcat-01 那题，agent 把分通道的中间产物写到了 work_dir
    的**上一级** ``$OUT/out/chan*.bin``，采集器按目录名把它当成第 5 道
    fixture —— 虚增题数、还把"解出率"从 12/12 拉成 12/13。有 manifest 就按
    manifest 认题。
    """
    batches, meta = _batches(tmp_path, {
        "run1": {"alpha-01": 10},
        "run2": {"alpha-01": 30},
    })
    # agent 的中间产物目录：不在 manifest 里
    junk = batches[0] / "out"
    junk.mkdir()
    (junk / "chan01.bin").write_bytes(b"\x00\x01")
    (batches[0] / "decode.py").write_text("print(1)", encoding="utf-8")

    collector.run_repeat_mode(batches, meta, None)
    out = capsys.readouterr().out
    assert "不在 manifest 里，已排除" in out
    assert "`out/`" in out
    assert "agent 写在 work_dir 上一级的中间产物" in out
    # 被排除 ≠ 这题没跑 —— 必须说清楚，否则会被读成缺失
    assert "别把它读成「这题没跑」" in out
    # 统计里只有 alpha-01
    assert "1 题 × 2 次" in out


def test_without_manifest_it_warns_that_junk_cannot_be_told_apart(tmp_path, capsys):
    """没 manifest 时不静默 —— 明说它分不出题目与杂物。"""
    batches, _ = _batches(tmp_path, {"run1": {"alpha-01": 10},
                                     "run2": {"alpha-01": 30}})
    collector.run_repeat_mode(batches, {}, None)
    assert "无法把「题目」与「agent 写进来的杂物」区分开" in capsys.readouterr().out


def test_excluded_dirs_are_archived(tmp_path):
    """排除项要落档 —— 它们是"跑批目录被污染"的证据，得能看趋势。"""
    batches, meta = _batches(tmp_path, {"run1": {"alpha-01": 10},
                                        "run2": {"alpha-01": 30}})
    (batches[0] / "out").mkdir()
    out_json = tmp_path / "a.json"
    collector.run_repeat_mode(batches, meta, out_json)
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["excluded_non_fixture"] == {"out": ["run1"]}


def test_dirs_and_runs_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        collector.main(["--dirs", "/tmp/x", "--runs", "/tmp/y"])
    with pytest.raises(SystemExit):
        collector.main([])
