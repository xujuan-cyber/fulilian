# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（上）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（上）
# CATEGORY: crypto

import
csv_headers = ['userid', 'name', 'idcard', 'phone']
capture = pyshark.FileCapture('data.pcapng', display_filter='http')
# 打开 CSV 文件并写入数据with open('data1.csv', mode='w', newline='', encoding='utf-8') as csvfile: writer = csv.DictWriter(csvfile, fieldnames=csv_headers) writer.writeheader()
 for packet in capture: if 'HTTP' in packet: # 仅处理HTTP请求包 http_layer = packet.http # print(http_layer) # 检查是否为POST请求且包含请求体 if hasattr(http_layer, 'request_method') and http_layer.request_method == 'POST': # 提取URL中的userid url = http_layer.request_uri userid = url.split('userid=')[1].split(' ')[0] if 'userid=' in url else None # 提取POST数据 if hasattr(http_layer, 'file_data'): post_data_hex = http_layer.file_data post_data = bytes.fromhex(post_data_hex.replace(":", "")).decode() # print(post_data) json_data = json.loads(post_data) # 提取name, idcard, phone name = json_data.get('name', None) idcard = json_data.get('idcard', None) phone = json_data.get('phone', None) # 写入CSV文件 writer.writerow({ 'userid': userid, 'name': name, 'idcard': idcard, 'phone': phone })
pythonimport csv
with open('data1.csv', mode='r', encoding='utf-8') as infile: reader = csv.DictReader(infile) data = list(reader)
# 使用集合去重unique_data = { (row['userid'], row['name'], row['idcard'], row['phone']) for row in data }
# 将集合转换为列表并按userid排序sorted_data = sorted(unique_data, key=lambda x: int(x[0]))
# 写入新的 CSV 文件with open('data2.csv', mode='w', newline='', encoding='utf-8') as outfile: writer = csv.writer(outfile) writer.writerow(['userid', 'name', 'idcard', 'phone']) for row in sorted_data: writer.writerow(row)
pythonfrom Crypto.PublicKey import DSAfrom Crypto.Signature import DSSfrom Crypto.Hash import SHA256import csvimport base64
with open('data-sign.csv', 'r', encoding='utf-8') as f: reader = csv.reader(f) header = next(reader) sign_data = {row[0]: row for row in reader}
with open('data2.csv', 'r', encoding='utf-8') as f: reader = csv.reader(f) header = next(reader) all_data = list(reader)
# 保存验证结果with open('data-unmodify.csv', 'w', encoding='utf-8', newline='') as f_undo, open('data-modify.csv', 'w', encoding='utf-8', newline='') as f_do:
 writer_undo = csv.writer(f_undo) writer_do = csv.writer(f_do)
 writer_undo.writerow(header) writer_do.writerow(header)
 for row in all_data: userid, name, idcard, phone = row
 # Load DSA public key public_key_path = f'public/public-{str(userid).zfill(4)}.pem' with open(public_key_path, 'r') as f: public_key = DSA.import_key(f.read())
 # Get signatures from data-sign.csv sign_row = sign_data.get(userid) if not sign_row: writer_do.writerow(row) continue
 _, name_signature_base64, idcard_signature_base64, phone_signature_base64 = sign_row
 # Verify name name_hash = SHA256.new(name.encode()) name_signature = base64.b64decode(name_signature_base64) try: DSS.new(public_key, 'fips-186-3').verify(name_hash, name_signature) name_verified = True 
except (ValueError, TypeError): name_verified = False
 # Verify idcard idcard_hash = SHA256.new(idcard.encode()) idcard_signature = base64.b64decode(idcard_signature_base64) try: DSS.new(public_key, 'fips-186-3').verify(idcard_hash, idcard_signature) idcard_verified = True 
except (ValueError, TypeError): idcard_verified = False
 # Verify phone phone_hash = SHA256.new(phone.encode()) phone_signature = base64.b64decode(phone_signature_base64) try: DSS.new(public_key, 'fips-186-3').verify(phone_hash, phone_signature) phone_verified = True 
except (ValueError, TypeError): phone_verified = False
 if name_verified and idcard_verified and phone_verified: writer_undo.writerow(row) else: writer_do.writerow(row)
