#!/usr/bin/env python3
"""
MT19937 变体通用求解器（GF(2) 矩阵求逆 untemper）
适用：题目自定义 Myrand 类，temper 为任意 32 位线性变换（旋转/异或移位/mask 任意组合），
     twist 或初始化常数可被改。已知 >=624 个连续输出时恢复状态并预测后续输出。
用法：改 TEMPER() 为题目实现 -> python mt_variant_solver.py <outputs.txt>
     outputs.txt 为 Python list 字面量（str(list) 写出即可）。
来源：DASCTF 2022 May 出题人挑战赛 random 题（2026-09 验证可用）
"""
import ast, random, sys
from hashlib import md5

MASK = 0xffffffff
def rotl(x, s): return ((x << s) | (x >> (32 - s))) & MASK
def rotr(x, s): return ((x >> s) | (x << (32 - s))) & MASK

# ===== 按题目改这里：temper 必须是线性的（纯 XOR/移位/旋转） =====
def temper(y):
    y = y ^ rotl(y, 11) ^ rotl(y, 15)
    y = y ^ rotr(y, 7) ^ rotr(y, 19)
    return y

def gf2_invert_temper():
    """返回 M^{-1} 的 32 个行向量；untemper 第 i 输出位 = <row_i, y> mod 2。"""
    cols = [temper(1 << i) for i in range(32)]          # M 的列
    rows = []
    for j in range(32):                                  # M 的行 j（输出位 j 的输入掩码）
        r = 0
        for i in range(32):
            if (cols[i] >> j) & 1:
                r |= 1 << i
        rows.append(r)
    aug = [[rows[j], 1 << j] for j in range(32)]         # [M | I]
    for c in range(32):
        p = next(k for k in range(c, 32) if (aug[k][0] >> c) & 1)
        aug[c], aug[p] = aug[p], aug[c]
        for k in range(32):
            if k != c and (aug[k][0] >> c) & 1:
                aug[k][0] ^= aug[c][0]
                aug[k][1] ^= aug[c][1]
    assert all(aug[c][0] == (1 << c) for c in range(32)), "temper 不可逆（非线性？）"
    return [aug[c][1] for c in range(32)]

INV = gf2_invert_temper()

def untemper(y):
    x = 0
    for i in range(32):
        if bin(INV[i] & y).count("1") & 1:               # 行向量 parity 内积（勿按列拼！）
            x |= 1 << i
    return x

def selftest():
    for _ in range(1000):
        v = random.getrandbits(32)
        assert temper(untemper(v)) == v

def predict_next(outputs):
    state = [untemper(o) for o in outputs]               # 第一次 twist 后的 MT 数组
    assert all(temper(s) == o for s, o in zip(state, outputs))
    # 标准 twist：若题目 twist 也被改，改为复用题目类（r=Myrand.__new__(Myrand); r.MT=state; r.index=0; r.rand()）
    for i in range(624):
        y = (state[i] & 0x80000000) + (state[(i + 1) % 624] & 0x7fffffff)
        state[i] = state[(i + 397) % 624] ^ (y >> 1)
        if y & 1:
            state[i] ^= 2567483520
    return temper(state[0])                              # 下一轮第 0 个输出

if __name__ == "__main__":
    selftest()
    print("[+] temper/untemper roundtrip OK")
    outs = ast.literal_eval(open(sys.argv[1]).read()) if len(sys.argv) > 1 else \
           [random.getrandbits(32) for _ in range(624)]
    assert len(outs) >= 624
    nxt = predict_next(outs[:624])
    print("[+] next output:", nxt)
    # 常见 flag 构造：md5(str(next))
    print("md5(str(n)) =", md5(str(nxt).encode()).hexdigest())
