# pwn-secret-check-01

Remote: nc pwn.challenge.local 9001 (offline corpus: level=static)

程序校验输入为内置密钥后打印 flag：密钥与 flag 均可通过 strings 静态获取。

附件：`chall`（ELF x86-64）。静态分析（strings/readelf）层可解。
