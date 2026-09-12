#!/bin/bash
# 难题 holdout 多批驱动器 —— 连跑 N 批并归档，供 `ctf_path_baseline.py --runs`
# 与 `--compare` 消费。
#
# 用法：
#   benchmarks/ctf_hard_n3.sh [批数=3] [归档目录=/tmp/ctf-n3-<时间戳>]
#
# ── 为什么需要这个脚本，而不是循环调 ctf_hard_run.sh ────────────────────
#
# 2026-09-13 实测：上一版驱动器把 run1/run2/run3 建成**兄弟目录**，
# 于是跑 run2 时 agent 可以 `ls ..` 看到 run1，而 run1 里留着上一批的
# `FLAG` 文件。日志原话：
#
#   "There's a run1 with the same challenge and a _mirror/_selfproof.
#    Let me check those to understand th..."
#
# 它确实照做了，并读到了 run1 的 `_selfproof/<id>/solve_reference.py`。
#
# 所以两次之间**不能有明文答案共存**。本脚本的做法：
#
#   1. 每批跑在**各自独立的 mktemp 父目录**里，不互为兄弟；
#   2. 每批跑完立刻 `tar` 打包、**删掉明文目录** —— 跑下一批时 `/tmp` 下
#      只剩压缩包，没有可 `cat` 的 `FLAG`；
#   3. 全部跑完（agent 已全部退出）再解包到归档目录，恢复 `--runs` 期望的
#      `batch<i>/<id>/` + `batch<i>/_mirror/` 布局。
#
# 第 2 步是关键：只要明文还在盘上，"跑下一批时它读不到"就只是运气。
#
# 仍然存在的边界：agent 若主动扫描整个 `/tmp` 并**解包**它遇到的压缩包，
# 仍能拿到旧答案。这是本机文件系统的固有性质，不靠"它大概不会"来关 ——
# ctf_hard_run.sh 的 preflight 会把它报出来，残留风险写在这里而不是藏起来。
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
N="${1:-3}"
ARCHIVE="${2:-/tmp/ctf-n3-$(date +%Y%m%d-%H%M%S)}"

mkdir -p "$ARCHIVE"

# 所有批共用的父目录，各自 mktemp —— 保证互不为兄弟。
OUT_PARENT="$(mktemp -d /tmp/.ctf-out.XXXXXXXXXX)"
RUN_PARENT="$(mktemp -d /tmp/.ctf-run.XXXXXXXXXX)"

echo "######## 归档目录 $ARCHIVE ########"
echo "######## OUT_PARENT  $OUT_PARENT（每批一个子目录；本批的 FLAG 只存在于此）"
echo "######## RUN_PARENT  $RUN_PARENT（logs/mirror/proof；与 OUT 无祖先关系）"

for i in $(seq 1 "$N"); do
  echo
  echo "######################## RUN $i / $N  开始 $(date +%H:%M:%S) ########################"
  bash "$REPO/benchmarks/ctf_hard_run.sh" "$OUT_PARENT/batch$i" "$RUN_PARENT/batch$i"
  rc=$?
  echo "######################## RUN $i / $N  结束 rc=$rc $(date +%H:%M:%S) ########################"

  if [ "$rc" -ne 0 ]; then
    echo "!!! 第 $i 批 rc=$rc —— 中止，不再跑后续批次（半份数据比没有更坏）"
    exit "$rc"
  fi

  # 立刻打包并删除明文：下一批跑起来时 /tmp 里没有本条批次的 FLAG 可读。
  tar -czf "$ARCHIVE/batch$i.tgz"        -C "$OUT_PARENT" "batch$i" || exit 1
  tar -czf "$ARCHIVE/batch$i.mirror.tgz" -C "$RUN_PARENT" "batch$i" || exit 1
  rm -rf "$OUT_PARENT/batch$i" "$RUN_PARENT/batch$i"
  echo "  已归档并清除明文：$(du -h "$ARCHIVE/batch$i.tgz" | cut -f1) + mirror"
done

# ── 全部跑完，agent 已退出，此时才解包 ─────────────────────────────────
echo
echo "######## 解包归档（agent 已全部退出）$(date +%H:%M:%S) ########"
BATCHES=()
for i in $(seq 1 "$N"); do
  tar -xzf "$ARCHIVE/batch$i.tgz" -C "$ARCHIVE" || exit 1
  # mirror 解到 batch<i>/_mirror —— run_repeat_mode 会自动认这个位置
  tar -xzf "$ARCHIVE/batch$i.mirror.tgz" -C "$ARCHIVE" || exit 1
  mv "$ARCHIVE/batch$i/mirror" "$ARCHIVE/batch$i/_mirror" || exit 1
  BATCHES+=("$ARCHIVE/batch$i")
done

# 解包后自证：归档里不该出现参考解/自证目录残留
leak="$(find "$ARCHIVE" -name 'solve_reference*' -o -name '*.reference.log' -o -name '_selfproof' 2>/dev/null)"
if [ -n "$leak" ]; then
  echo "!!! 归档里混进了参考解/自证产物，说明围堵没生效："; echo "$leak"; exit 1
fi
echo "  ✅ 归档内无参考解/自证残留"

rm -rf "$OUT_PARENT" "$RUN_PARENT" 2>/dev/null

echo
echo "ALL RUNS DONE $(date +%H:%M:%S)"
echo "采集："
echo "  python $REPO/benchmarks/ctf_path_baseline.py \\"
echo "      --runs ${BATCHES[*]} \\"
echo "      --manifest $REPO/benchmarks/manifest-ctf-hard.yaml \\"
echo "      --json $ARCHIVE/<名字>.json"
