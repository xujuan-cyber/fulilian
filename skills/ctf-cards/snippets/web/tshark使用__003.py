# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/工具使用/tshark使用.md
# TITLE: tshark使用
# CATEGORY: web

import re
from subprocess import PIPE, Popen

tshark_path = r"D:\Program Files\Wireshark\tshark.exe"  # 如果没有把tshark加入到环境变量的话，需要手动指定tshark路径
pcap_path = r"C:\Users\25348\Desktop\存储型XSS.pcap"
display_filter = ''  # 设置显示过滤
command = tshark_path + ' -r ' + pcap_path
p = Popen(command, stdout=PIPE, stderr=PIPE)
stdout, stderr = p.communicate()
# print(stdout)
# print(stderr)

# 提取出ipv4地址
re_rules = r'((2(5[0-5]|[0-4]\d))|[0-1]?\d{1,2})(\.((2(5[0-5]|[0-4]\d))|[0-1]?\d{1,2})){3}\s\\xe2\\x86\\x92\s((2(5[0-5]|[0-4]\d))|[0-1]?\d{1,2})(\.((2(5[0-5]|[0-4]\d))|[0-1]?\d{1,2})){3}'
re_match = re.finditer(re_rules, str(stdout))
for i in re_match:
    # print(i)
    i = str(i)
    display_filter = re.sub(r'^.*?match=\'', 'ip.src: ', i)
    display_filter = display_filter.replace("'>", '')
    display_filter = display_filter.replace(r' \\xe2\\x86\\x92 ', '\t——> ip.dst: ')
    print(display_filter)
