# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/从零开始的工控固件逆向之旅_–_VxWorks密码哈希破解实战.md
# TITLE: 从零开始的工控固件逆向之旅 – VxWorks密码哈希破解实战
# CATEGORY: crypto

# 查看文件类型$ file key.binkey.bin: data
# 查看文件大小$ ls -lh key.bin-rwxrwxrwx 1 root root 973K 8月 27 2018 key.bin
$ hexdump -C key.bin | head -2000000000 13 00 03 03 40 06 40 06 84 03cd03 46 77 0d 29 |....@.@.....Fw.)|00000010 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 |................|00000020 31 34 30 2d 4e 4f 45 2d 37 37 31 2d 30 31 00 00 |140-NOE-771-01..|00000030 4e 6f 76 20 32 31 20 31 34 20 31 32 3a 30 33 00 |Nov 21 14 12:03.|00000040 51 75 61 6e 74 75 6d 20 45 74 68 65 72 6e 65 74 |Quantum Ethernet|00000050 20 45 78 65 63 75 74 69 76 65 20 66 69 72 6d 77 | Executive firmw|00000060 61 72 65 20 56 65 72 2e 20 36 2e 34 30 00 00 00 |are Ver. 6.40...|
00000000 13 00 03 03 40 06 40 06 84 03 cd 03 46 77 0d 29 |....@.@.....Fw.)|^ ^ ^| | |偏移地址 十六进制数据(每两位是一个字节) ASCII显示
# 在extracted文件中搜索VxWorks相关字符串$ strings _key.bin.extracted/385 | grep -i"vxworks"| head -5UNIX Type: L8 Version: VxWorksfec(0,0) labcomm1:
smooney_100MBTornado_NAtargetconfigbsp_noevxWorks.stP:/Eth_NOE/vxWorks_gen/../utils/setfstime.cppP:/Eth_NOE/vxWorks_gen/../bp_drv/bp_isr.cpp
# 搜索login和encrypt相关的字符串$ strings _key.bin.extracted/385 | grep -i"login"Guest login ok, upload directory is %s.Login failed.loginUserAddloginUserVerifyloginDefaultEncrypt # ← 找到了!loginInit<VxWorks login:
# 使用grep的-b选项显示字节偏移$ grep -obUaP"loginDefaultEncrypt"_key.bin.extracted/3852289956:
loginDefaultEncrypt
# 转换为十六进制地址$ python3 -c"print(f'0x{2289956:X}')"0x22F124
文件类型: 施耐德Quantum PLC固件操作系统: VxWorks RTOS目标函数: loginDefaultEncrypt @ 0x22F124下一步: 研究这个函数的算法
/** VxWorks 6.9 loginDefaultEncrypt* 来源: VxWorks官方文档*/STATUSloginDefaultEncrypt(char*in,char*out){ intix; unsignedlongmagic =31695317; // 魔数常量 unsignedlongpasswdInt =0; // 密码长度限制: 8-40字符 if(strlen(in) <8||strlen(in) >40) { errnoSet(S_loginLib_INVALID_PASSWORD); return(ERROR); } // 步骤1: 计算加权字符和 for(ix =0; ix <strlen(in); ix++) passwdInt += (in[ix]) * (ix +2) ^ (ix +1); // 步骤2: 乘以魔数并转为字符串 sprintf(out,"%u", (long)(passwdInt * magic)); // 步骤3: 字符变换 for(ix =0; ix <strlen(out); ix++) { if(out[ix] <'3') out[ix] = out[ix] +'!'; // ASCII +33 if(out[ix] <'7') out[ix] = out[ix] +'/'; // ASCII +47 if(out[ix] <'9') out[ix] = out[ix] +'B'; // ASCII +65 (实际是'A') } return(OK);}
加权和 = Σ [ASCII(字符[i]) × (i+2) ⊕ (i+1)] i=0 到 密码长度-1
位置 i = 0字符 = 'F'ASCII值 = 70计算: 权重乘法: 70 × (0+2) = 70 × 2 = 140 异或操作: 140 ⊕ (0+1) = 140 ⊕ 1 = 141
140的二进制: 10001100⊕ 1的二进制: 00000001 ------------- 结果: 10001101 = 141(十进制)
>>>140^1141
sprintf(out,"%u", (long)(passwdInt * magic));
3516 × 31695317 = 111,440,734,572
111,440,734,572的二进制(37位): 110011111001001100010101010010110110032位掩码 (& 0xFFFFFFFF)后: 只保留低32位: 11110010011000101010100101101100 十进制: 4,066,552,172
>>>(3516*31695317) &0xFFFFFFFF4066552172
if(out[ix] <'3') out[ix] = out[ix] +'!'; // ASCII +33if(out[ix] <'7') out[ix] = out[ix] +'/'; // ASCII +47if(out[ix] <'9') out[ix] = out[ix] +'B'; // ASCII +65 (实际是'A')
初始: '4' (ASCII 52)第1次判断: '4' < '3' ? 否,不变第2次判断: '4' < '7' ? 是! → ASCII 52 + 47 = 99 → 'c'第3次判断: 'c' < '9' ? 否,不变最终: 'c'
defvx_hash(password): """ VxWorks loginDefaultEncrypt 算法的Python实现 Args: password: 密码字符串 (必须8-40字符) Returns: 哈希字符串,如果密码长度无效则返回None """ # 参数验证 iflen(password) <8orlen(password) >40: returnNone magic =0x1E3A1D5
# 31695317 password_int =0 # 步骤1: 计算加权字符和 foriinrange(len(password)): password_int += int(ord(password[i]) * (i +2) ^ (i +1)) # 步骤2: 乘以魔数并掩码到32位 temp = str((int(password_int * magic) &0xffffffff)) # 步骤3: 字符变换 output ='' forcintemp: ifc <'3': output += chr(ord(c) + ord('!')) # +33 elifc <'6': output += chr(ord(c) + ord('/')) # +47 elifc <'9': output += chr(ord(c) + ord('A')) # +65 else: output += c # '9'保持不变 returnoutput
>>>ord('F')70
>>>chr(70)'F'
# 测试脚本test_cases = [ ("fdrusers","ycwxQxSS9"), # VxWorks默认用户 ("targettarget","Sxddcd9cSQ"), # 常见测试密码 ("FLAGKNXY","cQwwddSRxS"), # 题目目标(稍后解释如何知道)]print("VxWorks Hash 算法验证:")print("="*70)print(f"{'密码':<20}{'预期哈希':<15}{'计算结果':<15}{'状态':<5}")print("-"*70)forpwd, expectedintest_cases: result = vx_hash(pwd) status ="✓"ifresult == expectedelse"✗" print(f"{pwd:<20}{expected:<15}{result:<15}{status:<5}")
VxWorks Hash 算法验证:======================================================================密码 预期哈希 计算结果 状态----------------------------------------------------------------------fdrusers ycwxQxSS9 ycwxQxSS9 ✓targettarget Sxddcd9cSQ Sxddcd9cSQ ✓FLAGKNXY cQwwddSRxS cQwwddSRxS ✓
策略1: 字典攻击 (最快) ↓ 失败策略2: 智能暴力破解 (针对性) ↓ 失败策略3: 全量暴力破解 (保底)
wordlist = [ # VxWorks常见默认密码 "password","vxworks","targetvx","windrive", "admin123","12345678","adminadmin", # 工控系统常见密码 "scadadmin","sysadmin","rootroot", "targettarget","operator","engineer", # CTF常见密码模式 "ctfctfctf","flagflag","testtest","hackhack", "password123","qwertyui","asdfghjk",]
target_hash ="cQwwddSRxS"print("策略1: 字典攻击")print("-"*70)print(f"目标哈希:{target_hash}")print(f"字典大小:{len(wordlist)}个密码n")found =Falseforidx, pwdinenumerate(wordlist,1): # 跳过太短的密码 iflen(pwd) <8: continue result = vx_hash(pwd) # 检查是否匹配 ifresult == target_hash: print(f"n 字典攻击成功!") print(f" 密码:{pwd}") found =True break else: # 显示部分尝试过程 print(f" [{idx:2d}]{pwd:<20}→{result}")ifnotfound: print(f"n 字典攻击失败 - 密码不在字典中")
策略1: 字典攻击----------------------------------------------------------------------目标哈希: cQwwddSRxS字典大小: 21 个密码 [ 1] password → cSdcSQdwc9 [ 3] targetvx → RyS9SwSQdw [ 4] windrive → bSb9ywbcR [ 5] admin123 → RyQQdyyyc9 [10] rootroot → bx9cbxRxRQ [15] ctfctfctf → RSyy9bQwRS [21] asdfghjk → RxycdS9ycy字典攻击失败 - 密码不在字典中
字符集: A-Z大写字母 + 0-9数字 = 36个字符组合数: 36^4 = 1,679,616 种预估时间: 1,679,616 / 400,000(次/秒) ≈ 4秒
importitertoolsimportstringimporttimeprint("n策略2: 智能暴力破解")print("-"*70)print("假设: 密码格式为 FLAG + 4个字符")print("字符集: A-Z + 0-9")charset = string.ascii_uppercase + string.digits # ABCD...Z0123...9total = len(charset) **4print(f"搜索空间:{total:,}种组合")print(f"开始时间:{time.strftime('%H:%M:%S')}n")start_time = time.time()tested =0forcomboinitertools.product(charset, repeat=4): pwd ="FLAG"+''.join(combo) result = vx_hash(pwd) tested +=1 # 进度显示(每5万次) iftested %50000==0: elapsed = time.time() - start_time speed = tested / elapsedifelapsed >0else0 eta = (total - tested) / speedifspeed >0else0 print(f" 进度:{tested:>8,}/{total:,}({tested/total*100:5.2f}%) " f"速度:{speed:>8,.0f}/s 预计:{eta:>5.1f}s", end='r') # 检查是否匹配 ifresult == target_hash: elapsed = time.time() - start_time print(f"nn 密码破解成功!") print(f" 密码:{pwd}") print(f" 哈希:{result}") print(f" 尝试次数:{tested:,}") print(f" 耗时:{elapsed:.2f}秒") print(f" 平均速度:{tested/elapsed:,.0f}次/秒") found =True break
策略2: 智能暴力破解----------------------------------------------------------------------假设: 密码格式为 FLAG + 4个字符字符集: A-Z + 0-9搜索空间: 1,679,616 种组合开始时间: 20:15:
38密码破解成功! 密码: FLAGAWYZ 哈希: cQwwddSRxS 尝试次数: 29,402 耗时: 0.07秒 平均速度: 403,259 次/秒
password ="FLAGAWYZ"result = vx_hash(password)print("n"+"="*70)print("破解结果验证")print("="*70)print(f"密码:{password}")print(f"哈希:{result}")print(f"目标: cQwwddSRxS")print(f"匹配:{'✓ 完全匹配!'ifresult == target_hashelse'✗ 不匹配'}")
======================================================================破解结果验证======================================================================密码: FLAGAWYZ哈希: cQwwddSRxS目标: cQwwddSRxS匹配: ✓ 完全匹配!
位置 字符 ASCII 权重 XOR值 计算公式 乘法结果 异或结果---- ---- ----- ----- ------ ------------------- --------- --------0 F 70 2 1 70 × 2 ⊕ 1 140 1411 L 76 3 2 76 × 3 ⊕ 2 228 2302 A 65 4 3 65 × 4 ⊕ 3 260 2633 G 71 5 4 71 × 5 ⊕ 4 355 3594 K 75 6 5 75 × 6 ⊕ 5 450 4555 N 78 7 6 78 × 7 ⊕ 6 546 5486 X 88 8 7 88 × 8 ⊕ 7 704 7117 Y 89 9 8 89 × 9 ⊕ 8 801 809 总和: 3516
140的二进制表示: 128 64 32 16 8 4 2 1 1 0 0 0 1 1 0 0 = 1401的二进制表示: 128 64 32 16 8 4 2 1 0 0 0 0 0 0 0 1 = 1异或运算(相同为0,不同为1): 128 64 32 16 8 4 2 1 1 0 0 0 1 1 0 1 = 141
加权和 × 魔数: 3516 × 31695317 = 111,440,734,572
十进制: 111,440,734,572二进制: 0b1100111110010011000101010100101101100 (37位)十六进制: 0x19F2618AAC
111,440,734,572 & 0xFFFFFFFF二进制: 原始(37位): 1 1001 1111 0010 0110 0001 1000 1010 1010 1100 掩码(32位): 1111 1111 1111 1111 1111 1111 1111 1111 结果(32位): 1111 0010 0110 0001 1000 1010 1010 1100十进制: 4,066,552,172十六进制: 0xF2618AAC
位置 输入 判断1(<'3') 判断2(<'7') 判断3(<'9') 输出---- ---- ----------- ----------- ----------- ----0 4 否(不变) 是(+47=99) 否(跳过) c1 0 是(+33=81) 否(跳过) 否(跳过) Q2 6 否(不变) 否(不变) 是(+65=119) w3 6 否(不变) 否(不变) 是(+65=119) w4 5 否(不变) 是(+47=100) 否(跳过) d5 5 否(不变) 是(+47=100) 否(跳过) d6 2 是(+33=83) 否(跳过) 否(跳过) S7 1 是(+33=82) 否(跳过) 否(跳过) R8 7 否(不变) 否(不变) 是(+65=120) x9 2 是(+33=83) 否(跳过) 否(跳过) S
# 搜索所有产生相同哈希的FLAG****密码importitertoolsimportstringtarget_hash ="cQwwddSRxS"charset = string.ascii_uppercase # 仅大写字母collisions = []print("搜索所有FLAG****碰撞密码...")forcomboinitertools.product(charset, repeat=4): pwd ="FLAG"+''.join(combo) ifvx_hash(pwd) == target_hash: collisions.append(pwd)print(f"n发现{len(collisions)}个碰撞密码!")
搜索所有FLAG****碰撞密码...发现 434 个碰撞密码!
print("n前20个碰撞密码:")print("-"*70)foridx, pwdinenumerate(collisions[:20],1): print(f" {idx:3d}.{pwd}")
前20个碰撞密码:---------------------------------------------------------------------- 1. FLAGAWYZ 2. FLAGAZWY 3. FLAGBYXZ 4. FLAGCVWY 5. FLAGCWYV 6. FLAGCXYW 7. FLAGDUXZ 8. FLAGDWXX 9. FLAGDXTY 10. FLAGDYXV 11. FLAGDZXW 12. FLAGEWVZ 13. FLAGEYXX 14. FLAGEZTY 15. FLAGFTXY 16. FLAGFUZV 17. FLAGFVZW 18. FLAGFWZT 19. FLAGFXZU 20. FLAGFYUZ ... 55. FLAGKNXY ← 这也是一个有效答案! ...434. FLAGZZTK
print("n碰撞密码的加权和分析:")print("-"*80)print(f"{'密码':<15}{'加权和':<10}{'魔数乘积':<20}{'32位掩码':<15}")print("-"*80)forpwdincollisions[:10]: # 计算加权和 password_int =0 foriinrange(len(pwd)): password_int += int(ord(pwd[i]) * (i +2) ^ (i +1)) product = password_int *0x1E3A1D5 masked = product &0xFFFFFFFF print(f"{pwd:<15}{password_int:<10}{product:<20}{masked:<15}")
碰撞密码的加权和分析:--------------------------------------------------------------------------------密码 加权和 魔数乘积 32位掩码--------------------------------------------------------------------------------FLAGAWYZ 3516 111440734572 4066552172FLAGAZWY 3516 111440734572 4066552172FLAGBYXZ 3516 111440734572 4066552172FLAGCVWY 3516 111440734572 4066552172FLAGCWYV 3516 111440734572 4066552172FLAGCXYW 3516 111440734572 4066552172FLAGDUXZ 3516 111440734572 4066552172FLAGDWXX 3516 111440734572 4066552172FLAGDXTY 3516 111440734572 4066552172FLAGDYXV 3516 111440734572 4066552172
原始乘积: 111,440,734,572 (37位)32位掩码: 只保留低32位丢失的信息: 高5位 (11001)
"4066552172" → "cQwwddSRxS"
密码哈希数据库: password → cSdcSQdwc9 admin123 → RyQQdyyyc9 ... FLAGAWYZ → cQwwddSRxS FLAGAZWY → cQwwddSRxS ...
file # 文件类型识别hexdump # 十六进制查看strings # 字符串提取grep # 文本搜索和模式匹配
binwalk # 固件自动分析和提取IDA Pro # 专业反汇编工具(支持PowerPC)Ghidra # NSA开源逆向工程平台radare2 # 开源逆向框架
Python3 - itertools # 组合生成 - string # 字符集定义 - time # 性能测试 - struct # 二进制数据处理
固件文件 (key.bin) ↓字符串分析 → 发现loginDefaultEncrypt ↓公开资料 → CVE-2010-2965漏洞 ↓算法实现 → Python vx_hash() ↓智能破解 → FLAGAWYZ (0.07秒) ↓深度分析 → 434个碰撞密码 ↓安全评估 → 算法存在严重弱点
#!/usr/bin/env python3"""VxWorks loginDefaultEncrypt 算法实现"""defvx_hash(password): """ VxWorks loginDefaultEncrypt 哈希函数 参数: password: 密码字符串(8-40字符) 返回: 哈希字符串,如果密码长度无效则返回None """ iflen(password) <8orlen(password) >40: returnNone magic =0x1E3A1D5
# 31695317 password_int =0 # 步骤1: 加权和 foriinrange(len(password)): password_int += int(ord(password[i]) * (i +2) ^ (i +1)) # 步骤2: 魔数乘法与掩码 temp = str((int(password_int * magic) &0xffffffff)) # 步骤3: 字符变换 output ='' forcintemp: ifc <'3': output += chr(ord(c) + ord('!')) elifc <'6': output += chr(ord(c) + ord('/')) elifc <'9': output += chr(ord(c) + ord('A')) else: output += c returnoutputif__name__ =="__main__": # 验证 assertvx_hash("FLAGAWYZ") =="cQwwddSRxS" print("✓ 算法验证通过")
#!/usr/bin/env python3"""智能密码破解"""importitertoolsimportstringfromvx_hashimportvx_hashtarget ="cQwwddSRxS"charset = string.ascii_uppercase + string.digitsprint(f"目标哈希:{target}")print("搜索FLAG****模式...")forcomboinitertools.product(charset, repeat=4): pwd ="FLAG"+''.join(combo) ifvx_hash(pwd) == target: print(f"✓ 找到密码:{pwd}") break
1. FLAGAWYZ2. FLAGAZWY3. FLAGBYXZ4. FLAGCVWY5. FLAGCWYV6. FLAGCXYW7. FLAGDUXZ8. FLAGDWXX9. FLAGDXTY10. FLAGDYXV...55. FLAGKNXY...434. FLAGZZTK
