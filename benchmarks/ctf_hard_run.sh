#!/bin/bash
# 难题 holdout 跑批器 —— 与 easy 语料的 /tmp/ctf-rerun.sh 同协议，三点不同：
#
#   1. 每个 fixture 先跑 make_data.py 生成语料（4 MB 文本不进 git）。
#   2. 语料生成后**先跑参考解自证**，参考解解不出就直接中止 —— 否则
#      一次"解出率 0"的跑批无法区分「agent 不行」和「fixture 坏了」。
#      这是 holdout 的命门：基准自己错了，所有结论都是假的。
#   3. 自证与 solve **目录分离**，且 solve 前硬闸检查参考解残留。
#      初版把参考解 cp 进 solve 目录，agent 真的去偷了（见下方注释）。
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
MIRROR="$OUT/_mirror"          # 镜像运行日志：在 solve 目录之外，agent 够不着
IDS=(misc-bigscan-01 misc-chunkconcat-01 reverse-obfchain-01 forensics-brutelog-01)

rm -rf "$OUT"
mkdir -p "$LOGS" "$MIRROR"

for id in "${IDS[@]}"; do
  d="$OUT/$id"          # solve 工作目录：只许有题面 + 语料
  proof="$OUT/_selfproof/$id"   # 自证目录：参考解读在这里，不进 solve 目录
  mkdir -p "$d" "$proof"
  cp "$FIX/$id/README.md" "$d/"

  echo "=== [$id] $(date +%H:%M:%S) 生成语料 ==="
  if ! python "$FIX/$id/make_data.py" --out "$d"; then
    echo "!!! [$id] 语料生成失败，中止"; exit 1
  fi

  # 自证必须跟 solve 目录分开。初版把 solve_reference.py 一起 cp 进 solve 目录，
  # 结果 agent 在 forensics 那题直接去偷了 —— 原话 "check the reference common
  # module for any flag extraction logic"，连试三次（file not found / Traceback /
  # search_files total_count=0）全败，flag 仍是真的，但这批数字已经不可信了：
  # 一次成功偷到就是满分假象，而失败与否全看它手气。基准不能有"看运气"的项。
  rm -rf "$proof"; mkdir -p "$proof"
  cp "$d"/* "$proof/" && cp "$FIX/$id/solve_reference.py" "$proof/"

  echo "=== [$id] $(date +%H:%M:%S) 参考解自证 ==="
  if ! ( cd "$proof" && python -c "
import sys; sys.path.insert(0, '$FIX'); sys.path.insert(0, '.')
import solve_reference as s
print(s.solve('.'))
" ) > "$LOGS/$id.reference.log" 2>&1; then
    echo "!!! [$id] 参考解跑不通，fixture 有问题 —— 中止（基准不可信时不许开跑）"
    tail -5 "$LOGS/$id.reference.log"
    exit 1
  fi

  # solve 前硬闸：工作目录里出现任何参考解残留就拒绝开跑。
  # 这一条是上面那次污染的直接产物 —— 别再靠"记得别 cp"来保证。
  leak="$(find "$d" -name 'solve_reference*' -o -name '*.reference.log' 2>/dev/null)"
  if [ -n "$leak" ]; then
    echo "!!! [$id] solve 目录里混进了参考解，会污染基线 —— 中止"
    echo "$leak"
    exit 1
  fi

  # 运行日志镜像到 solve 目录之外。work_dir 是 agent 的地盘：实测它用
  # write_file 把 solver.log 覆盖成过一份解题报告（misc-chunkconcat-01），
  # 那一跑的工具面数据全丢，0 被读成了"高效"。镜像只增不改，与 work_dir
  # 内那份并存 —— stopper 的增量扫描、replay/writeup 都不受影响。
  echo "=== [$id] $(date +%H:%M:%S) 开始 solve ==="
  ( cd "$d" && FULILIAN_SOLVER_LOG_MIRROR="$MIRROR/$id.solver.log" \
      timeout 3600 "$HOME/.local/bin/fulilian" solve "$d" -p ) \
      > "$LOGS/$id.log" 2>&1
  rc=$?
  echo "=== [$id] $(date +%H:%M:%S) 结束 rc=$rc flag=$(cat "$d/FLAG" 2>/dev/null) ==="
done

echo "ALL DONE $(date +%H:%M:%S)"

# 采集命令从 IDS 生成，不硬编码 —— 初版把三个 id 写死在这里，
# 加第四题时就会静默漏采（跑批说做了四题，采集只报三题）。
dirs=""
for id in "${IDS[@]}"; do dirs="$dirs $OUT/$id"; done
echo "采集： python $REPO/benchmarks/ctf_path_baseline.py \\"
echo "         --dirs$dirs \\"
echo "         --mirror-dir $MIRROR \\"
echo "         --manifest $REPO/benchmarks/manifest-ctf-hard.yaml"
