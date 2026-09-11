"""solve_reference — reverse-obfchain-01 参考解（fixture 自证）。

正确流程（6 步）：
  1. 看 data.bin 的头两字节是 `78 9C` —— zlib 流。所以至少有一层 inflate。
  2. 从**真正的 `main`** 出发，追它调用的函数：`main → sub_4F10`。
     **不能**用"哪个 sub_ 被别人调用"这条启发式 —— `main_legacy` 那条
     死链同样成立，会把人引到诱饵上。
  3. `sub_4F10` 里只有一句 `return sub_XXXX(...)`，拿到真函数名。
  4. 从真函数体里抽出 `tbl[16]` 与 XOR 常量，按 `key[i] = tbl[i] ^ C` 还原密钥。
  5. inflate data.bin，再用密钥循环 XOR —— 得到 flag。
  6. 拿 `flag{` 前缀自检。**这一步不可省**：用错函数时 inflate 照样成功，
     只是解出乱码，命令会以退出码 0 "成功"结束。

第 2 步与第 6 步是本题的考点。第 2 步考调用图推理，第 6 步考"解得出来
不等于解对了"的自检纪律 —— 现有 easy 语料里两者都不需要。
"""

SOLUTION_STEPS = 6

import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solve_reference_common import find_flag  # noqa: E402

_RE_TBL = re.compile(r"tbl\[16\]\s*=\s*\{(.*?)\}", re.S)
_RE_XORC = re.compile(r"tbl\[i\]\s*\^\s*0x([0-9A-Fa-f]{2})")
# 调用形态不固定：main 里是赋值 `plain = sub_4F10(...)`，而 sub_4F10 里是
# `return sub_XXXX(...)`。所以只匹配"函数名后跟左括号"，不要求前面的关键字。
_RE_CALL = re.compile(r"\b(sub_[0-9A-F]{4})\s*\(")
_RE_DEF = re.compile(
    r"unsigned char \*(sub_[0-9A-F]{4})\(const unsigned char \*buf.*?\n\}", re.S
)
_RE_MAIN = re.compile(r"^int main\(.*?\n\}", re.S | re.M)


def _body(src: str, name: str) -> str:
    for m in _RE_DEF.finditer(src):
        if m.group(1) == name:
            return m.group(0)
    raise SystemExit(f"参考解：找不到函数体 {name}")


def _callee(body: str, self_name: str) -> str:
    """函数体里第一个**不是自身**的 sub_ 调用。

    必须排除自身：函数体文本以签名开头（`sub_4F10(const unsigned char *buf`），
    而 `_RE_CALL` 只看"名字后跟括号"，所以不排除的话会匹配到自己，
    调用链原地打转。这个 bug 真的发生过 —— hop2 回到了 hop1。
    """
    for m in _RE_CALL.finditer(body):
        if m.group(1) != self_name:
            return m.group(1)
    raise SystemExit(f"参考解：{self_name} 里找不到任何调用")


def solve(work_dir: str) -> str:
    from solve_reference_common import read_text

    work = Path(work_dir)
    blob = (work / "data.bin").read_bytes()
    src = read_text(work_dir, "decompiled.c")
    # 魔数不写死：zlib 的最高两位是压缩级别（78 01/78 9C/78 DA 分别对应
    # 最快/默认/最优），生成器用的是 level 9。写死成 78 9C 就会与语料不符。
    out = [f"$ xxd data.bin | head -1\n{blob[:2].hex(' ')}  → zlib 流头"]

    # 第 2 步：从真正的 main 出发。注意**不能用**"谁有调用者"来筛 ——
    # main_legacy → sub_A1B2 那条死链也满足这一条。
    main_body = _RE_MAIN.search(src)
    if not main_body:
        raise SystemExit("参考解：找不到 main")
    hop1 = _callee(main_body.group(0), "main")
    out.append(f"$ grep -A3 '^int main' decompiled.c | grep -o 'sub_[0-9A-F]*('\n"
               f"main → {hop1}")

    real = _callee(_body(src, hop1), hop1)
    out.append(f"$ grep -A2 '{hop1}(' decompiled.c | grep -o 'sub_[0-9A-F]*('\n"
               f"{hop1} → {real}   ← 活跃路径的唯一终点")

    # 第 4 步：还原密钥。
    body = _body(src, real)
    tbl = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", _RE_TBL.search(body).group(1))]
    xc = int(_RE_XORC.search(body).group(1), 16)
    key = bytes(b ^ xc for b in tbl)
    out.append(f"$ grep 'tbl\\[i\\]' decompiled.c\nkey[i] = tbl[i] ^ 0x{xc:02X} → {key.hex()}")

    # 第 5 步：inflate → 循环 XOR。
    inflated = zlib.decompress(blob)
    plain = bytes(b ^ key[i % 16] for i, b in enumerate(inflated))
    text = plain.decode("utf-8", errors="replace")
    out.append(f"$ python -c 'inflate(data.bin) ^ key'\n{text}")

    # 第 6 步：自检。缺了它，用错函数也会"成功"。
    if "flag{" not in text:
        raise SystemExit("参考解解出来不含 flag —— 生成器与参考解不一致")
    return "\n".join(out) + "\n" + find_flag(text)
