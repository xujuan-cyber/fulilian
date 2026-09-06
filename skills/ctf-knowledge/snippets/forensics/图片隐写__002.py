# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/图片隐写.md
# TITLE: 图片隐写
# CATEGORY: forensics

# -*- coding: utf-8 -*-
import string
import os
dic = string.ascii_letters
i=0
i1=0
print(dic[:26])
for n in dic[:11]:
    # file = 'part'
    # file = file+str(n)
    for m in dic[:26]:
        file1=''
        file = 'part'+str(n)
        # print(file)
        file1 = file+str(m)
        file = file+str(m)+'.enc'
        print(file,file1)
        os.system('openssl rsautl -decrypt -inkey key -in %s -out %s' %(file ,file1))
        file1 = file+str(m)
        os.system('rm -f %s %s' %(file,file1))
os.system('cat part* > final')
