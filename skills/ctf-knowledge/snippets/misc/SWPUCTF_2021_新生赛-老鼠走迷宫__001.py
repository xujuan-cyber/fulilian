# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/SWPUCTF_2021_新生赛-老鼠走迷宫.md
# TITLE: SWPUCTF 2021 新生赛-老鼠走迷宫
# CATEGORY: misc

#!/usr/bin/env python
# visit https://tool.lu/pyc/ for more information
# Version: Python 3.7

import random
import msvcrt
(row, col) = (12, 12)
(i, j) = (0, 0)
maze = [
 [
 1,
 0,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1],
 （……省略，参考源文章）print('Mice walk in a maze: wasd to move,q to quit')
print("flag is the shortest path's md5,example:if the shortest path is wasdsdw,the flag is md5('wasdsdw')")
(i, j) = (0, 1)
n = 0
while i == row * 2 and j == col * 2 - 1:
 print('ohhhh!!!!you did it')
 break
 print('your position:({},{})'.format(i, j))
 inp = msvcrt.getch()
 n += 1
 ti = i
 tj = j
 if b'a' == inp and i > 0:
 tj -= 1
 elif b'w' == inp and j > 0:
 ti -= 1
 elif b's' == inp and j < row * 2:
 ti += 1
 elif b'd' == inp and i < col * 2:
 tj += 1
 elif b'q' == inp:
 exit('bye!!')
 else:
 print('What???')
 if maze[ti][tj] == 1:
 print(random.choice([
 'no wayy!!',
 "it's wall",
 'nop']))
 continue
 elif maze[ti][tj] == 0:
 print(random.choice([
 'nice!!',
 'yeah!!',
 'Go on']))
 i = ti
 j = tj
 return None
#!/usr/bin/env python
# visit https://tool.lu/pyc/ for more information
# Version: Python 3.7

import random
import msvcrt
(row, col) = (12, 12)
(i, j) = (0, 0)
maze = [
 [
 1,
 0,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1,
 1],
 （……省略，参考源文章）for row in maze:
 print(row)
print('Mice walk in a maze: wasd to move,q to quit')
print("flag is the shortest path's md5,example:if the shortest path is wasdsdw,the flag is md5('wasdsdw')")
(i, j) = (0, 1)
n = 0
while i == row * 2 and j == col * 2 - 1:
 print('ohhhh!!!!you did it')
 break
 print('your position:({},{})'.format(i, j))
 inp = msvcrt.getch()
 n += 1
 ti = i
 tj = j
 if b'a' == inp and i > 0:
 tj -= 1
 elif b'w' == inp and j > 0:
 ti -= 1
 elif b's' == inp and j < row * 2:
 ti += 1
 elif b'd' == inp and i < col * 2:
 tj += 1
 elif b'q' == inp:
 exit('bye!!')
 else:
 print('What???')
 if maze[ti][tj] == 1:
 print(random.choice([
 'no wayy!!',
 "it's wall",
 'nop']))
 continue
 elif maze[ti][tj] == 0:
 print(random.choice([
 'nice!!',
 'yeah!!',
 'Go on']))
 i = ti
 j = tj
dirs = [(0, 1), (1, 0), (0, -1), (-1, 0)] # 当前位置四个方向的偏移量
path = [] # 存找到的路径

def mark(maze, pos): # 给迷宫maze的位置pos标"2"表示“倒过了”
 maze[pos[0]][pos[1]] = 2

def passable(maze, pos): # 检查迷宫maze的位置pos是否可通行
 return maze[pos[0]][pos[1]] == 0

def find_path(maze, pos, end):
 mark(maze, pos)
 if pos == end:
 print(pos, end=" ") # 已到达出口，输出这个位置。成功结束
 path.append(pos)
 return True
 for i in range(4): # 否则按四个方向顺序检查
 nextp = pos[0] + dirs[i][0], pos[1] + dirs[i][1]
 # 考虑下一个可能方向
 if passable(maze, nextp): # 不可行的相邻位置不管
 if find_path(maze, nextp, end): # 如果从nextp可达出口，输出这个位置，成功结束
 print(pos, end=" ")
 path.append(pos)
 return True
 return False

def see_path(maze, path): # 使寻找到的路径可视化
 for i, p in enumerate(path):
 if i == 0:
 maze[p[0]][p[1]] = "E"
 elif i == len(path) - 1:
 maze[p[0]][p[1]] = "S"
 else:
 maze[p[0]][p[1]] = 3
 print("n")
 for r in maze:
 for c in r:
 if c == 3:
 print('33[0;31m' + "*" + " " + '33[0m', end="")
 elif c == "S" or c == "E":
 print('33[0;34m' + c + " " + '33[0m', end="")
 elif c == 2:
 print('33[0;32m' + "#" + " " + '33[0m', end="")
 elif c == 1:
 print('33[0;;40m' + " " * 2 + '33[0m', end="")
 else:
 print(" " * 2, end="")
 print()

if __name__ == '__main__':
 maze = [
 [1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
 [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1],
 [1, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1],
 [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1],
 [1, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1],
 [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
 [1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 1, 1, 1, 0, 1],
 [1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1],
 [1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1],
 [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1],
 [1, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1],
 [1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
 [1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1],
 [1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1],
 [1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1],
 [1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1],
 [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1],
 [1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
 [1, 0, 1, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1],
 [1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1],
 [1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1],
 [1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
 [1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1],
 [1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1],
 [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]]

 start = (0, 1)
 end = (24, 23)
 find_path(maze, start, end)
 see_path(maze, path)
