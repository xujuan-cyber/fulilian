# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/文件上传/README.md
# TITLE: 文件上传
# CATEGORY: web

import requests
url = "http://8.142.44.97:1111/upload/1.php"
while True:
    html = requests.get(url)
    if html.status_code == 200:
        print("OK")
        break
