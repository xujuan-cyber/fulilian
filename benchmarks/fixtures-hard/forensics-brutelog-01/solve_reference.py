"""solve_reference — forensics-brutelog-01 参考解（fixture 自证）。

正确流程（5 步）：
  1. 看体积 —— 3.3 MB，**不能整读**（读工具在 20,000 字节处截断）。
  2. 抽 `Accepted` 行 —— 9,004 条。**这一步几乎没用**，因为内网的
     日常运维登录也是 `Accepted`。
  3. 按**来源网段**过滤：只保留源地址不在 `10.0.0.0/8` 的 →
     恰好 1 条，来自 `203.0.113.77`。
     （诱饵在此处会失败：`203.0.113.99` 失败 18,000 次却从不成功；
     若按"失败最多"选人，会选中它然后一无所获。）
  4. 按**被攻陷的账号** pivot（不是按 IP）→ 一条
     `sudo ... curl ...?token=<base64url>`。
  5. URL-safe base64 解码 → flag。

第 3 步是考点：它要求把"登录成功"与"来源可信"两个维度**分开判断**。
第 1 步是工具纪律（与 misc-bigscan-01 同源），第 5 步要求意识到
`token=` 是个不透明编码串而不是字面量。

**第 4 步按账号而不是按 IP pivot 是有原因的**：那条 `sudo` 行里只有
用户名（`svc_backup`），**不含攻击者 IP** —— `sudo` 记录的是"谁在本机
执行了什么"，来源地址留在 sshd 那层。初版参考解写成"取该 IP 后续的活动"，
于是匹配到 0 行。真实取证里这个 pivot 也是按账号做的。
"""

SOLUTION_STEPS = 5

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solve_reference_common import find_flag  # noqa: E402

_RE_ACCEPTED = re.compile(r"^(\S+ +\d+ \d\d:\d\d:\d\d) .*Accepted \w+ for (\S+) from (\S+) ")
_RE_TOKEN = re.compile(r"token=([A-Za-z0-9_\-]+)")


def _is_internal(ip: str) -> bool:
    return ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172.")


def solve(work_dir: str) -> str:
    log = Path(work_dir) / "auth.log"
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    out = [f"$ wc -c auth.log\n{log.stat().st_size:,} bytes（整读会被 20000 字节截断）"]

    # 第 2 步：Accepted 有 9,004 条 —— 单看这一步得到不了任何结论。
    accepted = [(_RE_ACCEPTED.match(ln), ln) for ln in lines]
    accepted = [(m, ln) for m, ln in accepted if m]
    out.append(f"$ grep -c 'Accepted ' auth.log\n{len(accepted)} 条（内网日常登录混在里面，"
               f"这一步不够）")

    # 第 3 步：按来源网段过滤 —— 这一步才是决定性的。
    external = [(m, ln) for m, ln in accepted if not _is_internal(m.group(3))]
    out.append(f"$ grep 'Accepted ' auth.log | grep -v ' from 10\\.'\n"
               f"{len(external)} 条 ← 唯一的突破口")
    if len(external) != 1:
        raise SystemExit(f"参考解预期恰好 1 条外网 Accepted，实际 {len(external)} 条")

    m, ln = external[0]
    attacker, account, when = m.group(3), m.group(2), m.group(1)
    out.append(f"攻击者: {attacker}（{when} 成功登录，账号 {account}）")

    # 第 4 步：按**账号** pivot。按 IP 匹配会得到 0 行 —— sudo 日志里
    # 只有用户名，没有来源地址。
    after = [l for l in lines if l > when and account in l]
    out.append(f"$ grep '{account}' auth.log | awk '... > \"{when}\"'\n"
               f"账号后续活动 {len(after)} 行")

    for l in after:
        tm = _RE_TOKEN.search(l)
        if not tm:
            continue
        raw = tm.group(1)
        # 第 5 步：URL-safe base64。补齐 padding 再解 —— 生成器写日志时
        # 去掉了 '='，直接 b64decode 会因长度不是 4 的倍数而报错。
        padded = raw + "=" * (-len(raw) % 4)
        text = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        out.append(f"$ echo {raw} | base64 -d  # urlsafe, 补 padding\n{text}")
        return "\n".join(out) + "\n" + find_flag(text)

    raise SystemExit("参考解没找到 token —— 生成器与参考解不一致")
