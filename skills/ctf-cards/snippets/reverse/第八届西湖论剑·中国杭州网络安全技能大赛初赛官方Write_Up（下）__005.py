# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（下）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（下）
# CATEGORY: reverse

import
 AES_KEY = binascii.unhexlify("9fe14473479a283821241e2af78017e8") HMAC_KEY = binascii.unhexlify("1e3d54f1b9f0e106773a59b7c379a89d") encrypt_data = "hex"
def decrypt(encrypted_data, iv_bytes, signature, AES_KEY, hmac_key): cipher = AES.new(AES_KEY, AES.MODE_CBC, iv_bytes)return cipher.decrypt(encrypted_data)
 encrypt_data = bytes.fromhex(encrypt_data)

try: encrypt_data_length = int.from_bytes(encrypt_data[:4], byteorder='big', signed=False) encrypt_data_l = encrypt_data[4:] data1 = encrypt_data_l[:
encrypt_data_length-16] signature = encrypt_data_l[encrypt_data_length-16:
encrypt_data_length] iv_bytes = b"abcdefghijklmnop" dec = decrypt(data1, iv_bytes, signature, AES_KEY, HMAC_KEY)
except: dec = decrypt(encrypt_data, iv_bytes, signature, AES_KEY, HMAC_KEY)
 print("counter: {}".format(int.from_bytes(dec[:4], byteorder='big', signed=False))) print("任务返回长度: {}".format(int.from_bytes(dec[4:8], byteorder='big', signed=False))) print("任务输出类型: {}".format(int.from_bytes(dec[8:12], byteorder='big', signed=False)))
# print(dec[:
100].hex())
# print(dec[12:
int.from_bytes(dec[4:8], byteorder='big', signed=False)]) print(hexdump.hexdump(dec[:
1000])) open('secret.pcapng','wb').write(dec[64:-76])   ```
