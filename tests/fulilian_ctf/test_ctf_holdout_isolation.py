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

## 第三轮（产品家目录）：为什么用**变异体**证伪，而不是拿旧提交跑

第三轮那几条锁（`_seed_home` / `FULILIAN_HOME` / `_home_fp`）在旧提交上
**不能**那样验：本组的功能测试会真的去调 `ctf_hard_run.sh --seed-home <目录>`，
而旧版不认这个选项 —— 它会把 `--seed-home` 当成 `$OUT`，**直接开跑一整批
四道题**（要 API、要几分钟，还会往真身家目录写东西）。

所以改用变异体：把当前 runner 逐处改坏，每条锁都必须**红在它该红的那条
测试上**。`CTF_RUNNER_PATH` 就是为这个留的（见文件顶部的 RUNNER 定义）。
四个变异体与它们各自该红的测试：

    把 traces 从 _FRESH 里拿掉（回退成 symlink） → test_seed_home_puts_..._fresh_empties
                                                   + test_isolated_home_actually_hides_the_poison
    删掉 solve 的 FULILIAN_HOME=...               → test_runner_passes_fulilian_home_to_solve
    把每题一个家改回全批共用一个 $RUN_ROOT/home    → test_runner_passes_fulilian_home_to_solve
    把 _FP_AFTER 改成等于 _FP_BEFORE（假比对）      → test_runner_verifies_the_real_home_was_not_written

**变异体还抓出过本测试自己的一个洞**：`test_isolated_home_actually_hides_the_poison`
最初只用 `grep -rlF` 找内容，而 `grep -r` **不跟进递归中遇到的目录符号链接**
（`-R` 才跟进）—— 于是"traces 被 symlink 回真身"这个变异体下它照样是绿的。
可 agent 根本不做递归搜索：它知道自己的题名，直接 `cat ~/.fulilian/traces/<题名>.json`。
**断言方式弱于攻击方式时，锁就是装饰** —— 这条现在按直接路径查，并补了 `-R`。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# 可指向别处：用来把本组锁**在变异体上跑红一次**（见文件末尾"怎么证伪"）。
RUNNER = Path(os.environ.get("CTF_RUNNER_PATH") or REPO / "benchmarks" / "ctf_hard_run.sh")
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


# ── 第三轮：产品家目录（`~/.fulilian`）──────── ──────────────────────────
#
# 上面那些锁全在 `/tmp` 里。而 agent 的**产品家目录是固定路径**，`mktemp`
# 隔离碰不到它 —— 实测那里就躺着答案：
#
#   traces/<id>.json      ← 文件名就是 work_dir 名（agent 知道自己的名字）
#   learning.json         ← 19 处明文 flag，2026-09-13 00:25 还在被写
#   cache/terminal-output/*.log
#
# 而且它**自己会长**：每一跑写进新 flag，留给下一跑读 —— 与 n3 那次
# "run1/run2 互为兄弟"同一个病，只是搬进了产品目录。
#
# 为什么要一条**功能**锁而不是 grep：这组断言的价值全在"分界对不对"
# （哪些给空、哪些 symlink）。分界写反了（比如 traces 也 symlink 回真身）
# 源码看着仍然"有 FULILIAN_HOME 这回事"，但泄漏原样回来。所以下面用
# `--seed-home` 真的布一个家，再检查布出来的东西。


def _seed(source_fulilian: Path, dst: Path) -> subprocess.CompletedProcess:
    """用 `HOME=<source_fulilian 的父目录>` 跑 `--seed-home`，去布 `<dst>`。

    `_RH` 是 `${HOME}/.fulilian`，所以**换 HOME 就能控制它读哪个源** ——
    测试因此不碰真实家目录。

    注意传的是那个 `.fulilian` 目录本身，`HOME` 取它的**父目录**：第一版直接
    把 `.fulilian` 当 HOME，于是 `_RH` 变成 `.../.fulilian/.fulilian` —— 不存在，
    `_seed_home` 便按"源不存在"静默 return 0，测试红了却看不出原因。
    """
    return subprocess.run(
        ["bash", str(RUNNER), "--seed-home", str(dst)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": str(source_fulilian.parent)},
    )


@pytest.fixture()
def poisoned_home(tmp_path: Path) -> Path:
    """一个**假装是产品家目录**的源：答案态里有明文 flag。"""
    h = tmp_path / "fakehome" / ".fulilian"
    (h / "traces").mkdir(parents=True)
    # 文件名 = 题目名：这正是 agent 能直接猜到的那个路径
    (h / "traces" / f"{FIXTURE}.json").write_text(
        '{"flag": "flag{leaked_from_previous_run}"}', encoding="utf-8")
    (h / "cache" / "terminal-output").mkdir(parents=True)
    (h / "cache" / "terminal-output" / "out-1.log").write_text(
        "flag{leaked_from_previous_run}", encoding="utf-8")
    (h / "learning.json").write_text(
        '{"a": "flag{leaked_from_previous_run}"}', encoding="utf-8")
    # 其余答案态目录也各放一份，好让"给空"这条断言覆盖到多个条目，
    # 而不是只测 traces/learning.json 两个特例。
    for d in ("logs", "sessions", "memories", "pastes"):
        (h / d).mkdir()
        (h / d / "poison.txt").write_text(
            "flag{leaked_from_previous_run}", encoding="utf-8")
    # 这些是**跑起来必须有的**：认证、配置、技能库
    (h / "auth.json").write_text("{}", encoding="utf-8")
    (h / "config.yaml").write_text("model: x\n", encoding="utf-8")
    (h / "skills").mkdir()
    (h / "skills" / "ctf.md").write_text("skill", encoding="utf-8")
    return h


def test_seed_home_puts_answer_state_in_fresh_empties(
    poisoned_home: Path, tmp_path: Path
) -> None:
    """答案态必须是**新给的空**目录/文件，不能 symlink 回真身。

    分界写反（traces 也 symlink）就等于没修：agent 照样从自己家目录读到
    上一跑的 flag。这条测的就是那个分界。
    """
    dst = tmp_path / "isolated"
    r = _seed(poisoned_home, dst)
    assert r.returncode == 0, f"stderr={r.stderr!r}"

    # 答案态一律**不许 symlink 回真身**（这是判据，与源里有没有无关）。
    for name in ("traces", "cache", "logs", "sessions", "memories", "pastes"):
        assert not (dst / name).is_symlink(), f"{name} 绝不能 symlink 回真身"
    # 源里有的，必须被"新给一个空的"。
    for name in ("traces", "cache", "logs", "sessions", "memories", "pastes"):
        p = dst / name
        assert p.is_dir(), f"{name} 应当被建成新目录"
        assert not list(p.iterdir()), f"{name} 必须是空的（含内容=泄漏没堵住）"
    lj = dst / "learning.json"
    assert lj.is_file() and not lj.is_symlink() and lj.stat().st_size == 0

    # 而 agent 跑起来需要的那些仍要可达（symlink 到源）
    for name in ("auth.json", "config.yaml", "skills"):
        p = dst / name
        assert p.is_symlink(), f"{name} 应当 symlink 到源，否则 agent 起不来"
        assert p.exists(), f"{name} 的链接是断的"


def test_seed_home_leaves_the_source_home_untouched(
    poisoned_home: Path, tmp_path: Path
) -> None:
    """隔离是**复制式子集**，不是搬家：源家目录一个字节都不许动。

    这条防的是"图省事直接把源里的 traces 删了" —— 那是删用户的真实数据，
    而且会和并发会话打架。真正的判据是"读不到"，不是"源被清空"。
    """
    before = sorted(p.relative_to(poisoned_home) for p in poisoned_home.rglob("*"))
    _seed(poisoned_home, tmp_path / "isolated")
    after = sorted(p.relative_to(poisoned_home) for p in poisoned_home.rglob("*"))
    assert before == after, "源家目录被改动了"
    # 毒还得在源里（我们只负责"读不到"，不负责"替用户清"）
    assert (poisoned_home / "traces" / f"{FIXTURE}.json").exists()


def test_isolated_home_actually_hides_the_poison(
    poisoned_home: Path, tmp_path: Path
) -> None:
    """端到端判据：**照 agent 的找法**在隔离家里找不到 flag。

    上面两条断言"结构对"，这条断言"效果对"。

    **必须按"直接路径"查，不能只靠 `grep -r`。** 第一版就是 `grep -rlF`，
    结果在"traces 被 symlink 回真身"的变异体上**照样绿** —— 因为 `grep -r`
    不跟进递归中遇到的目录符号链接（`-R` 才跟进）。而 agent 根本不用递归
    搜索：它知道自己的题名，直接 `cat ~/.fulilian/traces/<题名>.json` 就行。
    断言方式要是弱于攻击方式，锁就是装饰 —— 变异体测试把这个缺口抓出来了。
    """
    dst = tmp_path / "isolated"
    _seed(poisoned_home, dst)

    # ① agent 真会用的直接路径：按名字读，读不到才算堵住。
    for rel in (f"traces/{FIXTURE}.json", "learning.json",
                "cache/terminal-output/out-1.log"):
        p = dst / rel
        if p.exists():                      # symlink 指向真身时这里就为真
            assert not p.is_symlink(), f"{rel} 是符号链接 —— 等于没隔离"

    # ② 再补一次"按内容找"：用 `-R`（跟进符号链接）。`-r` 会漏掉 symlink 目录，
    #    正是上面那个变异体暴露的盲区。
    hits = subprocess.run(
        ["grep", "-RlF", "flag{leaked_from_previous_run}", str(dst)],
        capture_output=True, text=True, timeout=60,
    )
    assert hits.stdout.strip() == "", f"隔离家里仍能读到旧答案：{hits.stdout}"


def test_runner_passes_fulilian_home_to_solve() -> None:
    """solve 必须以 `FULILIAN_HOME="$FHOME"` 起，且每题一个家。

    这条是**源码层**的补充锁：真正的行为验证要跑一次真 solve（要 API、
    要几分钟），不适合放进单测；而"忘了传这个变量"是本轮修的东西最容易
    回退的方式（删一行 env 而已，功能测试看不出来）。代价是它只在源码
    层面成立 —— 所以上面三条功能测试必须同时在。
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert 'FULILIAN_HOME="$FHOME"' in src
    assert 'FHOME="$RUN_ROOT/home/$id"' in src   # 每题一个，不是全批共用一个
    assert '_seed_home "$FHOME"' in src
    assert '_seal_tree "$FHOME"' in src          # 跑完也要收走（兜底）


def test_runner_verifies_the_real_home_was_not_written() -> None:
    """跑完要**比对真身家目录的指纹**，而不是声称隔离生效了。

    只在源码层锁，但锁的是最关键的一点：`_home_fp` 必须在开跑前和跑完后
    各取一次并比较。少了这个，`FULILIAN_HOME` 哪天被改名/被 profile 覆盖，
    泄漏会**静默**回来 —— 而"跑完才发现结果已被污染"是最贵的那种失败。
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert "_FP_BEFORE=\"$(_home_fp)\"" in src
    assert "_FP_AFTER=\"$(_home_fp)\"" in src
    assert "[ \"$_FP_BEFORE\" = \"$_FP_AFTER\" ]" in src
    assert src.index("_FP_BEFORE=") < src.index("_FP_AFTER="), "取指纹的顺序反了"


def test_selfcheck_modes_run_before_any_side_effect() -> None:
    """`--gate` / `--seed-home` 都必须在建目录之前分派。

    不只是洁癖：自检时 `$1` 就是那个选项名，而 `OUT="${1:-...}"` —— 真让
    `mkdir -p "$OUT"` 跑下去会在 cwd 里建一个叫 `--seed-home` 的目录，还会
    把用户给的自检目标填进 logs/mirror/proof。实测踩过一次。
    """
    src = RUNNER.read_text(encoding="utf-8")
    # 找**行首**那个 mkdir：`'mkdir -p "$OUT"'` 这个子串在注释里也出现过
    # （说明"为什么要在它之前退出"的那段），用裸 index() 会命中注释。
    mkdir_at = src.index('\nmkdir -p "$OUT"')
    assert src.index('= "--gate"') < mkdir_at
    assert src.index('= "--seed-home"') < mkdir_at
