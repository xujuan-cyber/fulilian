# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2022年工业信息安全技能大赛“望岳杯”锦标赛_wp.md
# TITLE: 2022年工业信息安全技能大赛“望岳杯”锦标赛 wp
# CATEGORY: crypto

#coding:
utf-8
import binascii
from libnum import n2s,s2n
import base64
def gcd(a, b):
    if a < b:
        a, b = b, a
    while b != 0:
        temp = a % b
        a = b
        b = temp
    return a

def egcd(a, b):
    if a == 0:
        return (b, 0, 1)
    else:
        g, y, x = egcd(b % a, a)
        return (g, x - (b // a) * y, y)

def modinv(a, m):
    g, x, y = egcd(a, m)
    if g != 1:
        raise Exception('modular inverse does not exist')
    else:
        return x % m

p = 1267650600235241044365044382487
q = 1267650600260888172240281085029
e = 65537
# tmp = base64.b64decode("qzogS7X8M3ZOpkUhJJcbukaRduLyqHAPblmabaYSm9iatuulrHcEpBmil7V40N7gbsQXwYx5EBH5r5V2HRcEIOXjgfk5vpGLjPVxBLyXh2DajHPX6KvbFpQ8jNpCQbUNq8Hst00yDSO/6ri9dk6bk7+uyuN0b2K1bNG5St6sCQ4qYEA3xJbsHFvMqtvUdhMiqO7tNCUVTKZdN7iFvSJqK2IHosIf7FqO24zkHZpHi31sYU7pcgYEaGkVaKs8pjq6nbnffr4URfoexZHeQtq5UAkr95zD6WgvGcxaTDKafFntboX9GR9VUZnHePiio7nJ3msfue5rkIbISjmGCAlj+w==")
#  = 
d = modinv(e, (p - 1) * (q - 1))
# c=s2n(tmp)
c = 1566077545968868311749088444723100549024925747577903610033503
    #c = 225031483444634056931067907865853799650197225351377050632290334721073031287701730297815850654473721939907812470206115171738967740183098960272963323728747481560137205796840356532306950935686580268408289864109695494835661414073083573249882362332920722000099781994315336570711188934565379141406727420346806389405536474102730682155998263607095718543239272202402139286809779368710600842078606046563228470023546348908618719147790859257980882643030144242048154566691808688844513142261099020381730517293884263384819159874220288293023868919557980548807831273449743064237407705987056818011286315950476959812697067649075359373253
n = p*q
m=pow(c,d,n)
print n2s(m)
s = '0123456789!@#$%^&*`~()_+-=[]{};:,.<>?/'"\|'
for i in s:
    for j in s:
        for k in s:
            for l in s:
                for m in s:
                    #print(1)
                    md5 = hashlib.md5()
                    c = str(i) + '1_1001_10_600_600_' + str(j) + str(k) + '00' + str(l) + str(m) + '7_202103301539'
                    #print(c)
                    md5.update(c.encode('utf-8'))
                    d = md5.hexdigest()
                    #print(c)
                    if d[:4] == 'b9fd' and d[6:9] =='9d5':
                        print(c)
                        print(d)
