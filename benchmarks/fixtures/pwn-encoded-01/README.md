# pwn-encoded-01

Remote: nc pwn.challenge.local 9004 (offline corpus: level=static)

win() 输出前对 .rodata 数据做单字节 XOR；flag 不以明文出现在二进制中，
需结合反编译产物中的 key 解码。
