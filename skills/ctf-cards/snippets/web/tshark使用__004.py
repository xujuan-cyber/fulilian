# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/工具使用/tshark使用.md
# TITLE: tshark使用
# CATEGORY: web

import re
from subprocess import PIPE, Popen

# tshark_path = r"D:\Program Files\Wireshark\tshark.exe"  # 如果没有把tshark加入到环境变量的话，需要手动指定tshark路径
pcap_path = r"C:\Users\25348\Desktop\testnew.pcap"
command = 'tshark.exe -r ' + pcap_path + ' -z endpoints,ip -q'
display_filter = ''  # 设置显示过滤
all_ip = []  # 用来存储获得到的ip
p = Popen(command, stdout=PIPE, stderr=PIPE)
stdout, stderr = p.communicate()
# print(stdout)
# print(stderr)

# 提取出ipv4地址，这个时候不必使用严格的ip过滤语法，可以写的很宽泛
re_rules = r'\d+\x2e\d+\x2e\d+\x2e\d+'
re_match = re.findall(re_rules, str(stdout))
print('提取出ip：{}个'.format(str(len(re_match))))
for i in re_match:
    print(i)
