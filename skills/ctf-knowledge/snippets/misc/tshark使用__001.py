# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/工具使用/tshark使用.md
# TITLE: tshark使用
# CATEGORY: misc

import base64

'''
批量把16进制转为ascii
'''

word = []  # 存储用户输入的内容
while True:
    char = input()
    char = char.strip()
    if char == '':
        continue
        if 'quit' in char:
            break
            word.append(char)
            
            for i in word:
                try:
                    hex_str = i
                    a = str(base64.b16decode(hex_str.upper()))
                    b = a.replace(r"\r\n'", '').replace("b'", '').replace(r'\r\n', '\n')  # 解码规范化之后的
                    print(b)
                    
                    
                except Exception as e:
        pass
