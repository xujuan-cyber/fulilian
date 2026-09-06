# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/文件包含.md
# TITLE: 正文
# CATEGORY: web

import requests

files = {
  'file': ("aa.txt","ssss")
}
url = "http://x.x.x.x/phpinfo.php"
r = requests.post(url=url, files=files, allow_redirects=False)
print(r.text)
