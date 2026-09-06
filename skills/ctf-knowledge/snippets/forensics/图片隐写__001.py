# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/图片隐写.md
# TITLE: 图片隐写
# CATEGORY: forensics

# -*- coding: utf-8 -*-
import os
import binascii

os.system('identify -format "%c \n" Question.gif > key')

temp=open('key','rb')
f = open('key1', 'wb+')
for i in temp:
    i = i.decode('utf-8')
    i=int(i,16)
    i=hex(i)
    i = binascii.unhexlify(i[2:])
   # 
    i = i.decode('utf-8') + '\n'
    i = bytes(i, 'utf-8')

    f.write(i)

temp.close()
f.close()
os.system('rm -f key')
os.rename('key1','key')
