# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/当爬虫工程师遇到CTF丨B站1024安全攻防题解.md
# TITLE: 当爬虫工程师遇到CTF丨B站1024安全攻防题解
# CATEGORY: misc

import base64

byte_arr1 = [78, 106, 73, 49, 79, 122, 65, 51, 89, 71, 65, 117, 78, 106, 78, 109, 78, 122, 99, 55, 89, 109, 85, 61]
byte_arr2 = [89, 87, 66, 108, 79, 109, 90, 110, 78, 106, 65, 117, 79, 109, 74, 109, 78, 122, 65, 120, 79, 50, 89, 61]

byte_arr1_ = bytes(b % 256 for b in byte_arr1)
byte_arr2_ = bytes(b % 256 for b in byte_arr2)

bs64_arr1 = base64.b64decode(byte_arr1_)
bs64_arr2 = base64.b64decode(byte_arr2_)

username = password = ""

for i in range(len(bs64_arr1)):
    username += chr(bs64_arr1[i] ^ 3)

for i in range(len(bs64_arr2)):
    password += chr(bs64_arr2[i] ^ 3)

print("username: ", username)
print("password: ", password)
print("flag: ", username + "-" + password)
username:  516834cc-50e448af
password:  bcf9ed53-9ae4328e
flag:  516834cc-50e448af-bcf9ed53-9ae4328e
