# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF常用脚本及工具/SCRIPTS-INDEX.md
# TITLE: CTF 脚本工具索引
# CATEGORY: misc

# variant_caesar.py — 偏移量逐个递减的凯撒
c = "密文"
for move in range(0, 50):
    flag = ""
    for i in c:
        flag += chr(ord(i) - move)
        move = move - 1
    print(flag)
