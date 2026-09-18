# Reverse 知识卡

> 2024-2026 考点补充：魔改算法识别特征（TEA/RC4/白盒 AES）、反调试绕过、UPX 变种脱壳。

## 常用工具
- 静态：IDA Pro(F5)/Ghidra/Binary Ninja，插件 D-810、FindCrypt、Detect It Easy
- 动态：x64dbg、gdb+pwndbg、strace/ltrace、unicorn/qiling 模拟执行
- Android：JADX、apktool、Frida、objection；Windows：DIE、Scylla、PE-bear
- 其他语言：Go（GoReSym/gopclntab 重建符号）、.NET（dnSpy/ILSpy+de4dot）、Python（pycdc 唯一支持 3.9+；≤3.8 可用 uncompyle6；pyinstxtractor）

## 魔改算法识别（高频）
- TEA/XTEA/XXTEA 识别：delta 魔数 0x9E3779B9（改成任意值也认结构）、uint32 双变量交叉累加、固定轮数循环
- TEA 常改点：delta 值、轮数(16/32/64)、+= 改 ^=、移位 4→其他、key 取用顺序、把解密函数当加密调用
- XXTEA 常改点：MX 公式中的常量与移位、轮数、分组尾部补位逻辑
- RC4 识别：S[256] 初始化(i 循环+swap)、KSA 用 key 轮转取模、PRGA 双指针 i/j、输出 XOR
- RC4 常改点：S 盒初始化公式、j 更新式（j+S[i] 改 j^S[i] 等）、S 盒大小非 256、输出下标 K[S[i]+S[j]] 变形、XOR 改加/减
- 白盒 AES 特征：代码中无 AES S-box/key 常量，但有十几张 256x256 大查找表；输入直接查表迭代 10 轮
- 白盒攻击：DFA 差分故障注入（phoenixGCTool/whitebox_tools）恢复末轮 round key → 倒推主密钥
- AES 识别：S-box 以 0x63/0x7c 开头、Rcon 0x01020408；常改点在轮常量、S 盒替换、MixColumns 列数/轮数
- 万能法：动态调试 dump 中间状态，把可疑变换逐个用 python 复现对拍

## 反调试与反逆向绕过
- ptrace(PTRACE_TRACEME)/TracerPid 检查：patch 返回值、LD_PRELOAD 假 ptrace、改 /proc/self/status
- Windows：IsDebuggerPresent/CheckRemoteDebuggerPresent/PEB.BeingDebugged/NtQueryInformationProcess → patch 或改标志
- 时间类：rdtsc/QueryPerformanceCounter/gettimeofday 差值检测 → patch 跳过或单步时改寄存器
- 异常类：int3/SEH/VEH 自陷 → 让调试器忽略异常交给程序自身 handler
- Android：/proc/self/maps 查 frida/xposed 特征、检测端口 27042 → hook 检测函数返回 false
- 花指令：固定 junk 序列（jz/jnz 成对跳）→ IDA 脚本 NOP 恢复；控制流平坦化 → D-810/deflat 还原
- 软件断点被检测：换硬件断点或单步跟踪；多进程反调试用 gdb follow-fork
- 数据段 CRC 自校验：patch 后同步改校验值，或直接绕过校验函数
- ELF 的 .init_array/构造函数藏检查：先看 init_array 再进 main

## 壳与解包
- UPX：`upx -d` 直接脱；失败即变种（magic "UPX!"/段名 UPX0/UPX1 被改）→ 010 修回特征再 -d
- 手动脱壳：ESP 定律（pushad 后对栈下硬件断点）→ 定位 OEP（大 jmp 跨段）→ dump → Scylla 修 IAT
- Python：pyinstaller 用 pyinstxtractor 解包 → pycdc 反编译；pyc 头被删先补 magic+时间戳
- Android 加固：FRIDA-DEXDump/BlackDex 脱壳；native 层看 JNI_OnLoad 动态注册，直接 IDA 分析 so
- Unity：Il2CppDumper + GameAssembly；Mono 直接 dnSpy 看 Assembly-CSharp.dll
- .NET 混淆：de4dot 先跑再 dnSpy 调试/改 IL
- VMP/Themida 类强壳：别硬脱，动态跟到关键比较点直接拿结果

## 常见考点
- 字符串加密：运行时解密 → 动态 dump 内存或 hook 输出函数拿明文
- VM 题：识别 opcode 表 + dispatch 循环 → 写解释器复跑或 unicorn 模拟
- 自定义校验：逐字符比较循环 → 已知前缀时逐位爆破
- 约束求解：比较逻辑复杂 → 提取为 z3 约束直接解出输入
- SMC/自修改代码：段可写 → 运行后 dump 内存再静态分析
- Go/Rust 大静态文件：先 FindCrypt 找魔数定位算法，别陷标准库；字符串校验注意 UTF-8 多字节切分导致按字节比较错位
- Win32/MFC：输入处理常在 WndProc/WM_CHAR 消息分支里搜

## 常见思路
1. strings 先行：flag、wrong/正确提示、Base64 表、已知魔数（AES S-box 0x63、TEA delta、SHA 常量）
2. DIE 查壳/语言/编译器：Go/Rust/Nim/AutoIt/UPX 各有专用工具
3. 定位输入流 → F5 主逻辑 → 跟变换链 → 每步 python 复现
4. 在 memcmp/strcmp/自定义比较前下断，动态拿中间结果省静态分析
5. 逆不出来别硬刚：找加密函数输入输出对，把原函数反向调用
6. 安卓：jadx 搜字符串/native → 决定 Frida hook 还是 IDA 看 so；重打包后记得 apksigner 重签名

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `NSSCTF{...}`
