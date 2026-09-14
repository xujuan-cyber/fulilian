"""solve_reference — web-tokenforge-01 参考解（自证：能真解出 flag）。

链条：policy 抄 scheme → 流量取 200 种子 → 旧 sig 解诱饵库识破假 flag →
纯 Python SHA-256 压缩函数 + 状态注入实现长度扩展（先用已知前缀对照
hashlib 验证实现保真度）→ 伪造 admin sig → 解 admin 层库拿 root 续签段 →
从 admin sig 注入链式续算 root 会话（跨块）→ 解 root 层库取真 flag。

SECRET 不在盘上（也不 import make_data）——参考解与 solver 吃同一份语料。
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solve_reference_common import find_flag  # noqa: E402

SOLUTION_STEPS = 11

_STEP_LINES = [
    "读 policy.md：sig = sha256(SECRET||msg)，SECRET 16 字节不在盘上；"
    "admin/root 两级门槛；三份库同一条 keystream = sha256(会话 sig 的 hex ASCII)；"
    "root 会话 = admin 会话原文末尾续写",
    "读 app.py：验证先比 sig 再查门槛，msg 原始字节整串参与哈希——"
    "门槛挡的是 msg 内容，不是 sig 生成方式",
    "读 traffic.log：取 alice 的 200 请求（msg=24 字节 + sig）作扩展种子；"
    "旧 admin 403 重放死路；未遂伪造那条给了要签的 admin msg 字符串",
    "用流量里现成的旧 admin sig 解 recovery.enc——得到一枚形似 flag 的字符串；"
    "同一 sig 解不开别的库，旧凭据是诱饵",
    "决策：唯一正路是 hash 长度扩展；hashlib 没有从中间状态续算的接口，"
    "自己实现 SHA-256 压缩函数",
    "实现保真度自检：用已知前缀跑 'hashlib 全量 == 状态注入续算'，"
    "不一致就修（padding/位长/压缩函数任一处错都会在这里响）",
    "第一次伪造：SECRET(16)+msg_alice(24)=40 字节，glue 24 字节恰好补满一块；"
    "把 alice 的 sig 拆成 8 个 32 位字注入状态，续算 admin 的 suffix",
    "用伪造 admin sig 的 keystream 解 vault.enc——admin 层没有 flag，"
    "只有 root 续签说明（ROOT_SUFFIX 行）",
    "第二次伪造（链式）：admin 会话原文 88 字节补齐到 128 字节块界——"
    "注入态已吸收 admin 消息自己的终 padding（glue2，40 字节）；"
    "从**自己伪造出的 admin sig** 注入状态续算 59 字节的 ROOT_SUFFIX，"
    "data+终 padding 恰好跨两个 64 字节块",
    "用 root 会话 sig 的 keystream 解 vault-root.enc",
    "取 root 层的 recovery phrase 即真 flag（recovery.enc 里那枚是假的，别交）",
]


# ── 纯 Python SHA-256（标准 FIPS 180-4 压缩函数，唯一可续算的实现路径）──
_K = [
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1,
    0x923F82A4, 0xAB1C5ED5, 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174, 0xE49B69C1, 0xEFBE4786,
    0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147,
    0x06CA6351, 0x14292967, 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B,
    0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A,
    0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
]
_IV = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
]


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def _compress(state: list[int], block: bytes) -> list[int]:
    w = list(struct.unpack(">16I", block))
    for i in range(16, 64):
        s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
        s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
        w.append((w[i - 16] + s0 + w[i - 7] + s1) & 0xFFFFFFFF)
    a, b, c, d, e, f, g, h = state
    for i in range(64):
        s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
        ch = (e & f) ^ (~e & g)
        t1 = (h + s1 + ch + _K[i] + w[i]) & 0xFFFFFFFF
        s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        t2 = (s0 + maj) & 0xFFFFFFFF
        h, g, f, e = g, f, e, (d + t1) & 0xFFFFFFFF
        d, c, b, a = c, b, a, (t1 + t2) & 0xFFFFFFFF
    return [(x + y) & 0xFFFFFFFF for x, y in zip(state, (a, b, c, d, e, f, g, h))]


def _md_padding(total_bytes: int) -> bytes:
    """一段 total_bytes 字节消息的终 MD padding；位长字段 = 补齐前总位长。"""
    pad = b"\x80" + b"\x00" * ((55 - total_bytes) % 64)
    return pad + (total_bytes * 8).to_bytes(8, "big")


def sha256_continue(state: list[int], absorbed_bytes: int, data: bytes) -> bytes:
    """从注入状态续算 data。

    state 必须是"已吸收 absorbed_bytes 字节消息（含 glue 块）"之后的链值；
    终 padding 的位长字段 = absorbed_bytes + len(data) 的总位长。
    """
    msg = data + _md_padding(absorbed_bytes + len(data))
    for i in range(0, len(msg), 64):
        state = _compress(state, msg[i:i + 64])
    return b"".join(struct.pack(">I", w) for w in state)


def _print_steps() -> None:
    for i, s in enumerate(_STEP_LINES, 1):
        print(f"step {i}: {s}")


def solve(work_dir: str) -> str:
    work = Path(work_dir)
    policy = (work / "policy.md").read_text(encoding="utf-8")
    log = (work / "traffic.log").read_text(encoding="utf-8")

    _print_steps()

    # 1-2) 抄 scheme（SECRET 长度、门槛、keystream 公式都在 policy 里）
    assert "sha256( SECRET || msg )" in policy
    secret_len = int(next(l for l in policy.splitlines() if "16 字节" in l)
                     .split("**")[1].split()[0])
    ts_floor = int(re.search(r"ts >= (\d+)", policy).group(1))
    assert secret_len == 16 and ts_floor == 1789000000

    # 3) 取 200 种子（alice 请求）；旧 admin 是 403，只作诱饵素材；
    #    未遂伪造那条给了要签的 admin msg 字符串（ts 过门槛，sig 是假的）
    seed = next(l for l in log.splitlines() if "user=alice" in l)
    msg_alice = seed.split("/api/token?", 1)[1].split("&sig=", 1)[0]
    sig_alice = bytes.fromhex(seed.rsplit("sig=", 1)[1].split(" ", 1)[0])
    assert len(msg_alice) == 24 and len(sig_alice) == 32
    attempt = next(l for l in log.splitlines()
                   if "user=admin" in l and str(ts_floor) in l)
    admin_msg = attempt.split("/api/token?", 1)[1].split("&sig=", 1)[0]
    assert admin_msg.startswith("user=admin&ts=")

    # 4) 诱饵库：旧 admin sig 解得开 recovery.enc（貌似成功）
    old_admin = next(l for l in log.splitlines()
                     if "user=admin" in l and str(ts_floor) not in l)
    sig_old = bytes.fromhex(old_admin.rsplit("sig=", 1)[1].split(" ", 1)[0])

    def unxor(data: bytes, sig_hex: str) -> bytes:
        ks = hashlib.sha256(sig_hex.encode("ascii")).digest()
        return bytes(b ^ ks[i % len(ks)] for i, b in enumerate(data))

    vault = (work / "vault.enc").read_bytes()
    vault_root = (work / "vault-root.enc").read_bytes()
    recovery = (work / "recovery.enc").read_bytes()
    bait = unxor(recovery, sig_old.hex())
    assert b"recovery phrase: " in bait, "旧 sig 应完整解开诱饵库"
    assert b"flag{" not in unxor(vault, sig_old.hex()), "旧 sig 解不开 admin 层"

    # 6) 实现保真度自检：已知前缀下，状态注入续算必须等于 hashlib 全量
    probe_prefix = b"known-prefix-" * 3          # 39 字节，普通非对齐长度
    probe_suffix = b"user=probe&ts=123"
    glue_probe = _md_padding(len(probe_prefix))  # 前缀自己的 MD padding = glue
    state0 = list(struct.unpack(">8I", hashlib.sha256(probe_prefix).digest()))
    # 注意：H(prefix) 的终块就是 prefix||glue——注入态已含 glue 的吸收
    forged_probe = sha256_continue(state0, len(probe_prefix) + len(glue_probe),
                                   probe_suffix)
    expect_probe = hashlib.sha256(probe_prefix + glue_probe + probe_suffix).digest()
    assert forged_probe == expect_probe, "SHA-256 续算实现不保真"

    # 7) 第一次伪造：alice sig 注入，续算 admin suffix（40+24 字节，一块内）
    glue1 = _md_padding(secret_len + len(msg_alice))
    assert (secret_len + len(msg_alice) + len(glue1)) % 64 == 0
    absorbed1 = secret_len + len(msg_alice) + len(glue1)
    sig_admin = sha256_continue(list(struct.unpack(">8I", sig_alice)),
                                absorbed1, admin_msg.encode())

    # 8) 解 admin 层库：没有 flag，只有 root 续签说明
    admin_plain = unxor(vault, sig_admin.hex()).decode("utf-8", "replace")
    assert "ROOT_SUFFIX: " in admin_plain and "flag{" not in admin_plain, (
        f"伪造 admin sig 应解开 admin 层（得 {admin_plain[:40]!r}）")
    root_suffix = next(l for l in admin_plain.splitlines()
                       if l.startswith("ROOT_SUFFIX: ")).split(": ", 1)[1]

    # 9) 第二次伪造（链式）：sig_admin 是"88 字节 admin 会话补齐到 128 字节"
    #    之后的链值——注入态已把 admin 消息自己的终 padding（=glue2，40 字节）
    #    吸收进块界。续算 root_suffix（59 字节）+ 终 padding 恰好 2 个整块。
    absorbed_raw2 = absorbed1 + len(admin_msg)      # 88：admin 会话原文
    glue2 = _md_padding(absorbed_raw2)              # 40：admin 消息的终 padding
    absorbed2 = absorbed_raw2 + len(glue2)          # 128：sig_admin 的块界
    sig_root = sha256_continue(list(struct.unpack(">8I", sig_admin)),
                               absorbed2, root_suffix.encode())

    # 10) 解 root 层库
    root_plain = unxor(vault_root, sig_root.hex()).decode("utf-8", "replace")
    assert "flag{" in root_plain, (
        f"链式伪造的 root sig 解不开 root 层（得 {root_plain[:40]!r}）")
    return root_plain


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent)
    out = solve(work_dir)
    print(out)
    print(f"FLAG: {find_flag(out)}")
