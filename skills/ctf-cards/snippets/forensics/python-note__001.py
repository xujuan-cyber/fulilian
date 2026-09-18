# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF常用脚本及工具/python-note.md
# TITLE: python-note
# CATEGORY: forensics

import re
    kk = re.compile(r'\d+')
    kk.findall('one1two2three3four4')
    # 输出['1','2','3','4']
    re.findall(kk,"one123")
    # 输出 [123]
