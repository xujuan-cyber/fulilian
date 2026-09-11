"""make_data — forensics-brutelog-01 数据生成器（确定性，seed 固定）。

语料：`auth.log`（约 3 MB / 12 万行 sshd 风格日志）。

**难度在"选对人"，不在"解密码"。** 正确路径只有一条：
  从 4 条 `Accepted` 里认出**唯一来自外网**的那条 → 拿到 IP →
  在该 IP 之后的活动里找到它拉取的备份 → URL 解码 → flag。

为什么这不容易 —— 三层诱饵，每一层都对应一种**会导致错误结论的朴素启发式**：

1. **"失败次数最多的 IP 就是攻击者"** → 错。`203.0.113.99` 失败 18,000 次，
   但它从未成功过（纯噪音源，可能是被入侵的肉鸡或蜜罐探针）。
2. **"第一条 Accepted 就是突破口"** → 错。日志里 `Accepted` 共 **9,004 条**，
   绝大多数是内网 `10.0.x` 的日常运维登录（9003 条）。
   真正的那一条藏在里面。
3. **"有 Accepted 就是攻击者"** → 错，而且这一层最狠：内网那 9,003 条
   同样是 `Accepted`。区分它们的唯一依据是**来源地址落在内网段之外**。
   所以正确做法不是"搜 Accepted"，而是"搜 Accepted 然后按来源网段过滤"。

第 3 层是本题的考点：它要求把"成功登录"与"来源是否可信"**两个维度
分开看**，现有 easy 语料里没有任何一题需要这种交叉判断。

**flag 不可被关键字搜到** —— 它以 **URL-safe base64** 的形式出现在
`token=` 参数里。初版这里用的是 `urllib.parse.quote`，那是错的：
percent-encoding 只转义 `{`/`}` 等符号，**字母原样保留**，所以
`flag` 这个子串会直接留在日志里，`grep flag` 一击命中，难度归零。
是生成器末尾那行自检（打印 `"flag" 字面出现次数`）把它抓出来的。

诚实说明两处简化：日志时间戳是生成的、不连续；`203.0.113.0/24` 是
RFC 5737 保留的文档网段，不指向任何真实主机。
"""

from __future__ import annotations

import base64
import random
from datetime import datetime, timedelta
from pathlib import Path

FLAG = "flag{pivot_from_the_only_external_accept}"

# 攻击者与两个诱饵。113.0.0.0/24 是 RFC 5737 文档网段。
ATTACKER_IP = "203.0.113.77"
NOISY_IP = "203.0.113.99"          # 诱饵 1：失败最多，但从没成功过
INTERNAL_IPS = ["10.0.4.12", "10.0.9.31", "10.0.9.58"]

# 诱饵 2：内网的正常登录用户。它们也产生 Accepted 行。
_INTERNAL_USERS = ["ops", "deploy", "root"]
ATTACK_USER = "svc_backup"

# 攻击者的爆破字典 —— 数量刻意**远少于** NOISY_IP，让"失败次数"这条
# 启发式指向错误的人。
_ATTACKER_PASSWORDS = [
    "password", "123456", "admin", "root", "letmein",
    "svc_backup", "P@ssw0rd", "welcome",
]
_ATTACKER_FAIL_COUNT = 240         # vs NOISY_IP 的 ~18000

_HOSTS = [f"web{i:02d}" for i in range(1, 13)] + [f"db{i:02d}" for i in range(1, 5)]


def _ts(base: datetime, offset_s: float) -> str:
    t = base + timedelta(seconds=offset_s)
    return t.strftime("%b %d %H:%M:%S")


def _build_log() -> str:
    rng = random.Random(20260913)
    base = datetime(2026, 9, 11, 2, 0, 0)
    lines: list[str] = []

    def emit(offset: float, msg: str) -> None:
        lines.append(f"{_ts(base, offset)} {rng.choice(_HOSTS)} sshd["
                     f"{rng.randrange(1000, 99999)}]: {msg}")

    # ── 诱饵 1：高频失败源，从不成功 ─────────────────────────────────
    # 时间上铺满整个窗口，使它成为"最显眼"的 IP。
    for i in range(18000):
        emit(rng.uniform(0, 7000),
             f"Failed password for invalid user admin{i % 97} from {NOISY_IP} "
             f"port {rng.randrange(30000, 65000)} ssh2")

    # ── 内网正常登录（诱饵 2）：也是 Accepted，但来源在内网段 ────────
    internal_logins = [
        (600.0, "10.0.4.12", "ops"),
        (1500.0, "10.0.9.31", "deploy"),
        (4200.0, "10.0.9.58", "root"),
    ]
    for off, ip, user in internal_logins:
        emit(off, f"Accepted publickey for {user} from {ip} port "
                  f"{rng.randrange(30000, 65000)} ssh2: RSA SHA256:"
                  f"{rng.randrange(16**20):040x}")
        emit(off + 1.0, f"pam_unix(sshd:session): session opened for user {user} "
                        f"by (uid=0)")

    # ── 攻击者：240 次失败 → 第 241 次成功 ──────────────────────────
    # 起点刻意排在第二条内网登录之后、第三条之前，使"按时间顺序第一个
    # 可疑事件"这条启发式也落空。
    atk_start = 2600.0
    for i in range(_ATTACKER_FAIL_COUNT):
        emit(atk_start + i * 2.5,
             f"Failed password for {ATTACK_USER} from {ATTACKER_IP} port "
             f"{rng.randrange(40000, 60000)} ssh2")
    atk_success_off = atk_start + _ATTACKER_FAIL_COUNT * 2.5
    emit(atk_success_off,
         f"Accepted password for {ATTACK_USER} from {ATTACKER_IP} port "
         f"{rng.randrange(40000, 60000)} ssh2")
    emit(atk_success_off + 1.0,
         f"pam_unix(sshd:session): session opened for user {ATTACK_USER} by (uid=0)")

    # ── 攻击者得手后的活动：拉取备份（flag 在这里，URL-safe base64）──
    emit(atk_success_off + 30.0,
         f"pam_unix(sshd:session): session closed for user {ATTACK_USER}")
    # 用 base64 而不是 percent-encoding：后者不转义字母，`flag` 会原样留在
    # 日志里被 grep 到。urlsafe 变体（- 与 _）符合"URL 里的不透明 token"这一
    # 现实形态，且整串不含字面 "flag"。
    token = base64.urlsafe_b64encode(FLAG.encode()).decode().rstrip("=")
    emit(atk_success_off + 45.0,
         f'sudo: {ATTACK_USER} : TTY=pts/3 ; PWD=/var/backups ; USER=root ; '
         f'COMMAND=/usr/bin/curl -s "http://10.0.9.31:8080/restore?token={token}"')

    # 补一批内网日常噪音，把上面那行淹掉。
    for i in range(9000):
        ip = rng.choice(INTERNAL_IPS)
        emit(rng.uniform(0, 7000),
             f"Accepted publickey for {rng.choice(_INTERNAL_USERS)} from {ip} "
             f"port {rng.randrange(30000, 65000)} ssh2: RSA SHA256:"
             f"{rng.randrange(16**20):040x}")

    rng.shuffle(lines)

    # 乱序后按时间重排 —— 真实日志是时序的，混乱顺序会让"时间线推理"
    # 变成"字符串搜索"，把难度路径绕过去。
    def key(line: str) -> str:
        return line[:15]

    lines.sort(key=key)
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="生成 forensics-brutelog-01 的 auth.log")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = _build_log()
    (args.out / "auth.log").write_text(data, encoding="utf-8")

    raw = data.encode()
    print(f"auth.log: {len(raw):,} bytes, {data.count(chr(10)):,} 行")
    print(f"Accepted 行 {data.count('Accepted ')} 条"
          f"（外网来源 {data.count(f'from {ATTACKER_IP}')} 条）")
    print(f"失败最多的是 {NOISY_IP}（18000 次，从不成功）；"
          f"攻击者是 {ATTACKER_IP}（{_ATTACKER_FAIL_COUNT} 次后成功）")

    # 这几行是本题的**验收断言**，不是日志。任一不成立就说明 fixture 的
    # 难度设计被破坏了（例如某个 IP 被写成 10.0.x 会让第 3 层诱饵失效）。
    lit = raw.lower().count(b"flag")
    assert lit == 0, f"日志里出现了 {lit} 次字面 'flag' —— 难度归零，见 docstring"
    ext = data.count(f"from {ATTACKER_IP}") - data.count(
        f"Failed password for {ATTACK_USER} from {ATTACKER_IP}")
    assert ext == 1, f"外网 Accepted 应为 1 条，实际 {ext} 条"
    print(f'自检 ✓ "flag" 字面 0 次；外网 Accepted 恰好 1 条')


if __name__ == "__main__":
    main()
