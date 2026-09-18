# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2025西湖论剑决赛misc全解.md
# TITLE: 2025西湖论剑决赛misc全解
# CATEGORY: misc

import os
import binascii
def listfindname(directory):
    folders = [os.path.join(directory, f) for f in os.listdir(directory) if os.path.isdir(os.path.join(directory, f))]
    folders.sort(key=os.path.getmtime)
    
    zipp = "".join(os.path.basename(folder)[0] for folder in folders)
    

    zip_data = binascii.unhexlify(zipp)

    with open('flag.zip', 'wb') as f:
        f.write(zip_data)
    
directory = "The flag is here"
listfindname(directory)
import base64
from Crypto.Cipher import AES

def aes_decode(data, key):
    try:
        aes = AES.new(str.encode(key), AES.MODE_CBC, iv=b'x00' * 16)  # 假设 IV 是 16 字节 0
        decrypted_text = aes.decrypt(data)
        decrypted_text = decrypted_text[:-(decrypted_text[-1])]  # 去除填充
        return decrypted_text
    
except Exception as e:
        print(f"解密错误: {e}")
        returnNone

def decrypt_file_line_by_line(input_file, output_file, key):
    with open(input_file, "r", encoding="utf-8") as f_in, open(output_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            ifnot line:
                continue
            encrypted_data = base64.b64decode(line)
            decrypted_data = aes_decode(encrypted_data, key)

            if decrypted_data:
                f_out.write(decrypted_data.decode("utf-8") + "n")
                    

if __name__ == '__main__':
    key = '5b4582c9d56b5b33'
    input_file = "encrypted_data.txt"
    output_file = "decrypted_output.txt"
    decrypt_file_line_by_line(input_file, output_file, key)
import base64

def decode_base64_file(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as f_in, open(output_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            ifnot line:
                continue
# 跳过空行
            decoded_bytes = base64.b64decode(line)  # Base64 解码
            decoded_text = decoded_bytes.decode("utf-8", errors="ignore")
            f_out.write(decoded_text + "n")

if __name__ == '__main__':
    input_file = "decrypted_output.txt"
    output_file = "decoded_output1.txt"

    decode_base64_file(input_file, output_file)
from PIL import Image
import numpy as np
import libnum

def rc4_decrypt(data, key):
    try:
        from Crypto.Cipher import ARC4
        cipher = ARC4.new(key.encode('utf-8'))
        return cipher.decrypt(data)
    
except Exception as e:
        print(f"[!] 解密失败: {e}")
        returnNone

def main():
    key = "password"
    img = Image.open("Steganography_challenges0.3.png")
    w, h = img.size
    img_arr = np.array(img)
    
    decrypted_pixels = np.zeros_like(img_arr, dtype=np.uint8)  # 确保数据类型正确
    
    for y in range(h):
        for x in range(w):
            r, g, b = img_arr[y, x]
            rgb_bytes = bytes([r, g, b])
            dec_rgb = rc4_decrypt(rgb_bytes, key)
            ifnot dec_rgb or len(dec_rgb) < 3:
                continue
            decrypted_pixels[y, x] = [dec_rgb[0], dec_rgb[1], dec_rgb[2]]
    
    img1 = Image.fromarray(decrypted_pixels)
    
    img1.save("decrypted_image.png")
    
if __name__ == "__main__":
    main()
from PIL import Image
import numpy as np
from Crypto.Util.number import *
import matplotlib.pyplot as plt
import pywt
import cv2

p = Image.open('flag.png').convert('RGB')
p_data = np.array(p)
R = p_data[:,:,0]
G = p_data[:,:,1].astype(np.float32)
B = p_data[:,:,2].astype(np.float32)

def string_to_bits(s):
    return bin(bytes_to_long(s.encode('utf-8')))[2:].zfill(8 * ((len(s) * 8 + 7) // 8))

def bits_to_string(b):
    n = int(b, 2)
    return long_to_bytes(n).decode('utf-8', 'ignore')

data = R.reshape(-1)%2
print(long_to_bytes(int(''.join([str(i) for i in data]),2)).replace(b'x00',b''))

def extract_qim(block, delta):
    block_flat = block.flatten()
    avg = np.mean(block_flat)
    mod_value = avg % delta
    if mod_value < delta / 4or mod_value > 3 * delta / 4:
        return'0'
    else:
        return'1'

def extract_watermark1(G_watermarked, watermark_length, delta=64):
    watermark_bits = []
    block_size = 8
    k = 0
    for i in range(0, G_watermarked.shape[0], block_size):
        for j in range(0, G_watermarked.shape[1], block_size):
            if k < watermark_length * 8:
                block = G_watermarked[i:i+block_size, j:j+block_size]
                if block.shape != (block_size, block_size):
                    continue
                coeffs = pywt.dwt2(block, 'haar')
                LL, (LH, HL, HH) = coeffs
                bit = extract_qim(LL, delta)
                watermark_bits.append(bit)
                k += 1

    # 将比特序列转换为字符串
    watermark_str = bits_to_string(''.join(watermark_bits))
    return watermark_str

print(extract_watermark1(G,253,8))

def dct2(block):
    return cv2.dct(block.astype(np.float32))

def idct2(block):
    return cv2.idct(block.astype(np.float32))

def svd2(matrix):
    U, S, V = np.linalg.svd(matrix, full_matrices=True)
    return U, S, V

def inverse_svd2(U, S, V):
    return np.dot(U, np.dot(np.diag(S), V))

def extract_watermark2(B_watermarked, B, watermark_length):
    h, w = B_watermarked.shape
    watermark_bits_extracted = []

    bit_index = 0

    for i in range(0, h, 8):
        for j in range(0, w, 8):
            if bit_index >= watermark_length * 8:
                break

            block_wm = B_watermarked[i:i+8, j:j+8]
            block_orig = B[i:i+8, j:j+8]

            dct_block_wm = dct2(block_wm)
            dct_block_orig = dct2(block_orig)

            U_wm, S_wm, V_wm = svd2(dct_block_wm)
            U_orig, S_orig, V_orig = svd2(dct_block_orig)

            delta_S = S_wm[0] - S_orig[0]

            if delta_S == 0:
                watermark_bits_extracted.append('1')
            else:
                watermark_bits_extracted.append('0')

            bit_index += 1

    watermark_bits_extracted = ''.join(watermark_bits_extracted)
    return bits_to_string(watermark_bits_extracted)

B_ori = np.array(Image.open('B.png').convert('L'))
print(extract_watermark2(B, B_ori, 83))
Hey boy, I'm here to help you, now you'ze one step away from successl let me |ell you key:
79557c2d8f94;
import wave

def extract_message(stego_wav):
    with wave.open(stego_wav, 'rb') as wav:
        frames = wav.readframes(wav.getnframes())

    binary_message = ''
    for byte in frames:
        binary_message += str((byte >> 1) & 1)

    message_bytes = []
    for i in range(0, len(binary_message), 8):
        byte = binary_message[i:i+8]
        if byte == '00000000':  # 终止符
            break
        message_bytes.append(int(byte, 2))

    message = ''.join(chr(byte) for byte in message_bytes)
    return message

if __name__ == "__main__":
    stego_file = "恋人を射ち堕とした日.wav"
    hidden_message = extract_message(stego_file)
    print("Hidden Message:", hidden_message)
oSthinggg
