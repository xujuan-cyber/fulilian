# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/工具使用/tshark使用.md
# TITLE: tshark使用
# CATEGORY: web

import re
from subprocess import PIPE, Popen
import os
import csv


def work(f, pcap_path, rules_name_id):
    # 1：读取数据包
    command = 'tshark.exe -r "' + pcap_path + '" -qz follow,tcp,raw,0'  # 一般只有1个追踪流，此处我只提取tcp流
    # print(command)
    p = Popen(command, stdout=PIPE, stderr=PIPE)
    stdout, stderr = p.communicate()
    # print(stdout)
    # print(stderr)

    # 2：提取出读取到的16进制内容
    regex = r"\\r\\n\w+\\r\\n"  # 编写提取出16进制负载的正则过滤器，面对不同项目支撑时需要调整此内容
    original_hex = re.findall(regex, str(stdout))
    # 少数情况下，一条数据流里面可能出现多个http会话（可能一组访问网站，一组访问ico图标），因此选择original_hex[0]，具体情况具体分析，一般项目支撑的只有一个追踪流（只包含一组会话）
    choice_hex = original_hex[0].replace('\\r\\n', '')

    # 3：封装规则
    # 封装16进制字符
    change_hex = re.findall(".{2}", choice_hex)
    need_hex = " ".join(change_hex)
    # 封装规则
    snort_rule = 'alert tcp any any -> any any (msg:"' + rules_name_id + '''"; flow:to_server; content:"|''' + need_hex + '|"; metadata:service http; sid:' + rules_name_id + '; rev:1;)'
    # return snort_rule
    print(f + '：\t' + snort_rule)
    write.writerow([f, snort_rule])


if __name__ == '__main__':
    print('''
脚本功能: 批量开发IPS规则
注意事项: 
1. 需要把tshark加入到环境变量
2. 此脚本是提取tcp追踪流中第一段内容的16进制，进而封装的规则
3. 脚本会穿透指定文件夹下的所有文件，获取出所有数据包（pcap和pcapng后缀）的绝对路径
''')
    files_path = input('请输入数据包所在文件夹：')
    rules_path = os.path.join(files_path, '规则信息.csv')  # 给出csv格式的结果，方便展示
    file = open(rules_path, 'w', newline='')  # 创建并打开CSV文件
    write = csv.writer(file)
    write.writerow(['数据包名字', '规则内容'])
    rules_name_id = 0  # 规则的名字和id号递增
    for current_folder, list_folders, files in os.walk(files_path):
        for f in files:  # 用来遍历所有的文件，只取文件名，不取路径名
            if f.endswith('pcap') or f.endswith('pcapng'):  # 操作数据包
                file_path = current_folder + '\\' + f  # 获取数据包的绝对路径
                rules_name_id = rules_name_id + 1
                rules_name_id1 = str(rules_name_id)
                work(f, file_path, rules_name_id1)
    file.close()
    print('规则开发完成，请查收导出的结果文件')
