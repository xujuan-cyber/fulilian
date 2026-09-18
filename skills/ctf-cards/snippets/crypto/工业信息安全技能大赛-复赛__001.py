# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/工业信息安全技能大赛-复赛.md
# TITLE: 工业信息安全技能大赛-复赛
# CATEGORY: crypto

import numpy as np
dataset = np.load('./ctf_ciscn_2024.npz', allow_pickle=True)
print(dataset.files)

# ['index', 'input', 'output', 'trace']
import matplotlib.pyplot as plt

trace = dataset['trace'] # 获取trace
num = len(dataset['trace']) # 数量
for x in range(44):
    plt.figure(figsize=(20, 2))
    plt.grid(True)
    plt.plot(trace[x][:
1000]) # 绘制
    plt.show()
for i in range(44):
    diff = 0
    for j in trange(len(dataset['trace'][i])):
        diff += (dataset['trace'][i][j]-avg_trace[j])**2
    print(diff)
from numpy import corrcoef
for i in range(44):  
    print(corrcoef(dataset['trace'][i],avg_trace))
from numpy import corrcoef
for i in range(40):  
    print(dataset['input'][i],corrcoef(dataset['trace'][i],avg_trace)[0][1])
for i in range(0,440,40):
    avg_trace = np.mean(dataset['trace'][i:i+40],axis=0)
    for j in range(i,i+40):
        if corrcoef(dataset['trace'][j],avg_trace)[0][1] < 0.5:
            print(dataset['input'][j])
import numpy as np
from tqdm import trange

sbox = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16)

def intermediate(pt, key):
    return sbox[pt ^ key]

HW = [bin(n).count("1") for n in range(0, 256)]

data = np.load('XA_CTF_AES128.npz')
# print(data.files)
indexs = data['index']
inputs = data['input']
outputs = data['output']
traces = data['trace']
print(indexs.shape, inputs.shape, outputs.shape, traces.shape)
# print(inputs[0])
# print(indexs)

probs = [0] * 16
real_keys = [0] * 16

for idx in range(16):
    maxcpa = [0] * 256
    cpaoutput = [0] * 256

    for kguess in range(0, 256):
        cov = np.zeros(5000)
        var1 = np.zeros(5000)
        var2 = np.zeros(5000)

        out_ = np.zeros(50)
        for i in range(50):
            out_[i] = HW[intermediate(inputs[i][idx], kguess)]

        mean = np.mean(out_, dtype=np.float64)

        power_mean = np.mean(traces, axis=0, dtype=np.float64)

        for i in range(50):
            hdiff = (out_[i] - mean)
            tdiff = traces[i, :] - power_mean
            cov = cov + (hdiff * tdiff) 
            var1 = var1 + hdiff * hdiff
            var2 = var2 + tdiff * tdiff

        cpaoutput[kguess] = cov / np.sqrt(var1 * var2)
        maxcpa[kguess] = max(abs(cpaoutput[kguess]))

    real_keys[idx] = np.argmax(maxcpa)
    probs[idx] = maxcpa[real_keys[idx]]
    print(real_keys[idx], probs[idx])
    
    
110.9666879575026875
2350.9921103599950032
1030.9933051387571794
1570.9927796749760798
1430.9950540930526299
180.989670983422036
1810.9944910157557735
1710.9958740382752966
2320.9931254042443289
510.9952003883763602
1910.9949302416398074
610.9926693309894157
1430.9949600262798161
1510.994798031588125
2390.9952079025158994
2380.9936861450484151
B = -0.15
dataset = dataset['trace'][0]

INDEX=[]
for i in range(len(dataset)):
    if dataset[i] < B:
        INDEX.append(i)
print(INDEX)
B = -0.15
dataset1 = dataset['trace'][0][1500:]

INDEX=[]
for i in range(len(dataset1)):
    if dataset1[i] < B:
        INDEX.append(i)
print(INDEX)

TIMES=[]
time=0
window = 200
for i in range(len(INDEX)-1):
    time += 1
    if INDEX[i+1]-INDEX[i] > window:
        TIMES.append(time)
        time=0
print(TIMES)
from Crypto.Util.number import *

p=7300128238517710772989589842105901599312145546905315623188928456848187437978787042996471536275040577467495423335797942935998701649740292768036532086689143

g = bytes_to_long(b'jx91xfaxcc0}xf9(x8fxf2Yx15x98{xa3x0bx98xedxc7xb3x99xacx8ex85i`xd3x92xdbx03xe6xcfxcdxcbxa5fxa1,xaexf3x16xd6xfeyL"x03x93xcbx19xafx9bdIOg,xd5Rx0c=xb7x96xb5')

key = pow(g,5272,p)

print("[+]",key)
print("[+]",key.bit_length())

c = (b'zxf5xfdVx98xe2vx8amxc9xc3xa7xb6xf5xa1x05q#xb7x9exa0xc3x0ex01x8fx9fx8cxa5xacxaarTtxebx14+9axa3!xbfxbaExd1xbfcb=')

from Crypto.Cipher import AES
import hashlib 
enc = AES.new(key = bytes.fromhex(hashlib.sha256(long_to_bytes(key)).hexdigest()),mode=AES.MODE_CBC,iv=b'x00'*16)

print(enc.decrypt(c))
