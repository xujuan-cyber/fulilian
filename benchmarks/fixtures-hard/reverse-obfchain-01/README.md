# reverse-obfchain-01

一个已 strip 的服务端程序，反编译产物在 `decompiled.c`，运行时读入的载荷
在 `data.bin`。

反编译器保留了两个入口：现役的 `main` 和一个因 ABI 兼容而留下的旧入口。
程序的符号名是反编译器合成的，调用关系是真实的。

`data.bin` 里包着 flag。注意：**能跑出东西不等于跑对了**。

flag 格式：`flag{...}`
