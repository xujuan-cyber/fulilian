# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/工具使用/tshark使用.md
# TITLE: tshark使用
# CATEGORY: misc

import dpkt
# import datetime
import socket

f = open(r'C:\Users\25348\Desktop\存储型XSS.pcap', 'rb')  # 要以rb方式打开，用r方式打开会报错
pcap = dpkt.pcap.Reader(f)
for timestamp, buf in pcap:
    # 打印UTC时间
    # print('时间戳：' + str(datetime.datetime.utcfromtimestamp(timestamp)))
    
    eth = dpkt.ethernet.Ethernet(buf)
    ip = eth.data
    src = socket.inet_ntoa(ip.src)
    dst = socket.inet_ntoa(ip.dst)
    print('[+] Src：' + src + ' ——> Dst：' + dst)
