"""P0-2 回归锁：止损轮询增量扫描（H-1）。

覆盖：语义等价 / 截断重置 / 跨块拼接 / 黑板 mtime 缓存 / 性能量级。
增量扫描的布尔结果必须与全量 scan_log_for_flag 完全一致（契约 1）。
"""

from __future__ import annotations

import os
import time

import pytest

from fulilian_ctf.blackboard import (
    BLACKBOARD_FILENAME,
    Blackboard,
    Fact,
    save_blackboard,
)
from fulilian_ctf.dispatcher import Dispatcher
from fulilian_ctf.solver import scan_log_for_flag

FLAG = "NSSCTF{abc-123}"


@pytest.fixture
def dispatcher():
    return Dispatcher(quiet=True)


@pytest.fixture
def slot():
    # _spawn 新建 slot 后增量字段经 .get() 兜底；空 dict 即可驱动被测方法
    return {}


def _append(log, text):
    with open(log, "a", encoding="utf-8") as f:
        f.write(text)


# ── 1. 语义等价：增量布尔结果与全量扫描一致 ──────────────────────────

def test_incremental_scan_matches_full_scan(dispatcher, tmp_path, slot):
    log = tmp_path / "solver.log"
    chunks = [
        "noise line 1\n",
        "recon: nmap output\n",
        f"found {FLAG} here\n",  # 第 3 段出现 flag
        "more noise\n",
        "tail\n",
    ]
    for i, chunk in enumerate(chunks):
        _append(log, chunk)
        got = dispatcher._incremental_flag_scan(slot, tmp_path)
        want = bool(scan_log_for_flag(tmp_path))
        assert got == want, f"chunk {i}: incremental={got} full={want}"
        if i == 2:
            assert got is True


# ── 2. 截断重写 → 重置 offset 从头扫 ────────────────────────────────

def test_truncated_log_resets_offset(dispatcher, tmp_path, slot):
    log = tmp_path / "solver.log"
    log.write_text(f"attempt 1 done, flag was {FLAG}\n", encoding="utf-8")
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is True
    # 新尝试：open("w") 截断重写，内容变短且暂无 flag
    log.write_text("new attempt, no flag yet\n", encoding="utf-8")
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is False
    _append(log, f"then {FLAG} appears\n")
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is True


# ── 3. 候选被读写边界劈开 → tail 拼接后仍可检出 ─────────────────────

def test_candidate_split_across_chunks(dispatcher, tmp_path, slot):
    log = tmp_path / "solver.log"
    _append(log, "scan output prefix ... NSSCTF{ab")
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is False
    _append(log, "c-123} suffix\n")
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is True


# ── 4. 黑板 mtime 缓存：未变复用对象，变了重载 ──────────────────────

def test_board_cache_reuses_until_mtime_changes(dispatcher, tmp_path):
    board_path = tmp_path / BLACKBOARD_FILENAME
    save_blackboard(Blackboard(challenge_id="c"), board_path)
    empty_slot: dict = {}

    b1 = dispatcher._cached_board(empty_slot, tmp_path)
    b2 = dispatcher._cached_board(empty_slot, tmp_path)
    assert b1 is not None
    assert b1 is b2  # mtime 未变 → 同一对象（不重读磁盘）

    board = Blackboard(challenge_id="c")
    board.add_fact(Fact(content="port 80 open", source="agent"))
    save_blackboard(board, board_path)
    # 强制 mtime 变化（防止 tmpfs mtime 粒度问题；size 亦作为 key 的一部分）
    st = board_path.stat()
    os.utime(board_path, ns=(st.st_mtime_ns + 1_000_000, st.st_mtime_ns + 1_000_000))

    b3 = dispatcher._cached_board(empty_slot, tmp_path)
    assert b3 is not b1
    assert len(list(b3.facts.values())) == 1


def test_board_cache_missing_file_returns_none(dispatcher, tmp_path):
    assert dispatcher._cached_board({}, tmp_path) is None


# ── 5. 性能量级：40MB 日志 + 4KB 增量，单轮 < 50ms ──────────────────

def test_incremental_scan_is_o_delta(dispatcher, tmp_path, slot):
    log = tmp_path / "solver.log"
    with open(log, "wb") as f:
        f.write(b"x" * (40 * 1024 * 1024))
    # 首轮为一次性全量（建立 offset 基线），不计入性能断言
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is False
    with open(log, "ab") as f:
        f.write(b"y" * 4096)
    t0 = time.perf_counter()
    assert dispatcher._incremental_flag_scan(slot, tmp_path) is False
    dt = time.perf_counter() - t0
    assert dt < 0.05, f"incremental scan took {dt*1000:.1f}ms (budget 50ms)"
