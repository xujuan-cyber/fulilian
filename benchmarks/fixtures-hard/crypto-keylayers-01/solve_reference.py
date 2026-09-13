"""solve_reference — crypto-keylayers-01 参考解（自证：能真解出 flag）。

链条：指纹定位 record → priv 解 L1 → 活 key2a + 导出尾部 key2b 拼接 → 解 L2 → 深处取 flag。
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solve_reference_common import find_flag  # noqa: E402

SOLUTION_STEPS = 9

_STEP_LINES = [
    "读 vault.export 头部，抄下 scheme（xor-sha256 对合流）、keyref 指纹 fp16、"
    "material-sha256-16 验真摘要",
    "脚本扫描 keyserver.dump 全部 25,000 条 record，对每条 pub 计算 sha256(pub)[:16]，"
    "命中 fp16 的那条就是钥 record（同 owner 的 3 条诱饵靠指纹排除）",
    "用命中 record 的 priv 作 ASCII 钥，xor(sha256(priv)) 试解两份 material blob，"
    "能解开的才是真链（另一份是平行诱饵链，解出来也拿去验摘要就知道是假）",
    "得到 L1 明文（'# layer 2/3' 开头）",
    "在 vault.export 尾部找 '### keystore-tail ###' 标记，取标记后的 key2b",
    "按 L1 明文判据试出活的 key2a：三个候选各与 key2b 组合解 L2，"
    "只有活的那对解出来开头是 '# layer 3'",
    "key2 = key2a + key2b（ASCII 拼接，无分隔），解 L2 得最终明文，落盘",
    "对照头部 material-sha256-16 验真最终明文（sha256[:16] 一致才算真），"
    "别拿第一份看着像的当答案",
    "在最终明文中部搜 recovery/token，取 flag",
]


def _print_steps() -> None:
    for i, s in enumerate(_STEP_LINES, 1):
        print(f"step {i}: {s}")


def solve(work_dir: str) -> str:
    work = Path(work_dir)
    export = (work / "vault.export").read_text(encoding="utf-8")

    # 1) 抄 scheme、keyref 与验真摘要
    _print_steps()
    fp16 = re.search(r"# keyref: pub:([0-9a-f]{16})", export).group(1)
    digest = re.search(r"# material-sha256-16: ([0-9a-f]{16})", export).group(1)

    # 2) 全量算指纹，定位 record（同 owner 诱饵在此消歧）
    hit = None
    for line in (work / "keyserver.dump").read_text(encoding="utf-8").splitlines():
        m = re.search(r"pub=([0-9a-f]{64})\s+priv=([0-9a-f]{64})", line)
        if m and hashlib.sha256(m.group(1).encode("ascii")).hexdigest()[:16] == fp16:
            hit = m.group(2)
    assert hit, "指纹未命中任何 record"

    # 3) 用命中 priv 试解两份 material blob —— 能解开的才是真链
    def unxor(data: bytes, key_ascii: str) -> bytes:
        ks = hashlib.sha256(key_ascii.encode("ascii")).digest()
        return bytes(b ^ ks[i % len(ks)] for i, b in enumerate(data))

    body = export.split("\n\n", 1)[1].split("### keystore-tail ###")[0]
    blobs = [base64.b64decode(l.strip()) for l in body.splitlines()
             if l.strip() and not l.strip().startswith("#")]
    l1_plain = next((b for b in (unxor(x, hit) for x in blobs)
                     if b.startswith(b"# layer 2/3")), None)
    assert l1_plain, "指纹命中的 priv 解不开任何 material blob"
    l1_text = l1_plain.decode()
    l2_b64 = l1_text.split("\n\n", 1)[1].strip()

    # 4) 尾部取 key2b
    key2b = re.search(r"### keystore-tail ###\s*key2b = ([0-9a-f]{32})", export).group(1)

    # 5) 判据选活 key2a（每个候选与 key2b 组合试解）
    l2_blob = base64.b64decode(l2_b64)
    for ka in re.findall(r"key2a = ([0-9a-f]{32})", l1_text):
        if unxor(l2_blob, ka + key2b).startswith(b"# layer 3"):
            key2a = ka
            break
    else:
        raise AssertionError("没有一行 key2a 与 key2b 组合能解开 L2")

    # 6) 解 L2，落盘（明文 ~100 KB，别塞进上下文）
    l3_text = unxor(l2_blob, key2a + key2b).decode("utf-8")
    (work / "recovered-layer3.txt").write_text(l3_text, encoding="utf-8")

    # 7) 验真：最终明文的 sha256[:16] 必须与头部 material-sha256-16 一致
    got = hashlib.sha256(l3_text.encode("utf-8")).hexdigest()[:16]
    assert got == digest, f"摘要不符（{got} != {digest}）—— 拿到的是诱饵链，不是真材料"

    # 8) 深处取 flag
    token = re.search(r"recovery/token = (\S+)", l3_text)
    assert token, "最终明文里没有 recovery/token"
    return token.group(1)


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent)
    flag = solve(work_dir)
    print(f"FLAG: {find_flag(flag)}")
