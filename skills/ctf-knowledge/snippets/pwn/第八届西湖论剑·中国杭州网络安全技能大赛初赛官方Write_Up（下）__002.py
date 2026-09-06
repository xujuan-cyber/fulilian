# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（下）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（下）
# CATEGORY: pwn

s = lambda data :sh.send(data)sa = lambda delim,data :sh.sendafter(delim, data)sl = lambda data :sh.sendline(data)sla = lambda delim,data :sh.sendlineafter(delim, data)r = lambda num=4096 :sh.recv(num)rl = lambda keepends=False :sh.recvline(keepends)ru = lambda delims, drop=True :sh.recvuntil(delims, drop)ra = lambda :sh.recvall()sd = lambda data :sh.shutdown(data)ia = lambda :sh.interactive()uu32 = lambda data :
u32(data.ljust(4,''))uu64 = lambda data :
u64(data.ljust(8,''))leak = lambda name,addr :
log.success('{} = {:#x}'.format(name, addr))
def dbg(a=''): gdb.attach(sh, a) pause()
binary = './BitDance'libc_path = './libc.so.6' # '/lib/i386-linux-gnu/libc.so.6' / '/lib/x86_64-linux-gnu/libc.so.6'elf = ELF(binary, checksec=False)
    #context.log_level = 'DEBUG'#context.arch = 'amd64'
def pwn(addr, debug):
global shglobal libc
 libc = elf.libc#libc = ELF(libc_path)

 i = 1while True:if(debug == 1): sh = process(binary)#sh = process(binary,env={"LD_PRELOAD" : libc_path})else: ip = addr.split(':')[0] port = addr.split(':')[1] sh = remote(ip, port)
 ru('Welcome to dance: ') sl('a'*i) data = rl()if data.startswith('Wrong length'): sh.close() i += 1continue print('flag length: ' + str(i))break
if __name__ == "__main__": pwn('localhost:
9999', 0)python#-*- coding=utf-8 -*-from pwn import *from sys import argvimport re
s = lambda data :sh.send(data)sa = lambda delim,data :sh.sendafter(delim, data)sl = lambda data :sh.sendline(data)sla = lambda delim,data :sh.sendlineafter(delim, data)r = lambda num=4096 :sh.recv(num)rl = lambda keepends=False :sh.recvline(keepends)ru = lambda delims, drop=True :sh.recvuntil(delims, drop)ra = lambda :sh.recvall()sd = lambda data :sh.shutdown(data)ia = lambda :sh.interactive()uu32 = lambda data :
u32(data.ljust(4,''))uu64 = lambda data :
u64(data.ljust(8,''))leak = lambda name,addr :
log.success('{} = {:#x}'.format(name, addr))
def dbg(a=''): gdb.attach(sh, a) pause()
binary = './BitDance'libc_path = './libc.so.6' # '/lib/i386-linux-gnu/libc.so.6' / '/lib/x86_64-linux-gnu/libc.so.6'elf = ELF(binary, checksec=False)
context.log_level = 'DEBUG'#context.arch = 'amd64'
def pwn(addr, debug):
global shglobal libc
 libc = elf.libc#libc = ELF(libc_path)
if(debug == 1): sh = process(binary)#sh = process(binary,env={"LD_PRELOAD" : libc_path})else: ip = addr.split(':')[0] port = addr.split(':')[1] sh = remote(ip, port)
 pd = 'a' * 96 sla('Welcome to dance: ', pd)
 ru('Start from 0n') rl()
 index_list = [0]
for i in range(96*8-1): data = rl()
# 匹配目标字符串，其中 {} 内匹配 x30 或 x31 pattern = r'x1bx5bx30x6dx1bx5bx30x3bx33x31x6d(x30|x31)x1bx5bx30x6dx1bx5bx30x3bx33x32x6d'
# 使用 re.search 查找第一个匹配结果 match = re.search(pattern, data)
 index_list.append(match.end() - 30) #前面还有一个这样的标志，所以要减30
 print(index_list) print(list(reversed(index_list)))
if __name__ == "__main__": pwn('localhost:
9999', 0)python#include <stdio.h>#include <stdlib.h>#include <string.h>
unsigned int FindBitSrc(unsigned int* box, unsigned int dwBitIdx, unsigned int dwBitNum){for (int i = 0; i < dwBitNum; i++) {if (box[i] == dwBitIdx) {return i; } }
return -1;}
unsigned int BitDecode(unsigned char* cipher, unsigned int* box, unsigned int count){unsigned char srcBit = cipher[0] >> 7;
unsigned int idx = 0;
unsigned int dwBitNum = count;
unsigned int dwBitSrcIdx;
unsigned char destBit;
unsigned int index = 0;
while (count--) { dwBitSrcIdx = box[index];
 destBit = (cipher[dwBitSrcIdx >> 3] >> (7 - (dwBitSrcIdx & 7))) & 1; cipher[dwBitSrcIdx >> 3] ^= (srcBit ^ destBit) << (7 - (dwBitSrcIdx & 7));
 srcBit = destBit; idx = dwBitSrcIdx; index++; }
return 0;}
unsigned int BitDanceDecode(unsigned char* cipher, unsigned int len){unsigned int box[] = {223, 64, 650, 471, 493, 580, 763, 459, 754, 349, 393, 417, 643, 638, 208, 324, 690, 490, 747, 200, 505, 256, 124, 670, 651, 550, 392, 517, 129, 526, 35, 388, 183, 654, 109, 318, 137, 585, 492, 117, 750, 507, 164, 622, 101, 358, 535, 661, 662, 78, 41, 378, 628, 410, 449, 533, 593, 222, 491, 38, 709, 462, 83, 230, 644, 627, 468, 80, 724, 295, 4, 435, 5, 383, 444, 341, 692, 411, 678, 360, 679, 277, 49, 57, 688, 649, 463, 337, 167, 123, 142, 55, 558, 397, 472, 700, 683, 115, 376, 728, 268, 245, 689, 332, 361, 731, 20, 429, 619, 286, 287, 641, 107, 63, 209, 46, 477, 74, 635, 21, 529, 257, 356, 723, 17, 516, 671, 316, 19, 419, 215, 86, 749, 193, 498, 118, 740, 347, 217, 292, 655, 482, 695, 501, 431, 368, 401, 424, 713, 466, 82, 25, 264, 598, 161, 694, 147, 340, 283, 185, 254, 13, 736, 297, 733, 766, 56, 367, 592, 510, 422, 568, 571, 666, 602, 727, 645, 84, 111, 203, 110, 584, 436, 575, 155, 192, 518, 597, 335, 454, 450, 37, 583, 158, 664, 399, 165, 307, 76, 537, 114, 624, 170, 206, 687, 169, 385, 483, 703, 681, 426, 730, 120, 456, 621, 36, 272, 717, 357, 718, 22, 54, 255, 497, 274, 59, 536, 320, 726, 389, 514, 339, 460, 108, 534, 660, 69, 190, 626, 379, 140, 181, 131, 240, 288, 448, 77, 24, 39, 113, 187, 322, 216, 734, 42, 104, 153, 278, 433, 353, 373, 636, 502, 423, 374, 317, 87, 567, 485, 72, 540, 415, 443, 1, 605, 201, 407, 427, 390, 210, 179, 314, 188, 425, 156, 486, 746, 244, 476, 219, 710, 211, 488, 499, 149, 202, 523, 2, 696, 414, 442, 184, 737, 432, 196, 338, 565, 520, 711, 595, 398, 359, 364, 102, 406, 45, 65, 685, 73, 509, 637, 365, 313, 235, 296, 721, 134, 569, 128, 416, 760, 126, 98, 263, 51, 599, 452, 693, 348, 508, 241, 34, 362, 145, 538, 180, 659, 458, 47, 676, 352, 218, 282, 566, 79, 309, 639, 386, 127, 12, 27, 609, 603, 663, 163, 691, 233, 294, 586, 207, 581, 139, 741, 589, 494, 512, 159, 612, 402, 682, 441, 577, 739, 310, 10, 531, 591, 464, 674, 116, 665, 75, 608, 157, 267, 743, 412, 269, 298, 675, 729, 105, 265, 720, 371, 579, 545, 70, 9, 553, 576, 121, 377, 32, 631, 504, 52, 705, 154, 606, 604, 408, 753, 594, 224, 252, 279, 434, 745, 582, 440, 150, 258, 351, 614, 647, 33, 646, 94, 561, 611, 62, 765, 198, 618, 633, 273, 400, 58, 302, 735, 457, 455, 290, 319, 451, 85, 204, 31, 308, 413, 89, 744, 11, 613, 698, 166, 229, 23, 350, 742, 640, 330, 336, 546, 122, 395, 652, 541, 634, 667, 372, 119, 311, 475, 758, 238, 447, 151, 532, 714, 304, 552, 418, 405, 106, 93, 600, 625, 18, 465, 276, 680, 409, 321, 446, 289, 195, 630, 213, 403, 53, 615, 40, 363, 716, 91, 381, 587, 135, 617, 461, 176, 271, 521, 547, 60, 543, 554, 327, 588, 559, 66, 160, 556, 328, 764, 601, 92, 16, 334, 236, 668, 738, 186, 684, 346, 141, 610, 205, 515, 130, 500, 467, 762, 428, 303, 239, 177, 748, 511, 525, 88, 453, 266, 572, 752, 391, 542, 248, 246, 138, 473, 48, 524, 281, 212, 522, 481, 323, 496, 420, 574, 437, 232, 99, 28, 469, 387, 722, 143, 767, 148, 280, 285, 90, 344, 234, 8, 227, 270, 291, 513, 312, 657, 61, 260, 607, 751, 301, 152, 275, 480, 214, 259, 243, 326, 573, 375, 226, 704, 563, 81, 199, 7, 250, 366, 225, 725, 146, 487, 251, 396, 699, 590, 686, 305, 342, 578, 333, 706, 528, 237, 656, 197, 380, 100, 3, 439, 174, 489, 249, 300, 343, 345, 549, 293, 220, 506, 474, 261, 299, 173, 478, 394, 759, 620, 484, 404, 562, 96, 369, 555, 194, 708, 438, 26, 702, 642, 658, 672, 519, 50, 125, 43, 331, 470, 719, 44, 551, 673, 182, 370, 421, 355, 570, 132, 354, 231, 495, 262, 648, 172, 629, 168, 6, 564, 136, 30, 382, 171, 653, 761, 755, 162, 315, 732, 325, 189, 669, 253, 596, 697, 67, 306, 144, 503, 29, 178, 677, 103, 707, 548, 701, 112, 191, 530, 242, 756, 479, 616, 632, 430, 539, 527, 221, 15, 329, 175, 445, 623, 14, 560, 247, 97, 544, 284, 133, 228, 68, 757, 71, 712, 95, 557, 715, 384, 0};
unsigned int dwBitNum = len * 8; BitDecode(cipher, box, dwBitNum);
return 0;}
int main(){
unsigned char flag[] = {0x0C,0x61,0x48,0x3A,0x01,0x44,0xD2,0x8D,0xCA,0x0B,0xB8,0x02,0xB1,0xC5,0x88,0x64,0x67,0x69,0x26,0x69,0x11,0xC7,0x47,0x1F,0xDC,0xB7,0x0E,0x1A,0x50,0xC3,0x57,0x0D,0x75,0xAF,0x01,0x58,0x14,0xA2,0x0A,0xFF,0xC8,0x8C,0x05,0xD9,0x40,0xF6,0xA3,0x16,0x21,0x5B,0x3D,0xFF,0x59,0xC2,0xFB,0x54,0x83,0x81,0xB4,0x8E,0x6A,0x50,0x1C,0x08,0xA5,0xB8,0xE4,0x4D,0x41,0xA3,0x12,0x00,0xF0,0xC8,0x0A,0x96,0xAA,0x79,0x48,0xF1,0x5B,0x24,0xD0,0x9D,0x75,0xB7,0xA8,0xDA,0x86,0x44,0x37,0x0B,0xB0,0x44,0x24,0x4C,0x00};
unsigned int flag_length = 96; BitDanceDecode(flag, flag_length);printf("%sn", flag);}
