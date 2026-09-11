"""solve_reference — misc-chunkconcat-01 的参考解（跑批前自证用）。

演示**最少步骤**的正确解法，同时它就是本题的预期路径：

  整读 transfer.log（2.9 MB）必然被 20,000 字节截断，而答案不在任何
  单独一行里 —— 所以「找到那一行」这个思路本身就是错的。正确做法是
  先过滤落盘，再离线处理。这正是 P0.1（工具输出落盘）想让它变成
  默认行为的那条路径。

SOLUTION_STEPS 是难度代理指标，也是验收时的分母：solver 的 api_calls
若数倍于它，即使解出也说明路径不经济（见 manifest-ctf-hard.yaml 头部）。
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solve_reference_common import find_flag  # noqa: E402

SOLUTION_STEPS = 5
TARGET_CHAN = "07"
_RE_OFF = re.compile(r"off=(\d+)")
_RE_DATA = re.compile(r"data=(\S+)")


def solve(work_dir: str) -> str:
    work = Path(work_dir)
    log = work / "transfer.log"

    # 步骤 1：过滤落盘。不整读 —— 2.9 MB 会被截断，而截掉的部分里
    # 恰恰是你拼出答案所需要的原料（这比"答案被截掉"更隐蔽）。
    chunks_file = work / "_chan07.txt"
    with chunks_file.open("w", encoding="utf-8") as fh:
        subprocess.run(["grep", f"chan={TARGET_CHAN} ", str(log)],
                       stdout=fh, check=False)
    lines = chunks_file.read_text(encoding="utf-8").splitlines()
    print(f"步骤 1: 过滤落盘 {len(lines)} 块（过滤输出本身就已超截断线）")

    # 步骤 2：按 off 排序。块按网络到达顺序写入，是乱的。
    # 按出现顺序拼会得到一个能过 base64、但内容是乱码的串 —— 有反馈、没答案。
    ordered = sorted(lines, key=lambda l: int(_RE_OFF.search(l).group(1)))
    print(f"步骤 2: 按 off 排序 {_RE_OFF.search(ordered[0]).group(1)}"
          f" → {_RE_OFF.search(ordered[-1]).group(1)}")

    # 步骤 3：拼接
    joined = "".join(_RE_DATA.search(l).group(1) for l in ordered)
    print(f"步骤 3: 拼接 {len(joined):,} 字符")

    # 步骤 4：解码
    payload = base64.b64decode(joined)
    print(f"步骤 4: base64 解码 → {len(payload):,} 字节")

    # 步骤 5：在还原出的 payload 里找 flag
    flag = find_flag(payload.decode("utf-8", errors="replace"))
    print(f"步骤 5: {flag}")
    return flag


if __name__ == "__main__":
    print(solve(sys.argv[1] if len(sys.argv) > 1 else "."))
