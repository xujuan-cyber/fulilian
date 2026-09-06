# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/代码审计/README.md
# TITLE: 代码审计
# CATEGORY: web

import hashlib


def md5(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()


for i in range(10000000):
    if(md5(str(i)).startswith('6d0bc1')):
        print(i)
        break
# 2020666
