# pwn-ret2win-01

Remote: nc pwn.challenge.local 9001 (offline corpus: level=static)

经典 ret2win：存在 win() 后门函数，远程栈溢出覆盖返回地址到 win() 即可。

附件：`chall`（ELF x86-64）。静态分析（strings/readelf）层可解。
