# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（下）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（下）
# CATEGORY: crypto

import
 encode_data = "SLHAIOj8/1icVtP6fImtJz6B6wR0t/XwLg1G0Y3AxoxnseBfPONxoyjAWCCOH84IJULnCZZrO7cIRxJPS2PtmDD4MvD8/PIpoW8Gj8536vhwd+tyXjNKyLNyNYcj+JgO4N5FTnKtkONgv7KnsMjJC3E0eI0ctqmZll8SrXLUS9k="
 private_key = RSA.import_key(PRIVATE_KEY.encode())
 cipher = PKCS1_v1_5.new(private_key) ciphertext = cipher.decrypt(base64.b64decode(encode_data), 0)
if ciphertext[0:4] == b'x00x00xBExEF': raw_aes_keys = ciphertext[8:24]# print(raw_aes_keys) raw_aes_hash256 = hashlib.sha256(raw_aes_keys).digest() aes_key = raw_aes_hash256[0:16] hmac_key = raw_aes_hash256[16:]
 print("RAW key: {}".format(raw_aes_keys.hex())) print("AES key: {}".format(aes_key.hex())) print("HMAC key: {}".format(hmac_key.hex()))
 hexdump.hexdump(ciphertext)   ```
