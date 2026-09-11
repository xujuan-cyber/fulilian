#!/bin/bash
# 难题 holdout 跑批器 —— 与 easy 语料的 /tmp/ctf-rerun.sh 同协议，两点不同：
#
#   1. 每个 fixture 先跑 make_data.py 生成语料（4 MB 文本不进 git）。
#   2. 语料生成后**先跑参考解自证**，参考解解不出就直接中止 —— 否则
#      一次"解出率 0"的跑批无法区分「agent 不行」和「fixture 坏了」。
#      这是 holdout 的命门：基准自己错了，所有结论都是假的。
#
# 用法：
#   benchmarks/ctf_hard_run.sh [输出目录]
# 之后：
#   python benchmarks/ctf_path_baseline.py --dirs <输出目录>/* \
#       --manifest benchmarks/manifest-ctf-hard.yaml
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIX="$REPO/benchmarks/fixtures-hard"
OUT="${1:-/tmp/ctf-hard}"
LOGS="$OUT/logs"
IDS=(misc-bigscan-01 reverse-obfchain-01 forensics-brutelog-01)

rm -rf "$OUT"
mkdir -p "$LOGS"

for id in "${IDS[@]}"; do
  d="$OUT/$id"
  mkdir -p "$d"
  cp "$FIX/$id/README.md" "$FIX/$id/solve_reference.py" "$d/"

  echo "=== [$id] $(date +%H:%M:%S) 生成语料 ==="
  if ! python "$FIX/$id/make_data.py" --out "$d"; then
    echo "!!! [$id] 语料生成失败，中止"; exit 1
  fi

  echo "=== [$id] $(date +%H:%M:%S) 参考解自证 ==="
  if ! ( cd "$d" && python -c "
import sys; sys.path.insert(0, '$FIX'); sys.path.insert(0, '.')
import solve_reference as s
print(s.solve('.'))
" ) > "$LOGS/$id.reference.log" 2>&1; then
    echo "!!! [$id] 参考解跑不通，fixture 有问题 —— 中止（基准不可信时不许开跑）"
    tail -5 "$LOGS/$id.reference.log"
    exit 1
  fi

  echo "=== [$id] $(date +%H:%M:%S) 开始 solve ==="
  ( cd "$d" && timeout 3600 "$HOME/.local/bin/fulilian" solve "$d" -p ) \
      > "$LOGS/$id.log" 2>&1
  rc=$?
  echo "=== [$id] $(date +%H:%M:%S) 结束 rc=$rc flag=$(cat "$d/FLAG" 2>/dev/null) ==="
done

echo "ALL DONE $(date +%H:%M:%S)"
echo "采集： python $REPO/benchmarks/ctf_path_baseline.py \\"
echo "         --dirs $OUT/misc-bigscan-01 $OUT/reverse-obfchain-01 $OUT/forensics-brutelog-01 \\"
echo "         --manifest $REPO/benchmarks/manifest-ctf-hard.yaml"
