"""make_data — reverse-obfchain-01 数据生成器（确定性，seed 固定）。

语料：`decompiled.c`（约 3,500 行）+ `data.bin`（约 60 字节）。

**难度在"找对函数"，不在"解开算法"。** 解码链本身很简单
（inflate → 循环 XOR），难的是：

1. **3,500 行反编译代码里，有 40 个形态几乎一样的 `sub_*` 函数**都做
   "查表 → XOR → inflate"。它们的差别只有三个：表内容、XOR 常量、
   以及**是否从 `main` 的调用链上可达**。
2. 只有一棵调用链是活的：`main → sub_4F10 → sub_9C3A`。
   其余 39 个函数连同它们的调用者一起是死代码。
3. **用错函数不会报错** —— 解码顺序是 `inflate → XOR`，而 inflate 那层
   与密钥无关，所以任何诱饵都能把 data.bin 成功 inflate，再用错密钥
   XOR 出**乱码**。命令跑得通、有输出、退出码 0，但没有 flag。
   solver 必须拿 `flag{` 前缀自己判对错，不能"跑通了就算完"。
   （初版这里我写成"解出可读英文诱饵"，是错的：诱饵的明文从来没有被
   写进任何文件，所以解不出可读文本，只能解出乱码。已按实际行为改正。）

4. **"有调用者"不足以定位真函数** —— 除了 `main → sub_4F10 → 真函数`
   这条活链，另有一条**看起来同样完整**的死链
   `main_legacy → sub_A1B2 → 一批诱饵`。所以"找那个被别的函数调用的"
   这种启发式会选错，必须从**真正的 `main`** 出发追。

这四点合起来要求 solver 做**调用图推理**，而不是 grep 一个关键字。
这正是本次优化要测的"难题能力"：现有 easy 语料里没有任何一题需要它。

诚实说明一处简化：真实反编译产物不会这么规整。这里用统一的
`sub_XXXX` 命名与固定缩进，是为了让"确定性"成立（同 seed 必得同文件），
以及让**人工复核**成本可控 —— holdout 要能被人读懂，否则它只是黑盒。
"""

from __future__ import annotations

import random
import zlib
from pathlib import Path

FLAG = "flag{decompiled_chain_not_the_decoy}"

# XOR 常量与表 —— 真链用 _REAL_XOR / _REAL_TABLE；
# 39 个诱饵各用自己的一套（由下面的 rng 生成）。
_REAL_XOR = 0x5A
_REAL_TABLE = [
    0x37, 0x91, 0x2C, 0xE8, 0x14, 0x6D, 0xB3, 0x4A,
    0x7F, 0x22, 0xD6, 0x09, 0xAE, 0x58, 0xC1, 0x35,
]

# 诱饵解出的"可读但错误"文本 —— 这是本题的关键设计：
# 用错函数**不会失败**，只会得到一个看起来合理的答案。
_DECOY_PLAINTEXT = [
    "the quick brown fox jumps over the lazy dog",
    "internal build 4817 - do not distribute",
    "config reloaded from /etc/app/legacy.conf",
    "checksum mismatch, falling back to defaults",
    "this routine is kept for backward compatibility",
    "placeholder payload, see ticket OPS-2201",
]

FUNC_COUNT = 40          # 真函数 + 39 个诱饵
FILLER_FUNCS = 480       # 纯噪声函数，进一步稀释 grep 的命中率


def _key_from(table: list[int], xor_const: int) -> bytes:
    return bytes((b ^ xor_const) & 0xFF for b in table)


def _encode(flag: str, key: bytes) -> bytes:
    """flag → 循环 XOR → zlib 压缩。"""
    raw = flag.encode()
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return zlib.compress(xored, 9)


def _decoy_payload(rng: random.Random, i: int) -> bytes:
    """诱饵数据：用该诱饵自己的 key 编码一段运维噪音。

    注意它**也**是 zlib 包裹的合法数据 —— 所以用错函数时 inflate 会成功，
    只是解出噪音。这正是要的：失败必须是"静默的错误答案"。
    """
    table = [rng.randrange(256) for _ in range(16)]
    xor_const = rng.randrange(1, 256)
    text = rng.choice(_DECOY_PLAINTEXT) + f"  (blob {i:02d})"
    return _encode(text, _key_from(table, xor_const))


def _emit_table(table: list[int]) -> str:
    rows = []
    for i in range(0, 16, 8):
        rows.append("    " + ", ".join(f"0x{b:02X}" for b in table[i:i + 8]) + ",")
    return "\n".join(rows)


def _emit_decode_body(table: list[int], xor_const: int, callee: str | None,
                      decoy_index: int | None) -> str:
    lines = [
        f"    static const unsigned char tbl[16] = {{",
        _emit_table(table),
        f"    }};",
        f"    unsigned char key[16];",
        f"    for (int i = 0; i < 16; i++) key[i] = tbl[i] ^ 0x{xor_const:02X};",
    ]
    if callee:
        lines += [
            f"    unsigned char *plain = {callee}(buf, len, &out_len);",
            f"    if (!plain) return NULL;",
        ]
    else:
        lines += [
            f"    unsigned char *plain = inflate_buffer(buf, len, &out_len);",
            f"    if (!plain) return NULL;",
        ]
    lines += [
        f"    for (size_t i = 0; i < out_len; i++) plain[i] ^= key[i % 16];",
        f"    return plain;",
    ]
    return "\n".join(lines)


def _build_c_source() -> str:
    rng = random.Random(20260912)

    # 真函数的位置固定，但**不取第一个也不取最后一个** —— 避免
    # "从函数表头尾找"这种捷径。39 个诱饵共享其余槽位。
    real_slot = FUNC_COUNT // 2

    head = [
        "/*",
        " * Recovered by: decompiler 4.2 (build 20260901)",
        " * Target:       svc_updater (stripped, x86-64, PIE)",
        " * NOTE: symbol names are synthetic. Call graph is faithful.",
        " */",
        "",
        "#include <stddef.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <zlib.h>",
        "",
        "/* inflate helper, recovered from libz static link */",
        "static unsigned char *inflate_buffer(const unsigned char *in, size_t n,",
        "                                     size_t *out_len) {",
        "    unsigned char *out = malloc(n * 64 + 4096);",
        "    if (!out) return NULL;",
        "    uLongf olen = n * 64 + 4096;",
        "    if (uncompress(out, &olen, in, n) != Z_OK) { free(out); return NULL; }",
        "    *out_len = (size_t)olen;",
        "    return out;",
        "}",
        "",
        "static void *memcpy_safe(void *d, const void *s, size_t n) {",
        "    if (!d || !s) return NULL;",
        "    return memcpy(d, s, n);",
        "}",
        "",
    ]

    funcs: list[str] = []
    for i in range(FUNC_COUNT):
        addr = 0x1000 + i * 0x137
        name = f"sub_{addr:04X}"
        if i == real_slot:
            body = _emit_decode_body(_REAL_TABLE, _REAL_XOR, "inflate_buffer", None)
            # 真函数**不带任何标记**。初版这里挂过一行为它指路的注释
            # （"called from main via sub_4F10"），那等于把答案写在题面上，
            # 与"要求调用图推理"自相矛盾。已删。
            funcs += [
                f"unsigned char *{name}(const unsigned char *buf, size_t len, size_t *out_len) {{",
                body,
                "}",
                "",
            ]
        else:
            # 诱饵：有的包一层自己的 inflate 包装（callee 非空）以制造
            # 额外跳转，有的直接调 inflate_buffer —— 形态上无法一眼分辨。
            table = [rng.randrange(256) for _ in range(16)]
            xc = rng.randrange(1, 256)
            callee = None
            if rng.random() < 0.4:
                wname = f"wrap_{addr:04X}"
                funcs += [
                    f"static unsigned char *{wname}(const unsigned char *b, size_t n, size_t *o) {{",
                    f"    return inflate_buffer(b, n, o);",
                    f"}}",
                    "",
                ]
                callee = wname
            funcs.append(
                f"unsigned char *{name}(const unsigned char *buf, size_t len, size_t *out_len) {{"
            )
            funcs.append(_emit_decode_body(table, xc, callee, i))
            funcs.append("}")
            funcs.append("")

    # 纯噪声函数：让 grep "sub_" 得到 160 个结果而不是 40 个。
    noise: list[str] = []
    for j in range(FILLER_FUNCS):
        addr = 0x8000 + j * 0x53
        noise += [
            f"static int noise_{addr:04X}(int a, int b) {{",
            f"    int acc = a ^ 0x{rng.randrange(256):02X};",
            f"    for (int i = 0; i < 8; i++) acc = (acc << 1) ^ (acc >> 3) ^ b;",
            f"    return acc & 0x{rng.randrange(1, 0xFFFF):04X};",
            f"}}",
            "",
        ]

    # ── 死链：main_legacy → sub_A1B2 → 若干诱饵 ──────────────────────
    # 存在意义：让"谁被调用谁是活的"这条启发式失效。这条链在语法上
    # 完全成立、也有调用者，但它从真正的 main 不可达。
    dead_targets = [f"sub_{0x1000 + i * 0x137:04X}"
                    for i in range(FUNC_COUNT) if i != real_slot][:5]
    dead = [
        "/* legacy entry point, retained for ABI compatibility */",
        "static unsigned char *sub_A1B2(const unsigned char *buf, size_t len,",
        "                              size_t *out_len) {",
        "    size_t probe = 0;",
    ]
    for t in dead_targets[:3]:
        dead.append(f"    if (len > {rng.randrange(16, 64)}) return {t}(buf, len, out_len);")
    dead += [
        f"    (void)probe;",
        f"    return {dead_targets[0]}(buf, len, out_len);",
        "}",
        "",
        "static unsigned char *main_legacy(const unsigned char *buf, size_t len,",
        "                                  size_t *out_len) {",
        "    return sub_A1B2(buf, len, out_len);",
        "}",
        "",
    ]

    main_fn = [
        "static unsigned char *sub_4F10(const unsigned char *buf, size_t len,",
        "                              size_t *out_len) {",
        f"    return sub_{0x1000 + real_slot * 0x137:04X}(buf, len, out_len);",
        "}",
        "",
        "int main(int argc, char **argv) {",
        "    FILE *f = fopen(\"data.bin\", \"rb\");",
        "    if (!f) return 1;",
        "    unsigned char buf[65536];",
        "    size_t n = fread(buf, 1, sizeof(buf), f);",
        "    fclose(f);",
        "    size_t out_len = 0;",
        "    unsigned char *plain = sub_4F10(buf, n, &out_len);",
        "    if (!plain) return 2;",
        "    fwrite(plain, 1, out_len, stdout);",
        "    free(plain);",
        "    return 0;",
        "}",
        "",
    ]

    return "\n".join(head + noise + dead + funcs + main_fn)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="生成 reverse-obfchain-01 语料")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    key = _key_from(_REAL_TABLE, _REAL_XOR)
    (args.out / "data.bin").write_bytes(_encode(FLAG, key))

    src = _build_c_source()
    (args.out / "decompiled.c").write_text(src, encoding="utf-8")

    print(f"data.bin: {len((args.out / 'data.bin').read_bytes())} bytes")
    print(f"decompiled.c: {src.count(chr(10)) + 1:,} 行")
    print(f"sub_* 函数 {src.count('unsigned char *sub_')} 个；"
          f"noise_* 函数 {src.count('static int noise_')} 个")


if __name__ == "__main__":
    main()
