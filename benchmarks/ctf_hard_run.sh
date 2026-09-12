#!/bin/bash
# 难题 holdout 跑批器 —— 与 easy 语料的 /tmp/ctf-rerun.sh 同协议，四点不同：
#
#   1. 每个 fixture 先跑 make_data.py 生成语料（4 MB 文本不进 git）。
#   2. 语料生成后**先跑参考解自证**，参考解解不出就直接中止 —— 否则
#      一次"解出率 0"的跑批无法区分「agent 不行」和「fixture 坏了」。
#      这是 holdout 的命门：基准自己错了，所有结论都是假的。
#   3. 自证与 solve **目录分离**，且 solve 前硬闸检查答案残留。
#   4. **所有非 work_dir 的产物都在 `$OUT` 之外**（见下）。
#
# ── 2026-09-13：泄漏围堵 ────────────────────────────────────────────────
#
# 上一版把 `logs/`、`_mirror/`、`_selfproof/` 都放在 `$OUT` 下，与各题的
# work_dir **同级**。agent 的工作目录就是 `$OUT/<id>`，于是一个 `ls ..`
# 就能看到三样东西：
#
#   $OUT/logs/<id>.reference.log   ← 参考解的 stdout，**明文 flag**
#   $OUT/_selfproof/<id>/          ← 参考解源码
#   $OUT/_mirror/<id>.solver.log   ← 本题自己的轨迹（无害）
#
# 硬闸只搜了 `$d` 内部，对隔壁一无所知。实测后果（`/tmp/ctf-n3/run1`
# 的 reverse-obfchain-01）：agent 的原话是
#
#   "The reference log shows a flag"        → 读 logs/*.reference.log
#   "Let me check the other challenges' logs"
#   "The reference logs match the FLAG files for the other tasks (ground truth)"
#   "The _selfproof directory has the official solve_reference.py. Let me read it"
#
# 三例实测（n=3 的两侧共 24 次跑）：**flag 都是真解出来的**，泄漏被用作
# **事后确认**；但 (a) 确认本身烧掉 10–15 次调用，(b) 卡住的题烧得更多 ——
# 浪费量与「这题难不难」正相关，**正好污染我们要测的那个变量**。
# 其中 misc-bigscan-01 那次的入口是 `verify_flag` 的**假阴性**（把真解判成
# "hallucination"），agent 为了搞清为什么才去翻泄漏。
#
# 所以本版把这三样整体挪到 `$RUN_ROOT`（mktemp -d，与 `$OUT` **无祖先/
# 后代关系**），并把硬闸从"只搜 work_dir"改成"搜 work_dir 的**整条祖先链**
# 到 `$OUT` 为止"。R 系列还要求跨批不共享父目录 —— 见 ctf_hard_n3.sh。
#
# **仍然存在的边界（不要假装它关上了）：** 本机 `/tmp` 下历史遗留的
# `ctf-*` 跑批目录里仍有旧 FLAG。agent 若主动 `find /tmp -name FLAG` 仍能
# 拿到**旧跑批**的 flag（同题同 flag，等于答案）。开跑前有 preflight 扫描
# 并打印清单；跨会话的陈旧目录归用户决定删不删，跑批器不擅自删别人的数据。
# 彻底解决要每题每批换 flag 值（改 4 个现有 fixture 的生成器），本轮不做 ——
# fixture 的"只有新增、没有调参"这条不变量比它值钱。
#
# 用法：
#   benchmarks/ctf_hard_run.sh [输出目录] [RUN_ROOT]
# 之后：
#   python benchmarks/ctf_path_baseline.py --dirs <输出目录>/* \
#       --manifest benchmarks/manifest-ctf-hard.yaml --mirror-dir <RUN_ROOT>/mirror
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIX="$REPO/benchmarks/fixtures-hard"
OUT="${1:-/tmp/ctf-hard}"
# RUN_ROOT 装 logs/ mirror/ proof/，必须在 OUT 之外。默认 mktemp 保证
# 唯一且不可预测；显式传入时下面的隔离断言会检查它与 OUT 不相交。
RUN_ROOT="${2:-${CTF_RUN_ROOT:-}}"
IDS=(misc-bigscan-01 misc-chunkconcat-01 reverse-obfchain-01 forensics-brutelog-01)

# ── 硬闸：work_dir 的整条祖先链上不许有答案 ────────────────────────────
# 老版只 `find "$d"` —— 而泄漏物从来不在 `$d` 里，全在它隔壁。现在从
# `$d` 往上走到边界（含），每一层都查。边界以上的层**不查**：那里是用户
# 自己的目录（如 ~/.fulilian），误报会把正常路径判成泄漏。
#
# 抽成 $1=被查目录 $2=上溯边界 的独立函数，是为了让它**可被直接测试** ——
# 见下面的 `--gate` 自检模式。上一版把这段内联在循环里，无法单独跑，于是
# "硬闸生效了没有"只能靠读源码确认；而本仓库已有的教训是**源码看着对不等于
# 它在生产路径上被调用过**。能跑的闸门才是闸门。
_gate() {
  local d="$1" stop="$2" hits="" a entry base
  # ① work_dir 内部：递归查（老版就只查了这一层）。
  hits="$(find "$d" \( -name 'FLAG' -o -name 'solve_reference*' \
        -o -name '*.reference.log' -o -name '_selfproof' -o -name '_mirror' \) 2>/dev/null)"
  # ② $OUT 的直属内容**只许是本次的题目录**。这一条才是关键：
  #    三处泄漏物（logs/、_selfproof/、_mirror/）全都是 $OUT 的直属子目录，
  #    而它们的**内容**在 `-maxdepth 1` 下不可见 —— 初版就是这么漏掉
  #    `$OUT/logs/<id>.reference.log` 的（明文 flag 就在里面）。
  #    所以这里不按"名字像不像泄漏物"判，而是按**白名单**判：不在 IDS 里的
  #    任何条目都是外来物，一律拒绝。加了新 fixture 只改 IDS 一处即可。
  for entry in "$stop"/* "$stop"/.[!.]*; do
    [ -e "$entry" ] || continue
    base="$(basename "$entry")"
    if [ -d "$entry" ] && [[ " ${IDS[*]} " == *" $base "* ]]; then continue; fi
    hits="$hits$entry"$'\n'
  done
  # ③ 往上：**兄弟跑批根**不许存在（上一版 run1/run2/run3 就是这么互相看见
  #    的 —— agent 原话 "There's a run1 with the same challenge"）。
  #    判据是"兄弟目录里有没有带 FLAG 的题目录"，不是看目录名 —— 名字可以
  #    随便取，`_gate` 不猜语义。深度限制在 2，是为了不把 `/tmp` 下的
  #    历史遗留（深度 3+）算成硬失败：那种情况由 preflight 报出、由用户决定，
  #    不在这里静默拦死正常跑批。
  local parent; parent="$(dirname "$stop")"
  if [ "$parent" != "/" ]; then
    hits="$hits$(find "$parent" -mindepth 1 -maxdepth 3 -name 'FLAG' \
          -not -path "$stop/*" -not -path "$stop" 2>/dev/null)"
  fi
  [ -n "$hits" ] && { echo "$hits"; return 1; }
  return 0
}

# 自检模式：`ctf_hard_run.sh --gate <目录> <边界>` → 只跑硬闸并打印结论。
# 给回归锁用（tests/benchmarks/test_ctf_holdout_isolation.py）；不跑批、
# 不建目录、不碰 /tmp —— 所以必须放在下面所有副作用**之前**。
if [ "${1:-}" = "--gate" ]; then
  if _gate "$2" "$3"; then echo "GATE-CLEAN"; exit 0
  else echo "GATE-LEAK"; exit 1; fi
fi

if [ -z "$RUN_ROOT" ]; then
  RUN_ROOT="$(mktemp -d /tmp/ctf-runroot.XXXXXXXXXX)"
fi
LOGS="$RUN_ROOT/logs"
MIRROR="$RUN_ROOT/mirror"
PROOF="$RUN_ROOT/proof"
mkdir -p "$OUT" "$LOGS" "$MIRROR" "$PROOF"

_real() { (cd "$1" 2>/dev/null && pwd -P) || echo "__missing__"; }

# ── 隔离断言：RUN_ROOT 与 OUT 不许互为祖先或后代 ──────────────────────
# 这条不满足就等于没修：agent 从 OUT/<id> 往上走能回到 RUN_ROOT。
_o="$(_real "$OUT")"; _r="$(_real "$RUN_ROOT")"
case "$_r/" in "$_o/"*) echo "!!! RUN_ROOT 在 OUT 内部（$_r ⊂ $_o）—— 泄漏没堵住，中止"; exit 1;; esac
case "$_o/" in "$_r/"*) echo "!!! OUT 在 RUN_ROOT 内部（$_o ⊂ $_r）—— 泄漏没堵住，中止"; exit 1;; esac
echo "  隔离：OUT=$_o"; echo "        RUN_ROOT=$_r（互不为祖先/后代）"

# ── preflight：本机是否还有历史跑批目录残留答案 ────────────────────────
# **只报不删**。跑批器不擅自删别的会话留下的数据；但必须让"台子上还有
# 旧答案"这件事在开跑前被看见 —— 静默通过等于假装它不存在。
echo "######## preflight $(date +%H:%M:%S) ########"
_stale="$(find /tmp -maxdepth 4 -name 'FLAG' -path '*ctf*' 2>/dev/null | grep -v "^$_o/" | head -10)"
if [ -n "$_stale" ]; then
  echo "  ⚠️  /tmp 下仍有历史跑批残留的 FLAG（agent 若 find /tmp 可读到旧答案）："
  echo "$_stale" | sed 's/^/      /'
  echo "      → 建议：rm -rf 这些跑批目录后重跑；本轮结果需按此打折。"
else
  echo "  ✅ /tmp 下未发现历史 FLAG 残留"
fi

rm -rf "$LOGS" "$MIRROR" "$PROOF"; mkdir -p "$LOGS" "$MIRROR" "$PROOF"

for id in "${IDS[@]}"; do
  d="$OUT/$id"          # solve 工作目录：只许有题面 + 语料
  p="$PROOF/$id"        # 自证目录：参考解读在这里，**不在 OUT 的祖先链上**
  mkdir -p "$d" "$p"
  cp "$FIX/$id/README.md" "$d/"

  echo "=== [$id] $(date +%H:%M:%S) 生成语料 ==="
  if ! python "$FIX/$id/make_data.py" --out "$d"; then
    echo "!!! [$id] 语料生成失败，中止"; exit 1
  fi

  # 自证必须跟 solve 目录分开 —— 且现在要**离得足够远**。初版把
  # solve_reference.py 一起 cp 进 solve 目录，agent 直接去偷；第二版挪到
  # `$OUT/_selfproof`（隔壁），agent 照样 `ls ..` 找到。距离不够 = 没修。
  rm -rf "$p"; mkdir -p "$p"
  cp "$d"/* "$p/" && cp "$FIX/$id/solve_reference.py" "$p/"

  echo "=== [$id] $(date +%H:%M:%S) 参考解自证 ==="
  if ! ( cd "$p" && python -c "
import sys; sys.path.insert(0, '$FIX'); sys.path.insert(0, '.')
import solve_reference as s
print(s.solve('.'))
" ) > "$LOGS/$id.reference.log" 2>&1; then
    echo "!!! [$id] 参考解跑不通，fixture 有问题 —— 中止（基准不可信时不许开跑）"
    tail -5 "$LOGS/$id.reference.log"
    exit 1
  fi

  # solve 前硬闸。
  if ! leak="$(_gate "$d")"; then
    echo "!!! [$id] work_dir 或其祖先链上混进了答案，会污染基线 —— 中止"
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

echo "ALL DONE $(date +%H:%M:%S)  RUN_ROOT=$RUN_ROOT"

# 采集命令从 IDS 生成，不硬编码 —— 初版把三个 id 写死在这里，
# 加第四题时就会静默漏采（跑批说做了四题，采集只报三题）。
dirs=""
for id in "${IDS[@]}"; do dirs="$dirs $OUT/$id"; done
echo "采集： python $REPO/benchmarks/ctf_path_baseline.py \\"
echo "         --dirs$dirs \\"
echo "         --mirror-dir $MIRROR \\"
echo "         --manifest $REPO/benchmarks/manifest-ctf-hard.yaml"
