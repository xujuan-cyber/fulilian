# Reverse 知识卡

## 常用工具
- IDA Pro / Ghidra, gdb / pwndbg, radare2 / rizin, objdump, readelf, strings, strace, ltrace
- 脱壳：upx -d, 010 Editor, x64dbg, 手动 OEP 查找
- Android: JADX, apktool, Frida, objection

## 常见考点
- **静态分析**: 字符串搜索（`strings`）、交叉引用、伪代码（F5/Decompiler）
- **动态调试**: gdb 断点、寄存器/内存修改绕过、anti-debug 绕过（ptrace, isDebuggerConnected）
- **算法还原**: 识别 AES/RSA/RC4/MD5 常量（S-box、常数表）、花指令、控制流平坦化
- **VM/Obfuscator**: 花指令还原、Ollvm 去混淆、unicorn 模拟执行
- **UPX/ASP 壳**: 脱壳后 dump + 修复 IAT
- **Android**: smali 修改重打包、Frida hook 关键函数、native 层 so 静态注册/JNI

## 常见思路
1. 先 `strings` 搜 flag 行、错误提示、URL、Base64 表
2. IDA F5 分析主函数 → 找输入验证逻辑
3. 跟踪关键比较（memcmp, strcmp, 自定义比较）
4. 边界检查：`ltrace` 看库调用、`strace` 看系统调用
5. 如果在 Windows: 用 x64dbg 或 IDA 远程调试

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`