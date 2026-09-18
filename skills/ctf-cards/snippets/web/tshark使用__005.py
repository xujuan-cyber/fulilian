# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/工具使用/tshark使用.md
# TITLE: tshark使用
# CATEGORY: web

import re
from subprocess import PIPE, Popen
import os
from rich.progress import track


def get_ip(pcap_path, f):
    command = 'tshark.exe -r ' + pcap_path + ' -z endpoints,ip -q'
    p = Popen(command, stdout=PIPE, stderr=PIPE)
    stdout, stderr = p.communicate()
    # print(stdout)
    # print(stderr)

    # 提取出ipv4地址，这个时候不必使用严格的ip过滤语法，可以写的很宽泛
    re_rules = r'\d+\x2e\d+\x2e\d+\x2e\d+'
    re_match = re.findall(re_rules, str(stdout))

    # print('数据包：'+f+'，提取出ip：{}个'.format(str(len(re_match))))
    for i in re_match:
        # print(i)
        if i not in all_ip:
            all_ip.append(i)


path = input('请给我一个文件夹，我会获取所有数据包里面的所有IP：')
all_ip = []  # 用来存储所有捕获到的IP

for current_folder, list_folders, files in track(os.walk(path)):
    for f in files:  # 用来遍历所有的文件，只取文件名，不取路径名
        if f.endswith('pcap') or f.endswith('pcapng'):  # 判断文件是不是数据包
            path_f = current_folder + '\\' + f  # 给出数据包的的绝对路径
            get_ip(path_f, f)

print('从所有数据包中提取出IP：{}个'.format(str(len(all_ip))))
for i in all_ip:
    print(i)
# os.system('pause')  # 在脚本中运行时可以删除此行
