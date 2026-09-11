"""make_data — misc-chunkconcat-01 数据生成器（确定性，seed 固定）。

与 misc-bigscan-01 是**不同的靶子**，不重复：

  bigscan   —— "能用一次 grep 命中，就别去整读"（实测 solver 做到了：shell:read = 17:2）
  chunkconcat —— "一次 grep 命中不了，必须处理完整个大输出"

bigscan 里 `grep http-backup` 一行就是答案，所以 P0.1（工具输出落盘）那条路径
**从未真正被压到**。本题把这条路堵死：答案被切成 1,140 块散在 4 万行日志里，
单次过滤输出的**规模本身就超限**，必须落盘再处理。

语料设计（五件事同时成立）：

1. **过滤输出的规模超限** —— `grep 'chan=07'` 得到 1,140 行 ≈ 97 KB，
   而工具在 20,000 字节处截断且不带指针。**答案不在被截掉的部分里，
   但解出答案所需的全部数据在那里** —— 这比 bigscan 更狠：bigscan 是
   "答案被截掉"，本题是"原料被截掉，你甚至不知道切掉了什么"。
2. **单次 grep 拿不到答案** —— data 是文件流的**分块**，必须全部拼接再解码。
   任何"找到那一行"的直觉在这里失效。
3. **块是乱序的** —— 全局 shuffle 后再按位置分配时间戳（时间戳递增、内容乱序），
   模拟网络层重组。参考解必须**按 `off=` 排序**，不能按出现顺序拼接。
   按出现顺序拼会得到一个能解出 base64、但内容是乱码的字节串 —— 有反馈、没答案。
4. **诱饵通道** —— 另有 19 个 chan 各自也在传数据，同样是 base64。混入任何
   一块，解码就失败。`grep data=` 会得到 4 万行。
5. **语料里没有关键字** —— payload 整体 base64 过，日志里 "flag" 出现 0 次，
   所以关键字 grep 无效（与 bigscan 同一条纪律，用断言锁住）。

**本题考的是「大输出纪律」，不是推理** —— 与 bigscan 同类，但压的是同一条
路径上**更硬的那一段**：bigscan 可以用一次巧妙的 grep 回避落盘，本题不行。
参考解必须落盘。这是 P0.1 更严格的探针。

诚实说明：真实分块传输不会用固定 24 字节，这里固定是为了确定性可复现 ——
holdout 的可复现性优先于拟真度，因为要用它做前后对照。
"""

from __future__ import annotations

import base64
import random
from pathlib import Path

FLAG = "flag{reassemble_by_seq_not_by_arrival}"

# 目标通道（文件流）与诱饵通道。用 07 而非 7，让 `chan=7` 这种写法也漏 ——
# 格式一致性本身就是一处小的严谨性检查。
TARGET_CHAN = "07"
DECOY_CHANS = [f"{c:02d}" for c in range(1, 21) if f"{c:02d}" != TARGET_CHAN]

CHUNK = 24                 # 每块的 base64 字符数（24 是 4 的倍数，可独立解码）
DECOY_CHUNKS_PER_CHAN = 2000   # 19 个诱饵通道 × 2000 ≈ 38,000 行

_BASE_TIME = "2026-09-11T02:14:33"


def _build_payload(rng: random.Random) -> bytes:
    """被分块传输的那份文件 —— 一段伪造的凭据导出，规模约 20 KB。

    flag 放在约 60% 深度，与 bigscan 的"别在头尾"纪律一致。
    """
    lines = [
        "# vault export (internal use only)",
        f"# generated 2026-09-11T02:10:00Z by vault-sync/2.4.1",
        "",
    ]
    n_cred = 420
    for i in range(n_cred):
        lines.append(f"credential/{i:05d} = {rng.getrandbits(48):012x}")
    lines.append("")

    # flag 落在 payload 约 60% 处
    split_at = int(n_cred * 0.6)
    head, tail = lines[:split_at + 3], lines[split_at + 3:]
    mid = [
        "# ---- recovery material ----",
        f"recovery/token = {FLAG}",
        "# ---- end recovery material ----",
        "",
    ]
    lines = head + mid + tail

    for i in range(120):
        lines.append(f"note/{i:03d} = " + "lorem ipsum dolor sit amet " * 3)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_log() -> str:
    rng = random.Random(20260912)
    payload = _build_payload(rng)
    b64 = base64.b64encode(payload).decode("ascii")

    # 目标通道：把整个 base64 流切成 CHUNK 字符一块，off 记录它在流中的偏移。
    records: list[tuple[str, int, str]] = []
    for off in range(0, len(b64), CHUNK):
        records.append((TARGET_CHAN, off, b64[off:off + CHUNK]))

    # 诱饵通道：等量随机 base64，长度与目标块一致，肉眼不可分。
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    for chan in DECOY_CHANS:
        for i in range(DECOY_CHUNKS_PER_CHAN):
            off = i * CHUNK
            records.append((chan, off, "".join(rng.choice(alphabet)
                                               for _ in range(CHUNK))))

    # 全局打乱 —— 这是本题的第二个题眼：块是按网络到达顺序写的，
    # 不是按流内偏移写的。再按位置赋时间戳，让时间戳仍是单调递增的。
    rng.shuffle(records)

    out: list[str] = [
        "# transfer-svc session log — channelized capture",
        f"# channels: {len(DECOY_CHANS) + 1}, records: {len(records)}",
        "",
    ]
    t_us = 0
    for chan, off, data in records:
        t_us += rng.randint(1000, 50000)
        sec, us = divmod(t_us, 1_000_000)
        ts = f"{_BASE_TIME}.{us:06d}Z" if sec == 0 else f"{_BASE_TIME}Z+{sec}s"
        out.append(f"{ts} chan={chan} off={off:06d} data={data}")
    return "\n".join(out) + "\n"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="生成 misc-chunkconcat-01 的 transfer.log")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent,
                    help="输出目录（默认 fixture 目录；runner 传 work_dir）")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    data = _build_log()
    (args.out / "transfer.log").write_text(data, encoding="utf-8")

    raw = data.encode("utf-8")

    # 自检 1：语料里不许出现 flag 字面（关键字 grep 必须无效）
    lit = raw.lower().count(b"flag")
    assert lit == 0, f"日志里出现 {lit} 次字面 'flag' —— 难度归零"

    # 自检 2：目标通道的过滤输出必须**超过工具截断阈值**，否则本题
    # 与 bigscan 就没区别了（那题的教训是"必须真的压到那条路径"）。
    tgt = [l for l in data.splitlines() if f"chan={TARGET_CHAN} " in l]
    tgt_bytes = len("\n".join(tgt).encode("utf-8"))
    assert tgt_bytes > 20_000, (
        f"chan={TARGET_CHAN} 过滤输出仅 {tgt_bytes:,} 字节，未超 20,000 截断线 —— "
        "本题会退化成 bigscan，失去探针意义"
    )

    # 自检 3：拼接后必须真能还原出含 flag 的 payload（否则参考解无解）
    import re
    ordered = sorted(tgt, key=lambda l: int(re.search(r"off=(\d+)", l).group(1)))
    joined = "".join(l.split("data=", 1)[1] for l in ordered)
    recovered = base64.b64decode(joined)
    assert FLAG.encode() in recovered, "拼接解码后找不到 flag —— 生成器自己错了"

    # 自检 4：乱序是真实的 —— 按出现顺序拼必须**拼不出** flag，
    # 否则本题的第二个题眼（必须按 off 排序）就是假的。
    naive = "".join(l.split("data=", 1)[1] for l in tgt)
    try:
        naive_ok = FLAG.encode() in base64.b64decode(naive)
    except Exception:
        naive_ok = False
    assert not naive_ok, "按出现顺序也能拼出 flag —— '乱序' 这层难度是假的"

    print(f"transfer.log: {len(raw):,} bytes, {data.count(chr(10)):,} 行")
    print(f"chan={TARGET_CHAN} 块数: {len(tgt)}，过滤输出 {tgt_bytes:,} 字节 "
          f"（截断线 20,000，超 {tgt_bytes / 20_000:.1f}×）")
    print(f"还原出的 payload: {len(recovered):,} 字节")
    print(f'自检 ✓ "flag" 字面 {lit} 次；按 off 排序可解、按出现顺序不可解')


if __name__ == "__main__":
    main()
