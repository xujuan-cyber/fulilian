# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（下）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（下）
# CATEGORY: reverse

from
# 将你的16进制字符串放在这里 hex_key = "30819e300d06092a864886f70d010101050003818c00308188028180525e1781f2f02d132a7818a6d269baddbf39352c8d20290ec2294fbe4d77e6549ef4766d8b0e1620000adfbd7aff99cd72f05623eb0def202265cf631dd895acd5e981da8424c03a295895c8194a31641f2eecd5a8715ca89cdbf9433c5d437538767666c3bdb0f8629555375b574fe408a94ae82f92960085d416374f1654b30203010001" # 用你的实际十六进制字符串替换
# 将十六进制字符串转换为字节 key_bytes = binascii.unhexlify(hex_key)
# 导入RSA公钥 rsa_key = RSA.import_key(key_bytes)
# 提取模数(n)和指数(e) n = rsa_key.n e = rsa_key.e
# 打印模数和指数 print(f"Modulus (n): {n}") print(f"Exponent (e): {e}")
# 将RSA公钥导出为PEM格式 pem_key = rsa_key.publickey().export_key(format='PEM')
# 打印PEM格式公钥 print(pem_key.decode('utf-8'))   ```
