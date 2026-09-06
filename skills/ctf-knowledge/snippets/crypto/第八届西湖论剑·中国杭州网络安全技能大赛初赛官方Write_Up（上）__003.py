# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（上）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（上）
# CATEGORY: crypto

import
hackkey = '4etz0hHbU3TgKqduFL'
with open('private.pem', 'rb') as f: private_key = RSA.import_key(f.read())
with open('encrypted_data.bin', 'rb') as f: ciphertext = f.read()
enc_aes_key = bytes.fromhex('20d96098010eb9b326be6c46e1ce1ca679e29f1d65dec055cf8c46c6436c3356af2dc312b2d35466308b9fff0dd427b44a37e34fca12992e45db2ddd81884bd8eb5bccd3c595e8a9a352bd61322e1d52329d6c8638bbfce65edffbc4d3a5759e88c0f90e31ce518837552a3a09d8e7e3c374f3857bfe501cce2066fb233ff1f5faac18d73c3b665a54e8c55574f16bf4678c5ce835d2a14a65f8c1cec012435a8c06314cbe727a3a9b6060dfd6cdb850073423841178f6f409bb7ce8d4863c6f58855954d34af3d2964c488c9057c8c5072a54e43f1f8039d32409eb1ff3abca41c0b302788c4c56c1a4be4506ff5b8aff0242e21c0ee7ffee2da20ed9434334')nonce = bytes.fromhex('d919c229aab6535efa09a52c589c8f47')tag = bytes.fromhex('5b204675b1b173c32c04b0b8a100ee29')
cipher_rsa = PKCS1_OAEP.new(private_key)aes_key = cipher_rsa.decrypt(enc_aes_key)
derived_aes_key = hashlib.sha256(hackkey.encode()).digest()if aes_key != derived_aes_key: raise ValueError("Decryption failed: AES key mismatch")
cipher_aes = AES.new(aes_key, AES.MODE_EAX, nonce=nonce)data = cipher_aes.decrypt_and_verify(ciphertext, tag)
with open('data.csv', 'wb') as f: f.write(data)
