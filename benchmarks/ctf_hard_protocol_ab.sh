#!/bin/bash
# hard-solve-protocol 配对 A/B 驱动器 —— 同一题、同一份代码，只翻 env。
#
# 用法：
#   benchmarks/ctf_hard_protocol_ab.sh <题目id> [批数=3] [归档目录=/tmp/ctf-ab-<时间戳>]
#
# 控制侧（ctl）：被拨开关 **不设**（默认 FULILIAN_CTF_HARD_SOLVE_PROTOCOL）
# 实验侧（exp）：被拨开关=1 —— TOGGLE_ENV=NAME 可换开关（⑤ P0.2 用
# FULILIAN_SOLVE_STATE_INJECT）。
# 每侧 N 批，每批跑在独立 mktemp 父目录、跑完即 tar+删除明文 —— 与
# ctf_hard_n3.sh 同一套防"run1/run2 互为兄弟"的手法。
#
# 为什么是"配对"：两侧跑同一题、同一批序，逐批对比 api_calls / 首屏 token /
# 轨迹。计划书 A3/A9 结案的结论：配对量（同题同批序）把不可归因变成可归因，
# 聚合量对落在固定开销里的效应看不见。所以本驱动产出的读数单位是"批次对"，
# 不是"两侧各聚合一次"。
#
# 代码隔离（④ 的教训：editable 安装解析到活工作树，另一会话 09:29 的文件
# sweep 差点混进实验侧）：建议从 HEAD 快照 worktree 跑 + PYTHONPATH 指快照，
# 活树怎么漂移两侧代码都不变：
#   git worktree add /tmp/ab-snap HEAD
#   TOGGLE_ENV=… PYTHONPATH=/tmp/ab-snap bash /tmp/ab-snap/benchmarks/ctf_hard_protocol_ab.sh …
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ID="${1:?用法: ctf_hard_protocol_ab.sh <题目id> [批数=3] [归档目录]}"
N="${2:-3}"
ARCHIVE="${3:-/tmp/ctf-ab-$(date +%Y%m%d-%H%M%S)}"
TOGGLE_ENV="${TOGGLE_ENV:-FULILIAN_CTF_HARD_SOLVE_PROTOCOL}"

echo "######## 配对 A/B: 题目=$ID 每侧 ${N} 批 归档=$ARCHIVE ########"
echo "  代码=当前工作树（同一份）; 两侧仅差 $TOGGLE_ENV"

mkdir -p "$ARCHIVE"

run_side() {
  local side="$1"
  echo "######################## SIDE $side 开始 $(date +%H:%M:%S) ########################"
  local out_parent run_parent
  out_parent="$(mktemp -d /tmp/.ab-out.XXXXXXXXXX)"
  run_parent="$(mktemp -d /tmp/.ab-run.XXXXXXXXXX)"
  for i in $(seq 1 "$N"); do
    echo "######## SIDE $side RUN $i / $N $(date +%H:%M:%S) ########"
    if [ "$side" = exp ]; then
      export "$TOGGLE_ENV=1"
    else
      unset "$TOGGLE_ENV"
    fi
    CTF_IDS="$ID" bash "$REPO/benchmarks/ctf_hard_run.sh" \
        "$out_parent/$side-$i" "$run_parent/$side-$i" || exit 1
    # 跑完立刻打包删除明文：下一批跑起来时 /tmp 里没有本批的 FLAG 可读。
    tar -czf "$ARCHIVE/$side-$i.tgz"        -C "$out_parent" "$side-$i" || exit 1
    tar -czf "$ARCHIVE/$side-$i.mirror.tgz" -C "$run_parent" "$side-$i" || exit 1
    rm -rf "$out_parent/$side-$i" "$run_parent/$side-$i"
  done
  rm -rf "$out_parent" "$run_parent"
  unset "$TOGGLE_ENV"
  echo "######################## SIDE $side 结束 $(date +%H:%M:%S) ########################"
}

run_side ctl
run_side exp

# ── 全部跑完（agent 已退出）才解包，恢复 --runs 期望的布局 ──────────────
echo "######## 解包归档 $(date +%H:%M:%S) ########"
BATCHES=()
for side in ctl exp; do
  for i in $(seq 1 "$N"); do
    tar -xzf "$ARCHIVE/$side-$i.tgz"        -C "$ARCHIVE" || exit 1
    tar -xzf "$ARCHIVE/$side-$i.mirror.tgz" -C "$ARCHIVE" || exit 1
    mv "$ARCHIVE/$side-$i/mirror" "$ARCHIVE/$side-$i/_mirror" || exit 1
    BATCHES+=("$ARCHIVE/$side-$i")
  done
done

leak="$(find "$ARCHIVE" -name 'solve_reference*' -o -name '*.reference.log' -o -name '_selfproof' 2>/dev/null)"
if [ -n "$leak" ]; then
  echo "!!! 归档里混进参考解/自证产物，围堵没生效："; echo "$leak"; exit 1
fi
echo "  ✅ 归档内无参考解/自证残留"

echo
echo "ALL RUNS DONE $(date +%H:%M:%S)"
echo "归档: $ARCHIVE"
echo "采集（两侧分开，便于 --compare / 配对读数）："
echo "  CTL: python $REPO/benchmarks/ctf_path_baseline.py --runs $ARCHIVE/ctl-* --manifest $REPO/benchmarks/manifest-ctf-hard.yaml --json $ARCHIVE/ctl.json"
echo "  EXP: python $REPO/benchmarks/ctf_path_baseline.py --runs $ARCHIVE/exp-* --manifest $REPO/benchmarks/manifest-ctf-hard.yaml --json $ARCHIVE/exp.json"
