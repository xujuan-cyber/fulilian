# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2025_LitCTF_writeup_by_Mini-Venom.md
# TITLE: 2025 LitCTF writeup by Mini-Venom
# CATEGORY: crypto

from Crypto.Util.number import long_to_bytes, inverse

n = 150624321883406825203208223877379141248303098639178939246561016555984711088281599451642401036059677788491845392145185508483430243280649179231349888108649766320961095732400297052274003269230704890949682836396267905946735114062399402918261536249386889450952744142006299684134049634061774475077472062182860181893
e = 65537
c = 22100249806368901850308057097325161014161983862106732664802709096245890583327581696071722502983688651296445646479399181285406901089342035005663657920475988887735917901540796773387868189853248394801754486142362158369380296905537947192318600838652772655597241004568815762683630267295160272813021037399506007505

# Since n is prime, φ(n) = n - 1
phi_n = n - 1
d = inverse(e, phi_n)
m = pow(c, d, n)
flag = long_to_bytes(m)

print(flag.decode())
#LitCTF{ee2c30dfe684f13a6e6c07b9ec90cc2c}
19
942430120937
1394236058532304847090984665696457270451329940554604681101032877003319842642
1576349568926279384369628072261252513038693891801832793244205614823946991510
9031182321353345635660995951808001555621426730805001745903972812720437922952
2534539199629164033610855636022774785947855765161278825011688773880094229014
8741
from z3 import *

def recover_factors_z3(n_val, s_val):
    p = Int('p')
    q = Int('q')

    solver = Solver()
    solver.add(p * q == n_val)
    solver.add(p + q == s_val)
    solver.add(p > 1, q > 1)

    if solver.check() == sat:
        model = solver.model()
        pv = model[p].as_long()
        qv = model[q].as_long()
        return min(pv, qv), max(pv, qv)
    else:
        returnNone

n = 17532490684844499573962335739488728447047570856216948961588440767955512955473651897333925229174151614695264324340730480776786566348862857891246670588649327068340567882240999607182345833441113636475093894425780004013793034622954182148283517822177334733794951622433597634369648913113258689335969565066224724927142875488372745811265526082952677738164529563954987228906850399133238995317510054164641775620492640261304545177255239344267408541100183257566363663184114386155791750269054370153318333985294770328952530538998873255288249682710758780563400912097941615526239960620378046855974566511497666396320752739097426013141       
pplusq = 264904851121137920947287086482326881385752688705374889409196246630630770102009950641809599308303022933372963797747735183944234823071639906681654992838707159246410571356707755892308435202955680710788529503317217548344168832053609281562447929541166386062570844327209330092595380642976752220867037216961082705142     

res = recover_factors_z3(n, pplusq)
if res:
    p, q = res
    phi = (p-1)*(q-1)
    d = inverse(e, phi)
    flag = long_to_bytes(pow(c, d, n))
    print(f"[+] p = {p}")
    print(f"[+] q = {q}")
    print(flag)
from Crypto.Util.number import *
import gmpy2
import itertools

def small_roots(f, bounds, m=1, d=None):
    ifnot d:
        d = f.degree()
        print(d)
    R = f.base_ring()
    N = R.cardinality()
    f /= f.coefficients().pop(0)
    f = f.change_ring(ZZ)
    G = Sequence([], f.parent())
    for i in range(m + 1):
        base = N ^ (m - i) * f ^ i
        for shifts in itertools.product(range(d), repeat=f.nvariables()):
            g = base * prod(map(power, f.variables(), shifts))
            G.append(g)
    B, monomials = G.coefficient_matrix()
    monomials = vector(monomials)
    factors = [monomial(*bounds) for monomial in monomials]
    for i, factor in enumerate(factors):
        B.rescale_col(i, factor)
    B = B.dense_matrix().LLL()
    B = B.change_ring(QQ)
    for i, factor in enumerate(factors):
        B.rescale_col(i, 1 / factor)
    H = Sequence([], f.parent().change_ring(QQ))
    for h in filter(None, B * monomials):
        H.append(h)
        I = H.ideal()
        if I.dimension() == -1:
            H.pop()
        elif I.dimension() == 0:
            roots = []
            for root in I.variety(ring=ZZ):
                root = tuple(R(root[var]) for var in f.variables())
                roots.append(root)
            return roots
    return []

e = 1915595112993511209389477484497
n = 12058282950596489853905564906853910576358068658769384729579819801721022283769030646360180235232443948894906791062870193314816321865741998147649422414431603039299616924238070704766273248012723702232534461910351418959616424998310622248291946154911467931964165973880496792299684212854214808779137819098357856373383337861864983040851365040402759759347175336660743115085194245075677724908400670513472707204162448675189436121439485901172477676082718531655089758822272217352755724670977397896215535981617949681898003148122723643223872440304852939317937912373577272644460885574430666002498233608150431820264832747326321450951
c = 5408361909232088411927098437148101161537011991636129516591281515719880372902772811801912955227544956928232819204513431590526561344301881618680646725398384396780493500649993257687034790300731922993696656726802653808160527651979428360536351980573727547243033796256983447267916371027899350378727589926205722216229710593828255704443872984334145124355391164297338618851078271620401852146006797653957299047860900048265940437555113706268887718422744645438627302494160620008862694047022773311552492738928266138774813855752781598514642890074854185464896060598268009621985230517465300289580941739719020511078726263797913582399
leak = 10818795142327948869191775315599184514916408553660572070587057895748317442312635789407391509205135808872509326739583930473478654752295542349813847128992385262182771143444612586369461112374487380427668276692719788567075889405245844775441364204657098142930

leak = leak << 180
R.<x,y> = PolynomialRing(Zmod(n))
f = e * (leak + x) + (y - 1)
res = small_roots(f,(2^180,2^101),m=1,d=3)
for root in res:
    dp_low = root[0]
    dp = leak + dp_low
    tmp = pow(2,e*dp,n) - 2
    p = gmpy2.gcd(tmp,n)
    q = n // p
    d = inverse(e,(p-1)*(q-1))
    m = pow(c,d,n)
    print(long_to_bytes(m))
def process_file(input_file, output_file):
    with open(input_file, 'rb') as f_in, open(output_file, 'wb') as f_out:
        data = f_in.read()
        i = 0
        while i < len(data) - 3:  # 需要至少4字节: f3 a0 (84/85) XX
            # 检查是否匹配 0xf3 0xa0
            if data[i] == 0xf3 and data[i+1] == 0xa0:
                opcode = data[i+2]
                
                # 确定要加的值
                if opcode == 0x85:
                    add_value = 0xd0
                elif opcode == 0x84:
                    add_value = 0x90
                else:
                    i += 1
                    continue
                
                # 处理下一个字节
                if i + 3 < len(data):
                    original_byte = data[i+3]
                    result_byte = (original_byte + add_value) % 256  # 防止溢出
                    f_out.write(bytes([result_byte]))
                
                i += 4  # 跳过已处理的4字节
            else:
                i += 1

process_file('hidden-word.txt', '2.txt')
print("处理完成！结果字节已保存到2.txt")
import numpy as np
 key_bytes = b'LitCTF2025'
 key_length = len(key_bytes)
 encoded_vector = [
     5776, 15960, 28657, 34544, 40294, 43824, 51825, 53033, 58165, 58514,
     61949, 56960, 53448, 49717, 47541, 45519, 40607, 40582, 38580, 42320,
     41171, 41269, 39370, 44224, 48760, 49558, 48128, 46531, 47088, 46181,
     46707, 46879, 48098, 52047, 53933, 56864, 60564, 64560, 66744, 63214,
     60873, 58245, 55179, 56857, 51532, 44308, 32392, 27577, 19654, 14342,
     11721, 9112, 6625
 ]
 message_length = 44
 equation_count = len(encoded_vector)
 coefficient_matrix = np.zeros((equation_count, message_length), dtype=int)
for col in range(message_length):
     for offset in range(key_length):
         coefficient_matrix[col + offset][col] = key_bytes[offset]

 encoded_array = np.array(encoded_vector)
 decoded_floats, _, _, _ = np.linalg.lstsq(coefficient_matrix, encoded_array, rcond=None)
 decoded_bytes = bytes([round(val) for val in decoded_floats])
print(decoded_bytes)
    #include <stdio.h>
 #include <stdint.h>
 //解密函数
 void decrypt (uint32_t* v, uint32_t* k) {
     uint32_t v0=v[0], v1=v[1], i; 
  uint32_t delta=0x114514;  
  uint32_t sum=delta*32;                 
     uint32_t k0=k[0], k1=k[1], k2=k[2], k3=k[3];   /* cache key */
     for (i=0; i<32; i++) {                         /* basic cycle start */
         v1 -= (k[3] + (v0 >> 5)) ^ (sum+ v0) ^ (k[2] + 16 * v0);
         v0 -= (k[1] + (v1 >> 5)) ^ (sum+ v1) ^ (*k + 16 * v1);
         sum-= 0x114514;
     }                                              /* end cycle */
     v[0]=v0; v[1]=v1;
 }
 void encrypt (uint32_t* v, uint32_t* k) {
     uint32_t v0=v[0], v1=v[1], i; 
  uint32_t delta=0x61C88747;  
  uint32_t sum=-delta*0x40;                 
     uint32_t k0=k[0], k1=k[1], k2=k[2], k3=k[3];   /* cache key */
     for (i=0; i<0x40; i++) {                         /* basic cycle start */
         v1 -= v0 ^ (k [((sum >> 11) & 3)] + sum) ^ (v0 + ((v0 >> 5) ^ (v0<<4)));
         sum += 0x61C88747;
         v0 -= v1 ^ (k[ (sum & 3)] + sum) ^ (v1 + ((v1 >> 5) ^ ( v1 <<4 )));
     }                                              /* end cycle */
     v[0]=v0; v[1]=v1;
 }
  int main() {
     uint32_t key[]={0x11223344,0x55667788,0x99AABBCC,0xDDEEFF11};
  uint32_t enc[40]={0x977457FE, 0xDA3E1880, 0xB8169108, 0x1E95285C, 0x1FE7E6F2, 0x2BC5FC57, 0xB28F0FA8, 0x8E0E0644, 0x68454425, 0xC57740D9};
for (size_t i = 0; i < 10; i+=2)
  {
   decrypt(enc+i,key);

  }
  puts((char*)enc);

 }
5 0 RESUME 0
 6 2 LOAD_GLOBAL 1 (NULL + input)
 14 LOAD_CONST 1 ('input your flag > ')
 16 PRECALL 1
 20 CALL 1
 30 LOAD_METHOD 1 (encode)
 52 PRECALL 0
 56 CALL 0
 66 STORE_FAST 0 (user_input)
 8 68 BUILD_LIST 0
 70 STORE_FAST 1 (decrypted)
 9 72 LOAD_GLOBAL 5 (NULL + range)n84 LOAD_GLOBAL 7 (NULL + len)
 96 LOAD_FAST 0 (user_input)
 98 PRECALL 1
 102 CALL 1
 112 PRECALL 1
 116 CALL 1
 126 GET_ITER
 >> 128 FOR_ITER 34 (to 198)
 130 STORE_FAST 2 (i)
 10 132 LOAD_FAST 0 (user_input)
 134 LOAD_FAST 2 (i)
 136 BINARY_SUBSCR
 146 LOAD_CONST 2 (6)
 148 BINARY_OP 10 (-)
 152 STORE_FAST 3 (b)
 11 154 LOAD_FAST 1 (decrypted)
 156 LOAD_METHOD 4 (append)
 178 LOAD_FAST 3 (b)
 180 PRECALL 1
 184 CALL 1
 194 POP_TOP
 196 JUMP_BACKWARD 35 (to 128)
 13 >> 198 BUILD_LIST 0
 200 LOAD_CONST 3 ((85, 84, 174, 227, 132, 190, 207, 142, 77, 24, 235, 236, 231, 213, 138, 153, 60, 29, 241, 241, 237, 208, 144, 222, 115, 16, 242, 239, 231, 165, 157, 224, 56, 104, 242, 128, 250, 211, 150, 225, 63, 29, 242, 169))
 202 LIST_EXTEND 1
 204 STORE_FAST 4 (fflag)
 14 206 BUILD_LIST 0
 208 LOAD_CONST 4 ((19, 55, 192, 222, 202, 254, 186, 190))
 210 LIST_EXTEND 1
 212 STORE_FAST 5 (key_ints)
 16 214 LOAD_CONST 5 (<code object encrypt at 0x0000019CC7F9DFD0, file "d:
codePYTHONIPParser1.py", line 16>)
 216 MAKE_FUNCTION 0
 218 STORE_FAST 6 (encrypt)
 23 220 PUSH_NULL
 222 LOAD_FAST 6 (encrypt)
 224 LOAD_FAST 4 (fflag)
 226 LOAD_FAST 5 (key_ints)
 228 PRECALL 2
 232 CALL 2
 242 STORE_FAST 7 (encrypted_flag)
 25 244 LOAD_FAST 1 (decrypted)
 246 LOAD_FAST 7 (encrypted_flag)
 248 COMPARE_OP 2 (==)
 254 POP_JUMP_FORWARD_IF_FALSE 17 (to 290)
 26 256 LOAD_GLOBAL 11 (NULL + print)
 268 LOAD_CONST 6 ('Good job! You made it!')
 270 PRECALL 1
 274 CALL 1
 284 POP_TOP
 286 LOAD_CONST 0 (None)
 288 RETURN_VALUE
 28 >> 290 LOAD_GLOBAL 11 (NULL + print)
 302 LOAD_CONST 7 ("Nah, don't give up!")
 304 PRECALL 1
 308 CALL 1
 318 POP_TOP
 320 LOAD_CONST 0 (None)
 322 RETURN_VALUE
Disassembly of <code object encrypt at 0x0000019CC7F9DFD0, file "d:
codePYTHONIPParser1.py", line 16>:
 16 0 RESUME 0
 17 2 BUILD_LIST 0
 4 STORE_FAST 2 (result)
 18 6 LOAD_GLOBAL 1 (NULL + range)
 18 LOAD_GLOBAL 3 (NULL + len)
 30 LOAD_FAST 0 (flag_bytes)
 32 PRECALL 1
 36 CALL 1
 46 PRECALL 1
 50 CALL 1
 60 GET_ITER
 >> 62 FOR_ITER 56 (to 176)
 64 STORE_FAST 3 (i)
 19 66 LOAD_FAST 0 (flag_bytes)
 68 LOAD_FAST 3 (i)
 70 BINARY_SUBSCR
 80 LOAD_FAST 1 (key)
 82 LOAD_FAST 3 (i)
 84 LOAD_GLOBAL 3 (NULL + len)
 96 LOAD_FAST 1 (key)
 98 PRECALL 1
 102 CALL 1
 112 BINARY_OP 6 (%)
 116 BINARY_SUBSCR
 126 BINARY_OP 12 (^)
 130 STORE_FAST 4 (b)
 20 132 LOAD_FAST 2 (result)
 134 LOAD_METHOD 2 (append)
 156 LOAD_FAST 4 (b)
 158 PRECALL 1
 162 CALL 1
 172 POP_TOP
 174 JUMP_BACKWARD 57 (to 62)
 21 >> 176 LOAD_FAST 2 (result)
 178 RETURN_VALUE
a=[85, 84, 174, 227, 132, 190, 207, 142, 77, 24, 235, 236, 231, 213, 138, 153, 60, 29, 241, 241, 237, 208, 144, 222, 115, 16, 242, 239, 231, 165, 157, 224, 56, 104, 242, 128, 250, 211, 150, 225, 63, 29, 242, 169]
b=[19, 55, 192, 222, 202, 254, 186, 190]
for i in range(len(a)):
    a[i] = a[i] ^ b[i % len(b)]
    print(chr(a[i]+6), end='')
