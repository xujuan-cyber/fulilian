# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024第四届“网鼎杯”朱雀组_writeup.md
# TITLE: 2024第四届“网鼎杯”朱雀组 writeup
# CATEGORY: crypto

start = 0x140003000
for i in range(0x600):
    PatchByte(start+i, (Byte(start+i)+0x42)&0xff)
# -*- coding: utf-8 -*-
import libnum
 
def decode_base24(ciphertext, code_table):
    """
    Decodes a base24 encoded string using a custom code table.
    
    :
param ciphertext: The base24 encoded string to decode.
    :
param code_table: A string containing all the characters in the base24 code table.
    :
return: The decoded string.
    """
    # 将密文字符串中的每个字符转换为其在码表中的索引
    temp = [code_table.index(char) for char in ciphertext if char in code_table]
    
    # 将索引转换为十进制数
    num = 0
    for i, value in enumerate(temp):
        num += value * (24 ** (len(temp) - i - 1))
    
    # 将十进制数转换为字符串
    decoded_bytes = libnum.n2s(num)
    
    # 解码为可读字符串
    decoded_string = decoded_bytes.decode('utf-8', errors='ignore')
    
    return decoded_string

# 自定义码表
base24_code_table = "4836CR7F9TXGQVWYB2JPHKDM"

# 放入密文
ciphertext = "4FKMKYP497G87QXHBTRJKCGM63XXCC8CDQX39TQPYFY"

# 解码
decoded_string = decode_base24(ciphertext, base24_code_table)

print(decoded_string[::-1])
r = random.getrandbits(1024)
p3 = r
while not is_prime(p3):
    p3 += random.getrandbits(400)
q3 = r
while q3 < p3:
    q3 += random.getrandbits(500)
while not is_prime(p3):
    q3 += random.getrandbits(500)
n3 = p3 * q3
f.write("n3 = {0}n".format(n3))
m1 = p1 * m * m + p2 * m + p3
m2 = q1 * m * m + q2 * m + q3
c1 = pow(m1, e, n)
c2 = pow(m2, e, n)
