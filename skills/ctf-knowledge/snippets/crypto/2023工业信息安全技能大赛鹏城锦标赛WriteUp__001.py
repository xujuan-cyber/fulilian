# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2023工业信息安全技能大赛鹏城锦标赛WriteUp.md
# TITLE: 2023工业信息安全技能大赛鹏城锦标赛WriteUp
# CATEGORY: crypto

# https://archives.sector.ca/presentations17/Eric-Evenchick-REAutoDiag.pdf
with open('./candump.log', 'r') as f:
    fr = f.read()
data = [x.split(' ')[2].split('#')[1] for x in fr.split('n')[:-1]][10: -4]
    #data = ''.join([x[2:].split('7D')[0] for x in data])
key = ''
for i in range(len(data)):
    #print(i, data[i], bytes.fromhex(data[i][2:]))
    if '7D' in data[i]:
        tmp = data[i].split('7D')   # ????
        key += tmp[0][2:] + '4242' + tmp[1][2:]
    else:
        key += data[i][2:]

import base64
key = bytes.fromhex(key)
print(key.decode())
print(base64.b64decode(b''.join(key.split(b'n')[1:-1])).hex())

n = 460657813884289609896372056585544172485318117026246263899744329237492701820627219556007788200590119136173895989001382151536006853823326382892363143604314518686388786002989248800814861248595075326277099645338694977097459168530898776007293695728101976069423971696524237755227187061418202849911479124793990722597
# factorDB
p = 15991846970993213322072626901560749932686325766403404864023341810735319249066370916090640926219079368845510444031400322229147771682961132420481897362843199
q = 28805791771260259486856902729020438686670354441296247148207862836064657849735343618207098163901787287368569768472521344635567334299356760080507454640207003
assert p * q == n

# https://github.com/RsaCtfTool/RsaCtfTool/issues/304
e = 354611102441307572056572181827925899198345350228753730931089393275463916544456626894245415096107834465778409532373187125318554614722599301791528916212839368121066035541008808261534500586023652767712271625785204280964688004680328300124849680477105302519377370092578107827116821391826210972320377614967547827619

c = 49204714858589959506425439175649050431712689077552080337419353493097408019421214668787900602380476464749282877075822584378756221224722944848685142270406954588911362016685713099949058708493084032575436033859064998703946175169856560687276793237892152502134788316092552043085946089668969326209343517732349235471

import libnum
d = libnum.invmod(e, (p-1)*(q-1))
m = pow(c, d, n)
flag = libnum.n2s(m)
print(d)
print(flag)
import base64
c = '636d526a5a7942305a6d4a6f49484931655563676248413553534243616b306764455a6f516c513264576767655464705369425263316f67596d684e49413d3d'
b = bytes.fromhex(c)
b = base64.b64decode(b)
print(b)
# b'rdcg tfbh r5yG lp9I BjM tFhBT6uh y7iJ QsZ bhM '

    #a = 'fgtongyuan'
a = 'FGTONGYUAN'
# https://www.cnblogs.com/0yst3r-2046/p/11948836.html
with open('./can_log.asc', 'r') as f:
    fr = f.read().split('n')
data = []
for fi in fr:
    fi = fi.split(' ')
    if len(fi) == 42:
        data += [(fi[6], fi[24], ''.join(fi[25: 32]))]
    if len(fi) == 41:
        data += [(fi[5], fi[23], ''.join(fi[24: 31]))]

res = []
tmp = ''
for d in data:
    id, tp, data = d
    if id == '7B0':     # ack
        continue
    elif tp[0] == '0':    # signal
        continue
    elif tp == '10':    # first
        res += [tmp]
        tmp = data[4:]
    elif tp[0] == '2':
        tmp += data
    else:
        print('???')
        print(tp, data)

test = ''
for r in res[3:]:
    print(r, len(r))
    test += r[2:-4]
print(test)
with open('./out.bin', 'wb') as f:
    f.write(bytes.fromhex(test))

# https://zhuanlan.zhihu.com/p/140896045
flag{canoecr7-zd9h-1emi-or8m-f8vm2od81nfk}
flag{3dad13db-cb48-495d-b023-3231d80f1713}
def getFlag(s):
    enc3 = base64.b32decode(s)
    enc2 = [(x^37)-37 for x in enc3]
    enc1 = [(x-37)^73 for x in enc2]
    print(bytes(enc1))

getFlag('KGRFYWPN43TE5FXG5SLOA7EWPRZJNZXHS3TODFXG4KLONYUW43TFW===')
# b'ctf{700h 06 2F FD 01 03 04 04 00}'
for i in range(50):
 if i % 5 != 3 and i % 17 == 8:
  break
print(0xcaffe, i, "tboxcloud")
import pyshark
import base64

cap = pyshark.FileCapture('easyping.pcap', display_filter="ip.src==192.168.3.73")
flag = []
for packet in cap:
    flag.append(len(bytes.fromhex(packet.icmp.data)))
flag = base64.b64decode(bytes(flag))
print(flag)
# b'::\nmongodb:!:
17843:0:
99999:7:::\nubuntu:$6$LhHRomTE$M7C4n84UcFLAG{xx31Dsrsb_Fu1_Success1}::'
import ctypes

def tea_decrypt(v, k):
    delta = 0x11451419
    teasum = ctypes.c_uint32(delta * 32)
    v0 = ctypes.c_uint32(v[0])
    v1 = ctypes.c_uint32(v[1])
    for i in range(32):
        v1.value = v1.value - (((v0.value<<3) + k[2]) ^ (v0.value + teasum.value) ^ ((v0.value>>6) + k[3]))
        v0.value = v0.value - (((v1.value<<3) + k[0]) ^ (v1.value + teasum.value) ^ ((v1.value>>6) + k[1]))
        teasum.value -= delta
    v[0] = v0.value
    v[1] = v1.value
    return v

from ida_bytes import *
addr = 0x2000
for i in range(0x1197, 0xDB6, -4):
    key = [i + x for x in range(0, 8, 2)]
    print(key)
    v = [get_dword(addr+i), get_dword(addr+i+4)]
    tea_decrypt(v, key)
    patch_dword(addr+i, v[0])
    patch_dword(addr+i+4, v[1])
from Crypto.Cipher import AES

key = b'rGzuwTc31NRH9tsT'
with open('flag', 'r') as f:
 dst = f.read()
aes = AES.new(key, AES.MODE_ECB)
dst = bytes.fromhex(dst)
print(aes.decrypt(dst))
# b'flag{hsOrB3IMqfoMUg0E}nnnnnnnnnn'
