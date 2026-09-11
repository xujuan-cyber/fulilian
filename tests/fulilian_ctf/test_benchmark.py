"""P1-4 benchmark runner 回归测试（mini-corpus / 基线 / 故障注入）。

只覆盖快路径（少量 fixture + 2 个故障场景），全量 25 题与 4 故障
由 `python3 -m fulilian_ctf.benchmark` 一条命令跑，见 benchmarks/README.md。
全程离线：mock solver_impl + 真实 verify 三重校验门，不调 API。

预修复基线（``git checkout HEAD -- fulilian_ctf/benchmark.py`` 后跑本文件
的 `-k "isolat or reference_solve"`，再按 md5 恢复）::

    3 failed, 11 deselected
    FAILED test_unit_suite_isolates_crashing_case
    FAILED test_reference_solve_times_out_instead_of_hanging
    FAILED test_reference_solve_reports_reference_exception

对应用例循环无逐题隔离（一个用例炸掉整轮丢结果）与参考解进程内直调
（卡在网络上的参考解让自证与整个用例循环永久挂住）。
"""

from __future__ import annotations

import json
import time

import pytest

from fulilian_ctf.benchmark import (
    BENCH_DIR,
    DEFAULT_MANIFEST,
    FAULT_SCENARIOS,
    compare_with_baseline,
    load_manifest,
    run_fault_scenario,
    run_unit_suite,
    save_baseline,
    validate_fixture,
)

REAL_FIXTURES = ["web-info-leak-01", "reverse-rot13-01", "crypto-caesar-01"]


def test_manifest_loads_and_covers_five_categories():
    entries = load_manifest(DEFAULT_MANIFEST)
    assert len(entries) == 25
    cats = {e["category"] for e in entries}
    assert cats == {"web", "crypto", "pwn", "reverse", "misc"}
    for cat in cats:
        assert sum(1 for e in entries if e["category"] == cat) == 5
    # P0-1 回归锁：多平台 flag 前缀必须被 corpus 覆盖
    prefixes = {e["expected_flag"].split("{", 1)[0] for e in entries}
    assert {"NSSCTF", "CTFshow", "DASCTF", "flag"} <= prefixes


@pytest.mark.parametrize("fid", REAL_FIXTURES)
def test_fixture_self_validates(fid):
    entry = next(e for e in load_manifest(DEFAULT_MANIFEST) if e["id"] == fid)
    ok, err = validate_fixture(entry)
    assert ok, f"fixture {fid} 参考解未通过真实 flag 门: {err}"


def test_unit_suite_small_manifest(tmp_path):
    """临时小 manifest：跑完整 solver_worker → flag 门 → FLAG 文件链路。"""
    manifest = [
        {
            "id": "web-info-leak-01",
            "category": "web",
            "fixture": "fixtures/web-info-leak-01/",
            "expected_flag": "NSSCTF{unit_web_bak_leak}",
            "expect": "solved",
        },
        {
            "id": "reverse-rot13-01",
            "category": "reverse",
            "fixture": "fixtures/reverse-rot13-01/",
            "expected_flag": "flag{rot13_reverse_me}",
            "expect": "solved",
        },
        # 故意指向不存在目录 → 必须如实标 fixture-invalid，不许造假通过
        {
            "id": "broken-fixture-01",
            "category": "misc",
            "fixture": "fixtures/__no_such_fixture__/",
            "expected_flag": "flag{never}",
            "expect": "solved",
        },
    ]
    mpath = tmp_path / "manifest-mini.yaml"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    summary = run_unit_suite(mpath)

    by_id = {c["id"]: c for c in summary["cases"]}
    assert by_id["web-info-leak-01"]["status"] == "solved"
    assert by_id["reverse-rot13-01"]["status"] == "solved"
    assert by_id["broken-fixture-01"]["status"] == "skipped: fixture-invalid"
    # mock 层 token 恒为 None
    assert all(c["tokens"] is None for c in summary["cases"])
    # 工具调用数有记录（参考解步数 + 1 次提交扫描）
    assert by_id["web-info-leak-01"]["tool_calls"] >= 2
    # 汇总：2 solved / 3 total（invalid 计入分母）
    assert summary["totals"]["solved"] == 2
    assert summary["totals"]["total"] == 3
    assert summary["categories"]["misc"]["skipped_fixture_invalid"] == 1


def test_smoke_suite_refuses(capsys):
    from fulilian_ctf import benchmark

    assert benchmark.main(["--suite", "smoke"]) == 2
    err = capsys.readouterr().err
    assert "默认拒绝" in err and "FULILIAN_BENCHMARK_SMOKE_CONFIRM" in err


def test_fault_empty_model_degrades():
    report = run_fault_scenario("empty-model")
    assert report["passed"], report["checks"]
    # 降级语义：challenge A 失败但不崩，错误被装回结果；后续题继续跑
    assert report["checks"]["challengeA_result"]["ok"] is False
    assert "empty model" in report["checks"]["challengeA_result"]["error"]
    assert report["checks"]["challengeB_continued"] is True
    assert report["checks"]["warnings_emitted"]


def test_fault_corrupt_blackboard_degrades():
    report = run_fault_scenario("corrupt-blackboard")
    assert report["passed"], report["checks"]
    # 黑板损坏只降级止损精度：解题照常完成，告警可见
    assert report["checks"]["challengeA_result"]["ok"] is True
    assert report["checks"]["challengeA_result"]["flag"] == "NSSCTF{unit_web_bak_leak}"
    assert report["checks"]["challengeB_continued"] is True
    assert report["checks"]["warnings_emitted"]


def test_all_fault_scenarios_registered():
    assert set(FAULT_SCENARIOS) == {
        "empty-model", "corrupt-blackboard", "missing-fts5", "remote-down"}


def test_baseline_save_and_compare(tmp_path):
    entries = load_manifest(DEFAULT_MANIFEST)
    mini = [e for e in entries if e["id"] in REAL_FIXTURES]
    mpath = tmp_path / "manifest.yaml"
    mpath.write_text(json.dumps(mini), encoding="utf-8")

    summary = run_unit_suite(mpath)
    out = save_baseline(summary, tmp_path / "baselines" / "test-unit.json")
    assert out.is_file() and json.loads(out.read_text(encoding="utf-8"))["suite"] == "unit"

    # 与自身对比：无退化
    assert compare_with_baseline(summary, out) == []

    # 构造退化 summary：通过率下降必须被检出
    degraded = json.loads(json.dumps(summary))
    degraded["categories"]["web"]["pass_rate"] = 0.0
    regressions = compare_with_baseline(degraded, out)
    assert any("pass_rate" in r for r in regressions)


# ── 逐用例隔离 + 参考解超时（回归：一个用例炸掉整轮 / 参考解卡死）──────────

def test_unit_suite_isolates_crashing_case(tmp_path, monkeypatch):
    """单个用例抛异常时：如实记 crashed 并继续跑后面的用例。

    旧实现在循环体里没有任何隔离，一个用例炸掉（fixture 拷贝失败、队列空、
    未知异常）整轮基准连同已经跑完的结果一起丢，连"失败"都报不出来。
    """
    from fulilian_ctf import benchmark
    from fulilian_ctf.solver import SolverResult

    manifest = [
        {"id": "crash-01", "category": "web",
         "fixture": "fixtures/web-info-leak-01/", "expected_flag": "flag{x}",
         "expect": "solved"},
        {"id": "ok-01", "category": "web",
         "fixture": "fixtures/web-info-leak-01/", "expected_flag": "flag{a}",
         "expect": "solved"},
        {"id": "ok-02", "category": "reverse",
         "fixture": "fixtures/reverse-rot13-01/", "expected_flag": "flag{b}",
         "expect": "solved"},
    ]
    mpath = tmp_path / "manifest-crash.yaml"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    ran: list[str] = []

    def fake_run(entry, fixture_dir, work_dir, **kw):
        ran.append(entry["id"])
        if entry["id"] == "crash-01":
            raise RuntimeError("boom: fixture exploded")
        return SolverResult(ok=True, exit_code=0, flag=entry["expected_flag"]), 0.01

    monkeypatch.setattr(benchmark, "validate_fixture", lambda e: (True, ""))
    monkeypatch.setattr(benchmark, "_run_mock_challenge", fake_run)

    summary = run_unit_suite(mpath)
    by_id = {c["id"]: c for c in summary["cases"]}

    assert by_id["crash-01"]["status"] == "crashed"
    assert "boom: fixture exploded" in by_id["crash-01"]["detail"]
    assert by_id["crash-01"]["solved"] is False
    # 崩溃之后的用例照常跑（这就是隔离要保的东西）
    assert ran == ["crash-01", "ok-01", "ok-02"]
    assert by_id["ok-01"]["status"] == "solved"
    assert by_id["ok-02"]["status"] == "solved"
    # crashed 计入分母，不因为是异常就消失
    assert summary["totals"]["total"] == 3
    assert summary["totals"]["solved"] == 2


def test_reference_solve_times_out_instead_of_hanging(tmp_path):
    """参考解卡住时必须被超时杀掉并如实报错，而不是把调用方永久挂住。"""
    from fulilian_ctf.benchmark import _reference_solve

    fixture = tmp_path / "fixtures" / "hang-01"
    fixture.mkdir(parents=True)
    (fixture / "solve_reference.py").write_text(
        "import time\n"
        "SOLUTION_STEPS = 1\n"
        "def solve(work_dir):\n"
        "    time.sleep(60)\n"
        "    return 'flag{never}'\n",
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()

    started = time.monotonic()
    output, err = _reference_solve(fixture, work, timeout=2.0)
    elapsed = time.monotonic() - started

    assert output == ""
    assert "timed out" in err
    assert elapsed < 30, f"超时没生效，等了 {elapsed:.1f}s"


def test_reference_solve_reports_reference_exception(tmp_path):
    """参考解自己抛异常 → 以错误串返回，不向调用方抛（否则又是一处炸点）。"""
    from fulilian_ctf.benchmark import _reference_solve

    fixture = tmp_path / "fixtures" / "boom-01"
    fixture.mkdir(parents=True)
    (fixture / "solve_reference.py").write_text(
        "SOLUTION_STEPS = 1\n"
        "def solve(work_dir):\n"
        "    raise ValueError('reference is broken')\n",
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()

    output, err = _reference_solve(fixture, work, timeout=30.0)
    assert output == ""
    assert "ValueError" in err and "reference is broken" in err


def test_benchmarks_dir_layout():
    assert (BENCH_DIR / "manifest-unit.yaml").is_file()
    assert (BENCH_DIR / "manifest-smoke.yaml").is_file()
    assert (BENCH_DIR / "retrieval-golden.yaml").is_file()
    assert (BENCH_DIR / "sampling" / "build_retrieval_golden.py").is_file()
