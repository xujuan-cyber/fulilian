# pwn-bof-01

Remote: nc pwn.challenge.local 9001 (offline corpus: level=static)

栈溢出（read 256 into buf[16]），先静态审计缓冲区偏移。

附件：`chall`（ELF x86-64）。静态分析（strings/readelf）层可解。
