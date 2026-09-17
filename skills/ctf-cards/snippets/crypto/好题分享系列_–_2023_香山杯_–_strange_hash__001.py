# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/好题分享系列_–_2023_香山杯_–_strange_hash.md
# TITLE: 好题分享系列 – 2023 香山杯 – strange_hash
# CATEGORY: crypto

from os import urandom
import socketserver
from Crypto.Util.number import *
import random
from hashlib import sha256
import string
from secret import flag

p = 18446744073709551557
M = [[8, 56, 280], [18446744073709551543, 18446744073709551467, 18446744073709551123], [7, 35, 155]]
ConInv = [0x39a3f978106bac2d,0x2940e055f4a33725,0xfda9a7a293fb5bc9]
Con = [[0x9c52c2de7a9373c4,0xf2135cb886d0fa21,0x957df7f3cd4879e9], [0xd54f837d2738d717,0x400ddf1ffaae436d,0xc2abb601d9a26b07], [0x1904359f1deb3495,0xc21aa09ba52b157b,0x3d45525db1b19a0c], [0xed66cf26a65afc73,0x1cee569b29ffa476,0x3da45abf4304849], [0x1c1a642fa0f3d96d,0x59a1c4fbb96aec86,0xa18e9ca93163f63d], [0x9621ec9fbcb402be,0xd69468353c31bee0,0x50655b3f20fee3b8], [0x109cde7a61c2c195,0x5ebbd9e98be60c59,0x334d2d15f6e43190], [0x47af2b0d63901977,0x67ace097bf8c6f34,0xb87da3296b70d64b], [0x52d6344b38f49899,0xad5773add31420e1,0xecd0b7480f8c8095], [0xe2afb6d20f5decda,0xb1767d8be7d1371,0x902fd6806a0ef4db]]
assert len(Con) == 10
Inv = inverse(3, p-1)
Round = 2

def add(x, y):
    return [(a + b)%p for a, b in zip(x, y)]

def multiply(x, M):
    result = []
    for i in range(len(M[0])):
        temp = 0
        for j in range(len(x)):
            temp += x[j] * M[j][i]
        result.append(temp%p)
    return result

def Rescue_Prime(R, P):
    X = add(P, ConInv)
    Y = [0, 0, 0]
    Z = [0, 0, 0]
    U = [0, 0, 0]
    for r in range(R):
        for i in range(3):
            Y[i] = pow(X[i], 3, p)
            
        Z = add(Con[2*r%10], multiply(Y, M))
        
        for i in range(3):
            U[i] = pow(Z[i], Inv, p)

        X = add(Con[(2*r+1)%10], multiply(U, M))
    return X

class Task(socketserver.BaseRequestHandler):
    encrypt_history = []

    def __init__(self, *args, **kargs):
        super().__init__(*args, **kargs)

    def proof_of_work(self):
        random.seed(urandom(8))
        proof = ''.join([
            random.choice(string.ascii_letters + string.digits)
            for _ in range(20)
        ])
        digest = sha256(proof.encode()).hexdigest()
        self.send_line(
            str.encode(("sha256(XXXX + %s) == %s" % (proof[4:], digest))))
        self.send_line(str.encode('Give me XXXX:'))
        x = self.request.recv(10)
        x = (x.strip()).decode("utf-8")
        if len(x) != 4 or sha256(
                (x + proof[4:]).encode()).hexdigest() != digest:
            return False
        return True

    def send_line(self, msg):
        try:
            self.request.sendall(msg + b'n')
        
except:
            pass

    def read_line(self):
        body = b""
        while True:
            ch = self.request.recv(1)
            if ch == b"n":
                break
            body = body + ch
        return body

    def timeout_handler(self, signum, frame):
        raise TimeoutError

    def handle(self):
        try:
            if not self.proof_of_work():
                self.dosend(b'You must pass the PoW!')
                self.request.close()
            self.send_line(b'Send your input:')
            input_str = self.read_line().decode()
            num_tuple = tuple(map(int, input_str.strip('()').split(',')))  
            if num_tuple[-1] != 0:
                self.send_line(b'The third number is not zero!')
                self.request.close()
            output = Rescue_Prime(Round, num_tuple)
            if output[-1] == 0:
                self.send_line(b'congratulate! Here is the flag:')
                self.send_line(flag)
            else:
                self.send_line(b'Oops! Find collision failed.')
                self.request.close()
        
except:
            self.send_line(b'What's wrong???')
            self.request.close()

class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

HOST, PORT = '0.0.0.0', 9999
server = ThreadedServer((HOST, PORT), Task)
server.allow_reuse_address = True
server.serve_forever()
ConInv = matrix(Zmod(p),ConInv)
Con = matrix(Zmod(p),Con)
M = matrix(Zmod(p),M)
output = vector(Zmod(p),[1, 1, 0])

tmp = output - Con[3]
tmp = tmp * M^-1
tmp = tmp * diagonal_matrix(tmp)^2
tmp = tmp - Con[2]
tmp = tmp * M^-1
tmp = tmp * diagonal_matrix(tmp)^(Inv-1)
tmp = tmp - Con[1]
tmp = tmp * M^-1
tmp = tmp * diagonal_matrix(tmp)^2
tmp = tmp - Con[0]
tmp = tmp * M^-1
tmp = tmp * diagonal_matrix(tmp)^(Inv-1)
input = tmp - ConInv[0]
