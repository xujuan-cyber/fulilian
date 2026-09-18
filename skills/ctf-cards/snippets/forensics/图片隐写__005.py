# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/图片隐写.md
# TITLE: 图片隐写
# CATEGORY: forensics

import os
import binascii
import struct


misc = open("flag.png","rb").read()

for i in range(1024):
    data = misc[12:16] + struct.pack('>i',i)+ misc[20:29]
    crc32 = binascii.crc32(data) & 0xffffffff
    if crc32 == 0x932f8a6b:
        print i
~~~

#### 例题-evalheight

根据题目名称肯定是修改高度了,这里展示一下多种工具的使用.
magnetos：





bash
