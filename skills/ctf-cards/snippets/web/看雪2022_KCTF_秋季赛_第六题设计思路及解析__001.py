# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/看雪2022_KCTF_秋季赛_-_第六题设计思路及解析.md
# TITLE: 看雪2022 KCTF 秋季赛 | 第六题设计思路及解析
# CATEGORY: web

#include <stdio.h>#include <stdlib.h>
unsigned int arrSeed_14725[] = { 15356, 8563 , 9659 , 14347, 11283, 30142, 29542, 18083, 5057 , 5531 , 23391, 21327, 20023, 14852, 4865 , 23820, 16725, 18665, 25042, 24920 };
unsigned int arrSeed_83690[] = { 11190, 27482, 980 , 5419 , 28164, 9548 , 16558, 22218, 6113 , 21959, 13889, 11580, 2625 , 19397, 25139, 8167 , 28165, 3950 , 25496, 27351 };
int my_strlen(const char* StrDest){ return ('' != *StrDest) ? (1 + my_strlen(StrDest + 1)) : 0;}
    #if 0//爆破代码int main(){ int i, j; int isSuccess = 0; for (i = 0; i < 99999; i++) { isSuccess = 1; //printf("0x%08xn", i); srand(i); for (j = 0; j < 20; j++) { if (rand() != arrSeed_14725[j]) { isSuccess = 0; break; } } if (isSuccess != 0) { printf("种子1:[%d]n", i); //break; } } isSuccess = 0; for (i = 0; i < 99999; i++) { isSuccess = 1; //printf("0x%08xn", i); srand(i); for (j = 0; j < 20; j++) { if (rand() != arrSeed_83690[j]) { isSuccess = 0; break; } } if (isSuccess != 0) { printf("种子2:[%d]n", i); //break; } } system("pause"); return 0;}
    #else
//题目程序int main(){ int i = 0; char szBuffer[128] = { 0 }; char szSeed1[6]; unsigned int dwSeed1; char szKCTF[5]; char szSeed2[6]; unsigned int dwSeed2; int isSuccess1; int isSuccess2; int isSuccess3;
 //0-99999 //14725KCTF83690 printf("please input :n"); scanf_s("%s", szBuffer, sizeof(szBuffer) - 1); if (my_strlen(szBuffer) != 14) { printf("errorn"); system("pause"); return 0; }
 szSeed1[5] = ''; for (i = 0; i < 5; i++) { szSeed1[i] = szBuffer[i + 0]; } dwSeed1 = atoi(szSeed1);
 szKCTF[4] = ''; for (i = 0; i < 4; i++) { szKCTF[i] = szBuffer[i + 5]; }
 szSeed2[5] = ''; for (i = 0; i < 5; i++) { szSeed2[i] = szBuffer[i + 5 + 4]; } dwSeed2 = atoi(szSeed2); //printf("%dn", dwSeed1); //14725 //printf("%sn", szKCTF); //KCTF //printf("%dn", dwSeed2); //83690
 isSuccess1 = 1; isSuccess2 = 1; isSuccess3 = 0; srand(dwSeed1); for (i = 0; i < 20; i++) { if (rand() != arrSeed_14725[i]) { isSuccess1 = 0; break; } } srand(dwSeed2); for (i = 0; i < 20; i++) { if (rand() != arrSeed_83690[i]) { isSuccess1 = 0; break; } } if (szKCTF[0] == 'K' && szKCTF[1] == 'C' && szKCTF[2] == 'T' && szKCTF[3] == 'F') { isSuccess3 = 1; }
 if (isSuccess1 != 0 && isSuccess2 != 0 && isSuccess3 != 0) { printf("success : %sn", szBuffer); system("pause"); return 0; } printf("errorn"); system("pause"); return 0;}
    #endif
一
观察程序运行结果
C:
Userssurface>C:
UserssurfaceOneDriveCrackCTFKanxue2022KCTFAutumn6CrackMeCrackMe.exeplease input :
0123456789error请按任意键继续. . . C:
Userssurface>
二
IDA反编译伪代码
int __cdecl main(int argc, const char **argv, const char **envp){ int preValue; // eax unsigned int preValueCopy; // ebx int sufValue; // eax unsigned int sufValueCopy; // edi int *v7; // esi int *v8; // esi char inputSN[128]; // [esp+4h] [ebp-A0h] BYREF char sufStr[8]; // [esp+84h] [ebp-20h] BYREF char preStr[8]; // [esp+8Ch] [ebp-18h] BYREF int v13; // [esp+94h] [ebp-10h] int v14; // [esp+98h] [ebp-Ch] int v15; // [esp+9Ch] [ebp-8h] memset(inputSN, 0, sizeof(inputSN)); printf("please input :n"); scanf_s("%s", inputSN); if ( sub_B91000(inputSN) != 0xE ) goto LABEL_19; preStr[5] = 0; // 字符串截断符：只允许5个字节 *(_DWORD *)preStr = *(_DWORD *)inputSN; preStr[4] = inputSN[4]; preValue = atoi(preStr); v15 = *(_DWORD *)&inputSN[5]; sufStr[5] = 0; // 字符串截断符：只允许5个字节 *(_DWORD *)sufStr = *(_DWORD *)&inputSN[9]; preValueCopy = preValue; sufStr[4] = inputSN[0xD]; sufValue = atoi(sufStr); v13 = 0; sufValueCopy = sufValue; v14 = 1; // 需保证为1 srand(preValueCopy); v7 = dword_B9F000; while ( rand() == *v7 ) // 依次获取的随机值需与内置全局数组相等 { if ( (int)++v7 >= (int)dword_B9F050 ) goto LABEL_7; // 要跳出来。避开 v14=0 } v14 = 0; // 执行了这一步就错LABEL_7: srand(sufValueCopy); v8 = dword_B9F050; while ( rand() == *v8 ) // 依次获取的随机值需与内置全局数组相等 { if ( (int)++v8 >= (int)&dword_B9F0A0 ) goto LABEL_12; // 要跳出来。避开 v14=0 } v14 = 0; // 执行了这一步就错LABEL_12: if ( (_BYTE)v15 == 'K' && *(_WORD *)((char *)&v15 + 1) == 'TC' && HIBYTE(v15) == 'F' )// KCTF v13 = 1; if ( v14 && v13 ) { printf("success : %sn", inputSN); system("pause"); } else {LABEL_19: printf("errorn"); system("pause"); } return 0;}
void __cdecl srand(unsigned int Seed){ *(_DWORD *)(_getptd() + 0x14) = Seed;}
int __cdecl rand(){ int v0; // ecx unsigned int v1; // eax v0 = _getptd(); v1 = 0x343FD * *(_DWORD *)(v0 + 0x14) + 0x269EC3; *(_DWORD *)(v0 + 0x14) = v1; return HIWORD(v1) & 0x7FFF;}
三
整理加密逻辑
if ( sub_B91000(inputSN) != 0xE )
preStr[5] = 0; // 字符串截断符：只允许5个字节*(_DWORD *)preStr = *(_DWORD *)inputSN;preStr[4] = inputSN[4];preValue = atoi(preStr);
v15 = *(_DWORD *)&inputSN[5];
v15 = *(_DWORD *)&inputSN[5];sufStr[5] = 0; // 字符串截断符：只允许5个字节*(_DWORD *)sufStr = *(_DWORD *)&inputSN[9];preValueCopy = preValue;sufStr[4] = inputSN[0xD];sufValue = atoi(sufStr);
srand(preValueCopy);v7 = dword_B9F000;while ( rand() == *v7 ) // 依次获取的随机值需与内置全局数组相等{ if ( (int)++v7 >= (int)dword_B9F050 ) goto LABEL_7; // 要跳出来。避开 v14=0}v14 = 0; // 执行了这一步就错
if ( (_BYTE)v15 == 'K' && *(_WORD *)((char *)&v15 + 1) == 'TC' && HIBYTE(v15) == 'F' )// KCTF
srand(sufValueCopy);v8 = dword_B9F050;while ( rand() == *v8 ) // 依次获取的随机值需与内置全局数组相等{ if ( (int)++v8 >= (int)&dword_B9F0A0 ) goto LABEL_12; // 要跳出来。避开 v14=0}v14 = 0; // 执行了这一步就错
四
编写破解代码
'''日期：2022-11-28作者：htg.心学'''###########################################################seed = 0###初始化种子
def InitSand(sd): global seed seed = sd###获取随机值
def GetSand(): global seed seed = seed * 0x343FD seed = seed & 0xFFFFFFFF seed = seed + 0x269EC3 seed = seed & 0xFFFFFFFF returnValue = seed >> 0x10 returnValue = returnValue & 0x7FFF return returnValue###两个列表preList = [0x00003BFC,0x00002173,0x000025BB,0x0000380B,0x00002C13,0x000075BE,0x00007366,0x000046A3,0x000013C1,0x0000159B,0x00005B5F,0x0000534F,0x00004E37,0x00003A04,0x00001301,0x00005D0C,0x00004155,0x000048E9,0x000061D2,0x00006158]sufList = [0x00002BB6,0x00006B5A,0x000003D4,0x0000152B,0x00006E04,0x0000254C,0x000040AE,0x000056CA,0x000017E1,0x000055C7,0x00003641,0x00002D3C,0x00000A41,0x00004BC5,0x00006233,0x00001FE7,0x00006E05,0x00000F6E,0x00006398,0x00006AD7]#################################################################三部分：XXXXXKCTFYYYYY##第一部分：XXXXX##第二部分：KCTF##第三部分：YYYYY###########################################################preFound = FalsesufFound = Falseprint("寻找第一部分......")for i in range(100000): InitSand(i) preFound = True for a in preList: if GetSand() != a: preFound = False if preFound: print("t找到第一部分：{:05}".format(i)) breakif not preFound: print("Failed!")###########################################################print("寻找第三部分......")for j in range(100000): InitSand(j) sufFound = True for a in sufList: if GetSand() != a: sufFound = False if sufFound: print("t找到第三部分：{:05}".format(j)) breakif not sufFound: print("Failed!") SN = "{:05}KCTF{:05}".format(i,j)print("序列号：{}".format(SN))###########################################################
