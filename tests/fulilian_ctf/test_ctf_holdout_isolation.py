"""难题 holdout 跑批器的**答案泄漏围堵**回归测试（2026-09-13）。

## 为什么加这一组

n=3 对照跑（`/tmp/ctf-n3` 与 `/tmp/ctf-ctl`，共 24 次）里翻出 agent 的原话：

    /tmp/ctf-n3/run1/reverse-obfchain-01:
        "The reference log shows a flag"
        "The reference logs match the FLAG files for the other tasks (ground truth)"
        "The _selfproof directory has the official solve_reference.py. Let me read it"

    /tmp/ctf-ctl/run2/misc-bigscan-01:
        "There's a run1 with the same challenge and a _mirror/_selfproof.
         Let me check those to understand th..."

三例（含未列为"疑似"的一次）的 flag **都是真解出来的**，泄漏被用作**事后
确认** —— 但确认本身烧掉 10–15 次调用，且**卡住的题烧得更多**。浪费量与
「这题难不难」正相关，正好污染 `ref_multiple` 这个被测量。

所以这不是"顺手打扫"，是**测量有效性的前置条件**：基准自己会漏答案时，
后面所有关于难度的结论都不成立。

## 这组测试锁的是什么

1. `_gate` 的**功能行为**（跑真的 shell 函数，不是 grep 源码字符串）——
   三条真实泄漏路径逐条复现，都必须被判 LEAK；
2. `$OUT` 的**布局白名单**：非题目录的直属条目一律拒绝 —— 初版按名字匹配
   泄漏物，漏掉了 `$OUT/logs/<id>.reference.log`（明文 flag 在**第二层**，
   `-maxdepth 1` 看不见）。这条测试就是为那个漏洞写的。
3. 驱动器**跨批不留明文**：跑完一批立刻打包并删目录。

## 反面证据（新锁要先证伪一次）

`_gate` 与 `--gate` 自检模式在旧版 `ctf_hard_run.sh` 上**不存在**，
所以这组测试在旧版上必然报错 —— 也就是说它测的是真实行为差异，
不是"无论代码怎么改都绿"的装饰。验证命令：

    git show <本次提交>^:benchmarks/ctf_hard_run.sh > /tmp/old.sh
    bash /tmp/old.sh --gate <dir>          # → 旧版会把 --gate 当 OUT 用，行为完全不同
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "benchmarks" / "ctf_hard_run.sh"
DRIVER = REPO / "benchmarks" / "ctf_hard_n3.sh"

FIXTURE = "misc-bigscan-01"


def _gate(work_dir: Path, stop: Path) -> str:
    """跑 `ctf_hard_run.sh --gate <dir> <stop>`，返回判定。

    取**最后一行**：泄漏时函数会先把命中路径打印出来再报 LEAK，
    只取首行会拿到路径而不是判定（第一版测试就栽在这上面）。
    """
    out = subprocess.run(
        ["bash", str(RUNNER), "--gate", str(work_dir), str(stop)],
        capture_output=True, text=True, timeout=60,
    )
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("GATE-")]
    assert lines, f"没有判定行；stdout={out.stdout!r} stderr={out.stderr!r}"
    return lines[-1]


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """一个 `$OUT` 骨架，含一个空的 work_dir。"""
    out = tmp_path / "out"
    (out / FIXTURE).mkdir(parents=True)
    return out


def test_clean_tree_passes(tree: Path) -> None:
    """干净的 $OUT（只有题目录）必须放行 —— 否则跑批器没法用。"""
    assert _gate(tree / FIXTURE, tree) == "GATE-CLEAN"


@pytest.mark.parametrize(
    "make_entry, label",
    [
        (lambda o: (o / "_selfproof" / FIXTURE).mkdir(parents=True)
                   or (o / "_selfproof" / FIXTURE / "solve_reference.py").touch(),
         "$OUT/_selfproof/<id>/solve_reference.py —— 实测被 agent 读走的那份"),
        (lambda o: (o / "logs").mkdir()
                   or (o / "logs" / f"{FIXTURE}.reference.log")
                      .write_text("flag{leaked}", encoding="utf-8"),
         "$OUT/logs/<id>.reference.log —— 参考解 stdout，**明文 flag**，在第二层"),
        (lambda o: (o / "_mirror").mkdir()
                   or (o / "_mirror" / f"{FIXTURE}.solver.log").touch(),
         "$OUT/_mirror/ —— 与上面两条同级"),
        (lambda o: (o / "out").mkdir()
                   or (o / "out" / "chan0.bin").touch(),
         "$OUT/out/ —— agent 自己写在 work_dir 上一级的中间产物"),
    ],
)
def test_out_side_entries_are_rejected(tree: Path, make_entry, label: str) -> None:
    """`$OUT` 的直属条目只许是题目录，别的都拒。

    这四条覆盖实测发生过的三种泄漏物 + 一次真实污染（chan*.bin 被当成第 5 题）。
    """
    make_entry(tree)
    assert _gate(tree / FIXTURE, tree) == "GATE-LEAK", label


def test_flag_inside_work_dir_rejected(tree: Path) -> None:
    """work_dir 内部有 FLAG 也要拒 —— 老版**只**查了这一层。"""
    (tree / FIXTURE / "FLAG").write_text("flag{x}", encoding="utf-8")
    assert _gate(tree / FIXTURE, tree) == "GATE-LEAK"


def test_sibling_run_root_rejected(tmp_path: Path) -> None:
    """兄弟跑批根里带 FLAG 时要拒。

    复现的正是 n3 驱动器那次：`/tmp/ctf-n3/run1` 与 `run2` 是兄弟，
    跑 run2 时 agent 可以直接读 run1 已经解出的 `FLAG`。
    """
    sib = tmp_path / "sibling"
    (sib / "run1" / FIXTURE).mkdir(parents=True)
    (sib / "run1" / FIXTURE / "FLAG").write_text("flag{old}", encoding="utf-8")
    (sib / "run2" / FIXTURE).mkdir(parents=True)
    assert _gate(sib / "run2" / FIXTURE, sib / "run2") == "GATE-LEAK"


def test_isolation_assertion_rejects_nested_roots(tmp_path: Path) -> None:
    """RUN_ROOT 与 OUT 互为祖先/后代时必须拒绝开跑。

    只把产物挪出去不够 —— 若 RUN_ROOT 仍落在 OUT 内部，agent 从 work_dir
    往上走照样回到泄漏物旁边。这条断言是"挪出去"与"挪到够远"的分界。
    """
    out = tmp_path / "out"
    out.mkdir()
    # 两个方向都要拒：RUN_ROOT 包住 OUT，以及 OUT 包住 RUN_ROOT。
    for work_dir, run_root in ((out, out / "runroot"), (out / "x", out)):
        r = subprocess.run(
            ["bash", str(RUNNER), str(work_dir), str(run_root)],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 1, f"应当拒绝：work_dir={work_dir} run_root={run_root}"
        assert "泄漏没堵住" in r.stdout


def test_driver_removes_plaintext_between_batches() -> None:
    """驱动器必须在批与批之间把明文目录清掉。

    只断言"有 tar 有 rm"是弱锁，但这条锁的是**顺序**：`tar` 在 `rm` 之前、
    且都在下一轮循环开始之前。顺序错了（先删后打包）会静默丢数据，
    顺序对了才叫"下一批跑起来时盘上没有明文 FLAG"。
    """
    src = DRIVER.read_text(encoding="utf-8")
    loop = src.split("for i in $(seq 1 \"$N\")")[1]
    tar_at = loop.index("tar -czf")
    rm_at = loop.index("rm -rf")
    assert tar_at < rm_at, "打包必须在删除之前，否则归档是空的"
    # 两个明文目录都要清：跑批目录（含各题 FLAG）与 RUN_ROOT（含 logs/mirror/proof）
    assert '"$OUT_PARENT/batch$i"' in loop.split("rm -rf")[1]
    assert '"$RUN_PARENT/batch$i"' in loop.split("rm -rf")[1]
    # 每批各用独立的 mktemp 父目录 —— 这是"不互为兄弟"的实现手段
    assert "OUT_PARENT=\"$(mktemp -d" in src
    assert "RUN_PARENT=\"$(mktemp -d" in src


def test_runner_keeps_artifacts_out_of_out() -> None:
    """runner 源码层：logs/mirror/proof 一律不得落在 `$OUT` 下。

    功能测试（上面的 `_gate`）已经能从行为上证明闸门会拦，这条是**预防**
    而非**检测** —— 它防的是"以后有人图省事又写回 `$OUT/logs`"。
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert 'LOGS="$RUN_ROOT/logs"' in src
    assert 'MIRROR="$RUN_ROOT/mirror"' in src
    assert 'PROOF="$RUN_ROOT/proof"' in src
    assert 'LOGS="$OUT' not in src
    assert 'MIRROR="$OUT' not in src
    assert 'PROOF="$OUT' not in src
