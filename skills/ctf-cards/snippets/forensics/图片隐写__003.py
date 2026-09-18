# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/图片隐写.md
# TITLE: 图片隐写
# CATEGORY: forensics

from PIL import Image
import re

x = 180 #x坐标  对于文件里的RGB数据组进行分解
y = 180 #y坐标  x*y = 行数

rgb1 = [****] #RGB数据
print len(rgb1)/3 #计算有多少组RGB数据
m=0
for i in xrange(0,x):
    for j in xrange(0,y):

        line = rgb1[(3*m):(3*(m+1))]#获取一行
        m+=1
        rgb = line

        im.putpixel((i,j),(int(rgb[0]),int(rgb[1]),int(rgb[2])))#rgb转化为像素
im.show()
im.save("flag.png")
