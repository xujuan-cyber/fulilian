# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/【WP】第七届“湖湘杯”_leaker-设计思路与解析.md
# TITLE: 【WP】第七届“湖湘杯” leaker|设计思路与解析
# CATEGORY: forensics

from PIL import Image
import numpy as np
import random
import base64

im = Image.open('leaker.png')
im = np.asarray(im)
x, y, z = im.shape

print(im.shape)

c = []
for j in range(y):
    c.append(1 - im[0, j, 3] // 255)
    c.append(1 - im[1, j, 3] // 255)

c = ''.join([str(x) for x in c])
c = c[:c.find('00000000')]
flag = ''.join([chr(int(c[i:i+8], 2)) for i in range(0, len(c), 8)])

print(flag)
print(base64.b64decode(flag.encode()))
