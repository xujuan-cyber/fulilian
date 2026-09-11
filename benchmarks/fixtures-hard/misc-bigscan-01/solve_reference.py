"""solve_reference — misc-bigscan-01 参考解（fixture 自证）。

正确流程（4 步，每一步都不可省）：
  1. 意识到 scan.log 有约 4 MB，**不能整读**（读工具在 20,000 字节处截断，
     目标在 65% 深度 —— 整读必丢）。必须走过滤。
  2. 按端口 8443 收敛 —— 15,000 台收到 **36 台**（目标 + 35 台诱饵）。
     这一步不够：端口不是答案。
  3. 在 36 台里按**服务属性** `http-backup` 收敛到唯一一台 —— 诱饵只有
     `|_http-title:`，没有备份目录列表。这一步才是关键。
  4. 取 `[blob]` 的 base64 解码得到 `flag{...}`。

第 1 步是本题真正的考点：**它是"工具输出纪律"题，不是"网络安全"题**。
一个不分块、直接 read_file 的 solver 会稳定失败，且失败原因是工具层截断
而不是推理错误 —— 这正是 P0.1（工具输出落盘）要修的病灶。
"""

SOLUTION_STEPS = 4

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solve_reference_common import find_flag  # noqa: E402

_BACKUP = re.compile(r"\|\s*http-backup:.*?\[\s*([A-Za-z0-9+/=]{8,})\s*\]", re.M)


def solve(work_dir: str) -> str:
    log = Path(work_dir) / "scan.log"
    raw = log.read_text(encoding="utf-8", errors="replace")
    out = [f"$ wc -c scan.log\n{len(raw.encode()):,} bytes（整读会被 20000 字节截断）"]

    # 第 2 步：按端口收敛。**故意先在回答里呈现这一步的不足** —— 36 台不是答案。
    hosts = re.split(r"(?=^Nmap scan report for )", raw, flags=re.M)
    port_hits = [h for h in hosts if "8443/tcp" in h]
    out.append(f"$ grep -c '8443/tcp' scan.log\n{len(port_hits)} 台（含诱饵，端口不是答案）")

    # 第 3 步：在候选里按服务属性收敛到唯一一台。
    m = _BACKUP.search(raw)
    if not m:
        raise SystemExit("参考解没找到 http-backup 行 —— 生成器与参考解不一致")

    blob = m.group(1)
    decoded = base64.b64decode(blob, validate=True).decode("utf-8")

    ctx = raw[max(0, m.start() - 2000): m.start()]
    ip = re.findall(r"Nmap scan report for (\S+)", ctx)
    out.append(f"$ grep -A3 'http-backup' scan.log\n唯一命中主机 {ip[-1] if ip else '?'}")
    out.append(f"$ echo {blob} | base64 -d\n{decoded}")
    return "\n".join(out) + "\n" + find_flag(decoded)
