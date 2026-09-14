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
# ── 2026-09-13（第二轮）：位置不是边界，可读性才是 ──────────────────────
#
# 上一版把产物"挪到 `$OUT` 之外"就宣布修好了。**挪位置挡不住全盘搜索。**
# 复核时实测到的三处仍在漏：
#
#   ① `$RUN_ROOT/logs/<id>.reference.log` —— 参考解 stdout，**当前这道题的
#      明文 flag**，在它自己 solve 期间就躺在盘上，`find /tmp -name
#      '*.reference.log'` 直接命中。
#   ② 本脚本第 186 行原来是 `flag=$(cat "$d/FLAG")` —— 跑批器自己的 stdout
#      被重定向到 `/tmp/ctf-n3.log` 之类的日志文件，**同批后跑的题**读得到。
#      实测五个历史批日志里共 34 处明文 flag，全部出自这一行。
#   ③ 跑完那题的 work_dir 原样留在 `$OUT` 里 —— 而 agent 自己写的
#      `ctf-notes.md` / `blackboard.json` 里就有明文 flag。
#
# 改法是把判据从"放哪"换成"**跑批期间在不在盘上**"：
#   · 参考解输出 + 参考解源码（PROOF 目录）—— 自证通过后**立即删除**，
#     只留 sha256 对账（哈希进不了答案）；
#   · 跑完那题的整棵 work_dir / runner 日志 / 镜像 —— 立即收进暂存区，
#     等全部跑完（agent 已退出）再还原回原布局 ⇒ 采集器与归档格式零改动；
#   · stdout 不再打印明文 flag，改打印 sha256 前 8 位。
#
# **残余边界（不要假装它关上了）：** 暂存用 gzip，而 gzip 不是加密 ——
# 有能力的 agent 主动 `gunzip` 仍能读到旧答案；同理它若 `tar xzf` 上层归档
# 也拿得到。**同用户同文件系统下，"不让它在盘上"是唯一真正的边界，"放哪"
# 与"压一下"都只是提高成本。** 真关上门要换用户或容器跑 agent。preflight
# 仍会扫出历史残留并打印清单（跑批器不擅自删别的会话留下的数据）。
# 另一个固有面：fixture 是确定性的，flag 明文就在仓库里
# （`manifest-ctf-hard.yaml` 的 expected_flag、make_data.py 的 FLAG 常量），
# agent 若去读仓库源码同样拿得到 —— 这条要靠"别把仓库放在它手边"解决，
# 不是靠跑批器。
#
# ── 2026-09-13（第三轮）：`/tmp` 之外还有一个固定路径 ────────────────────
#
# 清完 /tmp 之后做了一次全盘 grep（按 manifest 里那四个**真** flag 的字面量，
# 不是 grep 'flag{' —— 那样满屏都是误报），发现答案还躺在两处：
#
#   ① **agent 自己的产品家目录** `~/.fulilian/`：
#        traces/<题名>.json   ← 文件名就是 work_dir 名，agent 知道自己的名字，
#                               可以直接 cat，不必递归搜索
#        learning.json        ← 19 处明文 flag，2026-09-13 00:25 还在被写
#        cache/terminal-output/*.log
#      这是 mktemp 隔离**碰不到**的：路径是固定的。而且它**自己会长** ——
#      每一跑写进新 flag 留给下一跑读，与 n3 那次 "run1/run2 互为兄弟"
#      同一个病，只是搬进了产品目录。修法见 `_seed_home`：每题一个
#      `FULILIAN_HOME`，答案态给空、其余 symlink。
#      跑完用 `_home_fp` 比对真身指纹，**证明**隔离生效而不是声称。
#
#   ② **编排者自己的会话记录** `~/.claude/projects/*.jsonl`、`file-history/`：
#      agent 与编排者同用户，读得到。只要编排过程中把明文 flag 打到过工具
#      输出，答案就在那里，且每打一次新写一份。跑批器**不删**它（那是用户的
#      对话记录/审计线索），只在 preflight 报出来。真正的纪律是"跑批时别把
#      明文 flag 打到工具输出" —— 本文件的 stdout 已改成只打 sha256。
#
# 教训（第三轮才补上）：**"换个位置"和"清掉 /tmp"都不是判据，"在不在它能读到
# 的地方"才是。** 每修一处都要重新做一次全盘搜索，而不是假设"这回想全了"。
#
# 用法：
#   benchmarks/ctf_hard_run.sh [输出目录] [RUN_ROOT]
# 之后：
#   python benchmarks/ctf_path_baseline.py --dirs <输出目录>/* \
#       --manifest benchmarks/manifest-ctf-hard.yaml --mirror-dir <RUN_ROOT>/mirror
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIX="$REPO/benchmarks/fixtures-hard"

# ── agent 自己的家目录：跑批期间必须换成随批自带的 ──────────────────────
# 上面整套围堵都做在 /tmp 里，而 agent 的**产品家目录**（`~/.fulilian`）是
# **固定路径**，mktemp 隔离碰不到。实测那里就躺着答案：
#
#   traces/<id>.json           ← 文件名**就是 work_dir 名**，agent 知道自己的名字
#   learning.json              ← 19 处明文 flag，2026-09-13 00:25 还在被写
#   cache/terminal-output/*.log
#
# 而且它**自己会长**：每一跑都把刚解的 flag 写进去，留给下一跑读 —— 与 n3
# 那次 "run1/run2 互为兄弟" 是同一个病，只是从 /tmp 搬进了产品目录，
# 于是 `/tmp` 里的任何隔离对它都无效。
#
# 用 `FULILIAN_HOME` 把整棵树改指到随批自带的家。这是官方机制而非绕路：
# `fulilian_constants.py` 明写 "subprocess spawner should pass FULILIAN_HOME
# explicitly"，本机也没有 `active_profile`（有的话那条 guard 会告警）。
# 需要什么就 symlink 什么（读得到、写不脏真身）；会写运行状态的目录一律给
# **空的新目录** —— 写进去也只在 RUN_ROOT 内，跑完随批一起封存。
#
# 定义放在这里（`$OUT` 与建目录之前）是为了让 `--seed-home` 自检能像
# `--gate` 一样"在一切副作用之前"退出 —— 见下面的自检分派。
_RH="${HOME}/.fulilian"
# 既含答案、又会被写的运行态：给空目录，别 symlink 回真身。
_FRESH=(traces cache logs sessions state memories pastes session-exports \
        terminal-sessions pending_messages sandboxes kanban)
# 同上的单文件版（learning.json 是答案库，kanban.db* 是会被写的 sqlite）
_FRESH_FILES=(learning.json kanban.db kanban.db-shm kanban.db-wal)

_seed_home() {   # _seed_home <目标家目录>
  local dst="$1" e base
  mkdir -p "$dst"
  [ -d "$_RH" ] || return 0
  for e in "$_RH"/* "$_RH"/.[!.]*; do
    [ -e "$e" ] || continue
    base="$(basename "$e")"
    if [[ " ${_FRESH[*]} " == *" $base "* ]]; then mkdir -p "$dst/$base"; continue; fi
    if [[ " ${_FRESH_FILES[*]} " == *" $base "* ]]; then : > "$dst/$base"; continue; fi
    ln -s "$e" "$dst/$base"
  done
}

OUT="${1:-/tmp/ctf-hard}"
# RUN_ROOT 装 logs/ mirror/ proof/，必须在 OUT 之外。默认 mktemp 保证
# 唯一且不可预测；显式传入时下面的隔离断言会检查它与 OUT 不相交。
RUN_ROOT="${2:-${CTF_RUN_ROOT:-}}"
IDS=(misc-bigscan-01 misc-chunkconcat-01 reverse-obfchain-01 forensics-brutelog-01)
# 子集跑批：CTF_IDS 覆盖题目列表（逗号分隔，如 CTF_IDS=reverse-obfchain-01）。
# 硬闸白名单、采集命令都以 IDS 为准，所以单题批的 gate 与 manifest 交叉校验
# 会自动跟着收窄 —— 加题只改这一处。自检模式（--gate/--seed-home）不受影响。
if [ -n "${CTF_IDS:-}" ]; then
  IFS=',' read -r -a IDS <<< "$CTF_IDS"
fi

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

# CTF_CONFIG_EXTRA：播种完隔离家后，把 config.yaml 符号链接实体化并追加
# 这段 YAML（多行字符串）。用途：A/B 实验里把**两侧共有**的环境变量（如
# 压缩阈值 compression.threshold_tokens）压到跑批可达范围 —— 两侧设同值
# 才是配对；只在 exp 侧设的开关走 TOGGLE_ENV。只在 config.yaml 是符号链接
# 时动手（播种产物），否则原样不动。
_apply_config_extra() {  # _apply_config_extra <家目录>
  local dst="$1"
  local cfg="$dst/config.yaml"   # 别和 dst 挤同一行 local —— bash 会先用后赋
  [ -n "${CTF_CONFIG_EXTRA:-}" ] || return 0
  if [ -L "$cfg" ]; then
    cp -L "$cfg" "$cfg.tmp" || return 1
    # 深合并而不是文本追加：真配置已有 compression: 等段，YAML 顶层同名键
    # 会整体覆盖，文本追加会把原有子键（proactive_prune_tokens 等）顶丢。
    CTF_CONFIG_EXTRA="$CTF_CONFIG_EXTRA" python3 - "$cfg.tmp" <<'PYEOF' || { rm -f "$cfg.tmp"; return 1; }
import os, sys, yaml
cfg_path = sys.argv[1]
extra = yaml.safe_load(os.environ["CTF_CONFIG_EXTRA"]) or {}
cfg = yaml.safe_load(open(cfg_path)) or {}
def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v
merge(cfg, extra)
with open(cfg_path, "w") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
PYEOF
    mv "$cfg.tmp" "$cfg" && echo "  [config-extra] 已合并覆盖到 $cfg: $CTF_CONFIG_EXTRA" | head -2
  else
    echo "  [config-extra] 警告: $cfg 不是符号链接，未修改" >&2
  fi
}

# `ctf_hard_run.sh --seed-home <目录>` → 只布一个隔离家并打印结论。
# 同样安排在**一切副作用之前**（`_seed_home` 已在上面定义好）。这不只是洁癖：
# 此刻 `$1` 是 `--seed-home`，真让 `mkdir -p "$OUT"` 跑下去，OUT 就是
# `--seed-home` —— 会在 cwd 里建出一个同名目录，并且在自检模式里顺手把你的
# 目标目录填进 logs/mirror/proof。
if [ "${1:-}" = "--seed-home" ]; then
  _seed_home "$2" || exit 1
  echo "SEED-OK $2"; exit 0
fi

if [ -z "$RUN_ROOT" ]; then
  RUN_ROOT="$(mktemp -d /tmp/ctf-runroot.XXXXXXXXXX)"
fi
LOGS="$RUN_ROOT/logs"
MIRROR="$RUN_ROOT/mirror"
PROOF="$RUN_ROOT/proof"
SEALED="$RUN_ROOT/sealed"     # 跑批期间的明文答案暂存区（跑完还原）
mkdir -p "$OUT" "$LOGS" "$MIRROR" "$PROOF" "$SEALED"

_real() { (cd "$1" 2>/dev/null && pwd -P) || echo "__missing__"; }

# ── 暂存：跑批期间不让明文答案留在盘上 ──────────────────────────────────
# 上一版的错误是"挪位置就完事"（logs/ 从 OUT 里挪到 RUN_ROOT）。位置不是
# 边界 —— agent 能 `find /tmp`，实测 `find /tmp -name '*.reference.log'`
# 直接命中**当前这道题**的明文答案。同用户同文件系统下，凡是跑批期间留在
# 盘上的东西它都读得到，挪到哪都一样。
#
# 所以判据从"放哪"改成"**在不在盘上**"：
#   · 参考解输出、参考解源码 —— 自证跑完立刻**删除**（它们只在自证那一瞬
#     需要存在）；
#   · 已跑完那题的 FLAG / solver.log / 镜像 —— 立刻收进 SEALED，等全部跑完
#     （agent 已退出）再还原回原布局，采集器与归档格式都不用改。
#
# **残余边界，写出来不假装关上了：** SEALED 里是 `.gz`，而 gzip 不是加密 ——
# 有能力的 agent 主动 `gunzip` 仍能读到。真关上要换用户/容器跑 agent，属于
# 本机同用户文件系统的固有性质。这里做到的是"顺手 grep 找不到、得刻意去解压"，
# 而且参考解源码与明文从不落盘。
_seal() {   # _seal <源文件> <暂存名>
  gzip -c "$1" > "$SEALED/$2.gz" || return 1
  rm -f "$1"
}
_unseal() { # _unseal <暂存名> <目标路径>
  [ -f "$SEALED/$1.gz" ] || return 0
  gunzip -c "$SEALED/$1.gz" > "$2"
}
# 整个 work_dir 一起收 —— 不能只收 FLAG。agent 自己写的 `ctf-notes.md` /
# `blackboard.json` 里就有明文 flag（实测：`- inflate + XOR → flag{...}`），
# 按文件名挑要收哪些是挑不干净的。目录级暂存是"全部收走"。
_seal_tree() {   # _seal_tree <目录> <暂存名>
  tar -czf "$SEALED/$2.tgz" -C "$(dirname "$1")" "$(basename "$1")" || return 1
  rm -rf "$1"
}
_unseal_tree() { # _unseal_tree <暂存名> <目标父目录>
  [ -f "$SEALED/$1.tgz" ] || return 0
  tar -xzf "$SEALED/$1.tgz" -C "$2"
}

# ── 不变量：跑批期间**真身**家目录的答案态不许被写 ──────────────────────
# FULILIAN_HOME 一旦没生效（被改名、被 profile 覆盖、某条代码路径没走
# `get_fulilian_home()`），泄漏就静默回来了 —— 而且是那种"跑完才发现结果已经
# 被污染"的失败。所以不靠"我读过源码，觉得它对"，而是**开跑前记指纹、跑完
# 比一次**。指纹只覆盖答案态那几处，不是整棵树（3.6G 扫不起，也没必要）。
_home_fp() {
  local p out=""
  for p in "$_RH/traces" "$_RH/learning.json" "$_RH/cache/terminal-output"; do
    if [ -e "$p" ]; then
      out="$out$(find "$p" -type f -printf '%p %T@ %s\n' 2>/dev/null | sort | sha256sum | cut -c1-16)  $p"$'\n'
    else
      out="$out""MISSING  $p"$'\n'
    fi
  done
  printf '%s' "$out"
}

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

# 产品家目录里的历史答案：**现在不影响本轮**（下面每题都换 FULILIAN_HOME），
# 但它仍是"上一跑写、这一跑读"的来源，属用户的真实数据，跑批器不擅自删 ——
# 报出来，让"要不要清"由用户决定。
if [ -d "$_RH" ]; then
  _hstale="$(grep -rlF -e 'flag{' "$_RH/traces" "$_RH/learning.json" \
             "$_RH/cache/terminal-output" 2>/dev/null | head -5)"
  if [ -n "$_hstale" ]; then
    echo "  ℹ️  家目录 $_RH 里有历史 flag（已被本轮 FULILIAN_HOME 隔离，读不到）："
    echo "$_hstale" | sed 's/^/      /'
    echo "      → 它不受 /tmp 的隔离影响，属长期残留；要不要清由你定。"
  else
    echo "  ✅ 家目录答案态里未见历史 flag"
  fi
fi

# **跑批器关不掉的一层：编排者自己的会话记录。** agent 与编排者同用户，
# 所以 `~/.claude/projects/*.jsonl`（对话记录）与 `file-history/` 它一样读得到。
# 只要编排过程里有人**把明文 flag 打到过工具输出**，答案就在那儿 —— 而且每打
# 一次就新写一份。跑批器不删用户的对话记录（那是审计线索，删了更糟），只能报。
# 判据用"有没有 flag{ 字样"，粗但够用：宁可误报也不静默。
_orch="$(grep -rlF 'flag{' "$HOME/.claude/projects" "$HOME/.claude/file-history" \
          2>/dev/null | head -5)"
if [ -n "$_orch" ]; then
  echo "  ⚠️  编排者的会话记录里有 flag 字样（agent 同用户，读得到）："
  echo "$_orch" | sed 's/^/      /'
  echo "      → 跑批时别再把明文 flag 打到工具输出；本轮若结果异常好，先查这个。"
fi

rm -rf "$LOGS" "$MIRROR" "$PROOF"; mkdir -p "$LOGS" "$MIRROR" "$PROOF"
_FP_BEFORE="$(_home_fp)"

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

  # 自证通过了 —— 这两样此刻就成了最该消失的东西：
  #   $LOGS/$id.reference.log  参考解的 stdout，**当前这道题的明文 flag**
  #   $p/ ($PROOF)             参考解源码 + 语料副本 = 答案的说明书
  # 自证的全部价值是"确认 fixture 不是坏的"，那一瞬已经兑现。留着它，只是把
  # **当前正在解的这道题**的答案摆在 solve 期间能被 `find /tmp` 扫到的位置。
  # 只留 sha256 供事后对账 —— 哈希进不了答案。
  _pf="$LOGS/$id.reference.log"
  _pn="$(wc -c < "$_pf")"; _ph="$(sha256sum "$_pf" | cut -c1-8)"
  rm -f "$_pf"; rm -rf "$p"
  echo "=== [$id] $(date +%H:%M:%S) SELFPROOF-OK 输出 ${_pn}B sha256:${_ph}（输出与参考解源码已删除）==="

  # solve 前硬闸。边界传 $OUT（往上溯到 OUT 为止）；老版只传一个参数，
  # 而 _gate 在 --gate 自检改造后是双参签名，set -u 下直接崩 —— 隔离测试
  # 只走 --gate 双参路径，抓不住主循环这个调用点（"测试全绿 ≠ 接上了线"）。
  if ! leak="$(_gate "$d" "$OUT")"; then
    echo "!!! [$id] work_dir 或其祖先链上混进了答案，会污染基线 —— 中止"
    echo "$leak"
    exit 1
  fi

  # 运行日志镜像到 solve 目录之外。work_dir 是 agent 的地盘：实测它用
  # write_file 把 solver.log 覆盖成过一份解题报告（misc-chunkconcat-01），
  # 那一跑的工具面数据全丢，0 被读成了"高效"。镜像只增不改，与 work_dir
  # 内那份并存 —— stopper 的增量扫描、replay/writeup 都不受影响。
  # 每题一个**自己的家**：这样连"同一批里前一道题的 trace"都读不到，
  # 不必只依赖跑完再封存（封存是兜底，隔离在家目录这一层就成立了）。
  FHOME="$RUN_ROOT/home/$id"
  _seed_home "$FHOME"
  _apply_config_extra "$FHOME"

  echo "=== [$id] $(date +%H:%M:%S) 开始 solve ==="
  ( cd "$d" && FULILIAN_HOME="$FHOME" \
      FULILIAN_SOLVER_LOG_MIRROR="$MIRROR/$id.solver.log" \
      timeout 3600 "$HOME/.local/bin/fulilian" solve "$d" -p ) \
      > "$LOGS/$id.log" 2>&1
  rc=$?

  # **不要在这里打印明文 flag。** 老版这一行是
  #     flag=$(cat "$d/FLAG")
  # 而跑批器的 stdout 会被重定向到 /tmp 的日志文件（`> /tmp/ctf-n3.log`）——
  # 那是**同批里后跑的题、以及后续每一批**都能直接读到的位置。实测五个历史
  # 批日志里共 34 处明文 flag，全部来自这一行。改打印 sha256 前 8 位：
  # 人工对账（与 manifest 的 expected_flag 比对）照样做得了，答案不在盘上。
  if [ -f "$d/FLAG" ]; then
    _fn="$(wc -c < "$d/FLAG")"; _fh="$(sha256sum "$d/FLAG" | cut -c1-8)"
    echo "=== [$id] $(date +%H:%M:%S) 结束 rc=$rc FLAG=已写 ${_fn}B sha256:${_fh} ==="
  else
    echo "=== [$id] $(date +%H:%M:%S) 结束 rc=$rc FLAG=未写 ==="
  fi

  # 整棵 work_dir 收走（含 agent 自己写的 notes/blackboard，里面就是明文
  # flag），再加上 runner 的 solve stdout 与镜像 —— 三处都明文含答案。
  # 不收走的话，同批后跑的题 `grep -r flag /tmp` 就能读到前一题的答案，
  # 与"_selfproof 在隔壁"同一类问题，只是换了文件名。全部跑完再还原。
  _seal_tree "$d"                  "$id.workdir"           || { echo "!!! [$id] work_dir 暂存失败"; exit 1; }
  # 这个家目录里已经有本题的 trace / learning（明文 flag）。**symlink 不跟进去**：
  # tar 默认按符号链接存，不会把真身那 3.6G 拖进来。
  _seal_tree "$FHOME"              "$id.fhome"             || { echo "!!! [$id] 家目录暂存失败"; exit 1; }
  [ -f "$LOGS/$id.log" ] && { _seal "$LOGS/$id.log" "$id.runner.log" \
        || { echo "!!! [$id] runner 日志暂存失败"; exit 1; }; }
  [ -f "$MIRROR/$id.solver.log" ] && { _seal "$MIRROR/$id.solver.log" "$id.mirror.solver.log" \
        || { echo "!!! [$id] 镜像日志暂存失败"; exit 1; }; }
done

echo "ALL DONE $(date +%H:%M:%S)  RUN_ROOT=$RUN_ROOT"

# ── 全部跑完（agent 已退出）才还原明文 ─────────────────────────────────
# 采集器按 `work_dir/FLAG`、`work_dir/usage.json`、`<mirror>/<id>.solver.log`
# 的约定读数，归档格式也照旧；这里还原**就是为了不改它们**。还原发生在没有
# agent 在跑的窗口里，所以不再构成泄漏。
_restored=0
for id in "${IDS[@]}"; do
  _unseal_tree "$id.workdir" "$OUT"
  _unseal_tree "$id.fhome"   "$RUN_ROOT/home"
  _unseal "$id.runner.log"        "$LOGS/$id.log"
  _unseal "$id.mirror.solver.log" "$MIRROR/$id.solver.log"
  [ -d "$OUT/$id" ] && _restored=$((_restored+1))
done
echo "明文已还原 ${_restored}/${#IDS[@]} 题（跑批期间不在盘上）"
if [ "$_restored" -ne "${#IDS[@]}" ]; then
  echo "!!! 有 work_dir 没能还原 —— 归档会缺题，中止"
  exit 1
fi
# 暂存区已还原完毕，留着只会让上层归档（n3 驱动器 tar 的是整个 RUN_ROOT）
# 多带一份含答案的压缩副本，白占体积。
rm -rf "$SEALED"

# ── 比指纹：真身的答案态没被动过，FULILIAN_HOME 才算真的生效了 ──────────
# 动了就说明围堵在这条路径上漏了 —— 本轮结果**已经被污染**，但跑都跑完了，
# 唯一能做的是别让它冒充干净数据。所以大声报出来、并显式打折。
_FP_AFTER="$(_home_fp)"
if [ "$_FP_BEFORE" = "$_FP_AFTER" ]; then
  echo "✅ 真身家目录答案态未被写入 —— FULILIAN_HOME 隔离生效"
else
  echo "!!! 真身家目录的答案态在跑批期间**被写了** —— FULILIAN_HOME 没兜住："
  diff <(printf '%s\n' "$_FP_BEFORE") <(printf '%s\n' "$_FP_AFTER") | sed 's/^/      /'
  echo "      后果：本轮 agent 读得到别的跑次留下的答案，ref_multiple / solve 率都要打折。"
  echo "      先查 fulilian 是否仍按 get_fulilian_home() 解析这些路径，再谈难度结论。"
fi

# 采集命令从 IDS 生成，不硬编码 —— 初版把三个 id 写死在这里，
# 加第四题时就会静默漏采（跑批说做了四题，采集只报三题）。
dirs=""
for id in "${IDS[@]}"; do dirs="$dirs $OUT/$id"; done
echo "采集： python $REPO/benchmarks/ctf_path_baseline.py \\"
echo "         --dirs$dirs \\"
echo "         --mirror-dir $MIRROR \\"
echo "         --manifest $REPO/benchmarks/manifest-ctf-hard.yaml"
