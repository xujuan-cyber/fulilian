# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/【工控Writeup】2022河南工业互联网安全大赛复赛.md
# TITLE: 【工控Writeup】2022河南工业互联网安全大赛复赛
# CATEGORY: reverse

import string
flag = bytearray(b"666i5250356j4249"b"616732557968356j")for i in range(len(flag)):    if flag[i] in string.ascii_lowercase.encode():        flag[i] -= 4print(flag)print(bytes.fromhex(flag.decode()))
tshark -r .modbus.pcap -Y "modbus && ip.src==172.31.14.123" -T fields -e "frame.number" -T fields -e "modbus.func_code" > data.txt
data = []with open("data.txt", 'r') as f:    for line in f:        data.append(line.strip().split('t'))
base = ['17', '109', '65', '1', '1', '3', '3', '67']p = 0for i in data:    if i[1] != base[p % len(base)]:        print(i)    p += 1
data = []with open("data.txt", 'r') as f:    for line in f:        data.append(line.strip().split('t'))
base = ['17', '109', '65', '1', '1', '3', '3', '67']p = 0for i in data:    if p == 539:        continue    if i[1] != base[p % len(base)]:        print(i)    p += 1
