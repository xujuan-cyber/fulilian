"""原子写纪律的回归锁：FLAG 落盘 / relay_block.json / 降级读。

被测缺陷都是同一族：**普通 ``write_text`` 先 truncate 再写**，读者在这个窗口里
看到的是空文件（或半截内容）。FLAG 与 relay_block.json 都是跨进程沟通渠道 ——
写者在探索者子进程里，读者在父进程（收割 / 幻觉检测 / 中继 / CLI）里，窗口
真实存在。实测（4000 轮并发读写同一文件）：

    普通 write_text   读 16028 次：完整 3058 / **空 12970** / 残缺 0
    atomic_write_text 读 18931 次：完整 18931 / 空 0 / 残缺 0

「已解出」被读成「没解出」是要命的静默失败，所以这几处必须锁住。

第二条锁的是**降级**：``read_relay_block`` 的契约是「坏了就回落到 RELAY.md /
None」，但旧实现只捕获 JSONDecodeError/KeyError/ValueError —— 顶层是列表、
字符串、数字，或字段类型不对时，``from_dict`` 抛的是 AttributeError/TypeError，
异常会一路冒到 dispatcher 的轮次循环里。

预修复基线（``git checkout HEAD --`` 回退 verify/relay/solver/dispatcher/
multi_agent/racer 六个文件后跑本文件，再按 md5 恢复）：

    5 failed, 4 passed in 1.17s
    FAILED test_flag_write_is_never_observed_empty
    FAILED test_read_flag_file_ignores_directory
    FAILED test_write_relay_block_never_observed_empty
    FAILED test_read_relay_block_degrades_on_wrong_shape
    FAILED test_read_relay_block_ignores_directory
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fulilian_ctf.relay import (
    RELAY_BLOCK_FILENAME,
    RelayBlock,
    make_achieved_message,
    read_relay_block,
    write_relay_block,
)
from fulilian_ctf.solver import read_flag_file
from fulilian_ctf.verify import check_output_for_flag

FLAG = "flag{" + "a" * 40 + "}"


# ── 1. FLAG 落盘：读者永远看不到空文件 ────────────────────────────────────

def test_flag_write_is_never_observed_empty(tmp_path):
    """并发读者不得观察到 truncate 窗口（预修复时 ~80% 的读是空串）。"""
    target = tmp_path / "FLAG"
    target.write_text(FLAG + "\n", encoding="utf-8")
    output = f"tool output: {FLAG} more text"

    stop = threading.Event()
    empty_reads = [0]
    reads = [0]

    def reader():
        while not stop.is_set():
            text = target.read_text(encoding="utf-8", errors="replace")
            reads[0] += 1
            if text.strip() != FLAG:
                empty_reads[0] += 1

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        for _ in range(300):
            assert check_output_for_flag(output, str(target)) == FLAG
    finally:
        stop.set()
        th.join(timeout=5)

    assert reads[0] > 0, "读者一次都没跑起来，用例无效"
    assert empty_reads[0] == 0, (
        f"{empty_reads[0]}/{reads[0]} 次读到空/残缺 FLAG —— 写不是原子的"
    )
    assert target.read_text(encoding="utf-8").strip() == FLAG


def test_flag_write_leaves_no_tmp_residue(tmp_path):
    target = tmp_path / "FLAG"
    check_output_for_flag(f"out {FLAG}", str(target))
    # tmp_path 里还有 conftest 造的假 FULILIAN_HOME（fulilian_test），只看 .tmp
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == [], leftovers


def test_read_flag_file_ignores_directory(tmp_path):
    """同名目录不该让「读不到就当没有」变成 IsADirectoryError。"""
    (tmp_path / "FLAG").mkdir()
    assert read_flag_file(tmp_path) == ""


# ── 2. relay_block.json：原子写 + 形状不对就降级 ──────────────────────────

def _block() -> RelayBlock:
    return RelayBlock(
        session_id="s1",
        messages=[make_achieved_message("agent-a", "拿到 shell")],
        achieved_primitives=["shell"],
        dead_ends=["sqli"],
        next_steps=["提权"],
    )


def test_write_relay_block_roundtrip_is_atomic(tmp_path):
    write_relay_block(tmp_path, _block())
    again = read_relay_block(tmp_path)
    assert again is not None
    assert again.achieved_primitives == ["shell"]
    assert [m.content for m in again.messages] == ["拿到 shell"]
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == [], leftovers


def test_write_relay_block_never_observed_empty(tmp_path):
    """接力块被并发读时不得出现空文件（旧实现是普通 write_text）。"""
    write_relay_block(tmp_path, _block())
    target = tmp_path / RELAY_BLOCK_FILENAME
    stop = threading.Event()
    bad = [0]
    reads = [0]

    def reader():
        while not stop.is_set():
            text = target.read_text(encoding="utf-8", errors="replace")
            reads[0] += 1
            if '"achieved_primitives"' not in text:
                bad[0] += 1

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        for _ in range(200):
            write_relay_block(tmp_path, _block())
    finally:
        stop.set()
        th.join(timeout=5)

    assert reads[0] > 0
    assert bad[0] == 0, f"{bad[0]}/{reads[0]} 次读到空/残缺接力块"


def test_read_relay_block_degrades_on_wrong_shape(tmp_path):
    """结构合法的 JSON 但形状不对 → None，不得把解析细节漏给调用方。"""
    payloads = [
        "[]",                              # AttributeError: 'list' has no 'get'
        '"hello"',                         # AttributeError: 'str'
        "3",                               # AttributeError: 'int'
        '{"messages": "不是列表"}',          # 元素不是对象
        '{"achieved_primitives": 5}',      # TypeError: not iterable
        '{"round_number": "第一轮"}',        # int() 失败
    ]
    for payload in payloads:
        (tmp_path / RELAY_BLOCK_FILENAME).write_text(payload, encoding="utf-8")
        assert read_relay_block(tmp_path) is None, payload


def test_read_relay_block_ignores_directory(tmp_path):
    (tmp_path / RELAY_BLOCK_FILENAME).mkdir()
    assert read_relay_block(tmp_path) is None


def test_read_relay_block_still_parses_intact_json(tmp_path):
    """降级不能把正常路径一起吞了。"""
    (tmp_path / RELAY_BLOCK_FILENAME).write_text(
        json.dumps(_block().to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    got = read_relay_block(tmp_path)
    assert got is not None and got.dead_ends == ["sqli"]


# ── 3. 去重后的 relay.atomic_write_text 仍是原子语义 ──────────────────────

def test_relay_atomic_write_text_is_atomic(tmp_path):
    """relay 曾自持一份等价实现；统一到 fsutil 后语义必须不变。"""
    from fulilian_ctf.relay import atomic_write_text

    target = tmp_path / "payload.json"
    target.write_text('{"complete": true}', encoding="utf-8")
    stop = threading.Event()
    bad = [0]
    reads = [0]

    def reader():
        while not stop.is_set():
            text = target.read_text(encoding="utf-8", errors="replace")
            reads[0] += 1
            if text != '{"complete": true}':
                bad[0] += 1

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        for _ in range(500):
            atomic_write_text(target, '{"complete": true}')
    finally:
        stop.set()
        th.join(timeout=5)

    assert reads[0] > 0
    assert bad[0] == 0, f"{bad[0]}/{reads[0]} 次读到空/残缺内容"
