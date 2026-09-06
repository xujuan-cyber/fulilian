# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/冠军Writeup大放送_-_DataCon2022域名体系安全赛道之“NDNS”战队.md
# TITLE: 冠军Writeup大放送 | DataCon2022域名体系安全赛道之“NDNS”战队
# CATEGORY: misc

import csvimport osSLD_Ccount = {}
i=0file_names = os.listdir('./datacon_cdn_basic')for file_name in file_names: i+=1 file_path = os.path.join('./datacon_cdn_basic',file_name) print('Processing with '+ str(i) +' file!') with open(file_path, encoding='utf-8-sig') as f: f_csv = csv.reader(f) #headers = next(f_csv) #headers:['sld_md5', 'all_md5_fqdn', 'request_cnt', 'rtype', 'all_md5_rdata', 'country_code', 'country_name', 'region_name', 'asn_sort'] #['86f066f08908de0c617243cb33081050', '2ddfe6b1ebd12b3d1807eff0274d883c.86f066f08908de0c617243cb33081050', '1', '5', 'ccd4d6df14af7f4215db6b77945fc02a.95074d472f19c7108ee72233cd65f543', 'null', 'null', 'null', '0'] for row in f_csv: if row[3]=='5': if row[4]: sld = row[4].split('.')[-1] if sld in SLD_Ccount: SLD_Ccount[sld] += 1 else: SLD_Ccount[sld] = 1
SLD_Ccount_sorted = dict(sorted(SLD_Ccount.items(), key=lambda x: x[1], reverse=True))
file1 = open('./mydata/SLD_Ccount_sorted.csv', 'w')writer = csv.writer(file1)count_all = 0for k,v in SLD_Ccount_sorted.items(): writer.writerow([k,v]) count_all += vprint(count_all) print('Success!')#共 29581826 条 CNAME 记录
import csvimport os
CDN_list1 = []CDN_fqdn_count = {}fqdn_count = {}
with open('./mydata/SLD_Ccount_sorted.csv', encoding='utf-8-sig') as f: f_csv = csv.reader(f) for row in f_csv: #if int(row[1]) >= 397: CDN_list1.append(row[0])
for sld in CDN_list1: CDN_fqdn_count[sld] = 0
i=0file_names = os.listdir('./datacon_cdn_basic')for file_name in file_names: i+=1 file_path = os.path.join('./datacon_cdn_basic',file_name) print('Processing with '+ str(i) +' file!') with open(file_path, encoding='utf-8-sig') as f: f_csv = csv.reader(f) for row in f_csv: sld = row[0] if sld in CDN_list1: fqdn = row[1] if fqdn in fqdn_count: fqdn_count[fqdn] += 1 else: fqdn_count[fqdn] = 1 CDN_fqdn_count[sld] += 1
CDN_fqdn_count_sorted = dict(sorted(CDN_fqdn_count.items(), key=lambda x: x[1], reverse=True))
file1 = open('./mydata/CDN_fqdn_count_sorted.csv', 'w')writer = csv.writer(file1)count_all = 0for k,v in CDN_fqdn_count_sorted.items(): writer.writerow([k,v]) count_all += vprint(count_all) print('Success!')
import csvimport os
CDN_list1 = []fqdn_region_list = {}fqdn_region_count = {}
with open('./mydata/SLD_Ccount_sorted.csv', encoding='utf-8-sig') as f: f_csv = csv.reader(f) for row in f_csv: CDN_list1.append(row[0])#print(CDN_list1)i=0file_names = os.listdir('./datacon_cdn_basic')for file_name in file_names: i+=1 file_path = os.path.join('./datacon_cdn_basic',file_name) print('Processing with '+ str(i) +' file!') with open(file_path, encoding='utf-8-sig') as k: k_csv = csv.reader(k) for row in k_csv: if row[3]=='1': sld = row[0] if sld in CDN_list1: fqdn = row[1] region = row[7] if fqdn in fqdn_region_list: if region in fqdn_region_list[fqdn]: pass else: fqdn_region_list[fqdn].append(region) else: fqdn_region_list[fqdn] = [region]
for k,v in fqdn_region_list.items(): fqdn_region_count[k]=len(v)fqdn_region_count_sorted = dict(sorted(fqdn_region_count.items(), key=lambda x: x[1], reverse=True))
file1 = open('./mydata/fqdn_region_count_sorted.csv', 'w')writer = csv.writer(file1)for k,v in fqdn_region_count_sorted.items(): writer.writerow([k,v]) print('Success!')
import csvsld_region_list = {}sld_region_count = {}
for k,v in fqdn_region_list.items(): sld = k.split('.')[-1] if sld in sld_region_list: for _ in v: if _ in sld_region_list[sld]: pass else: sld_region_list[sld].append(_) else: sld_region_list[sld] = vfor k,v in sld_region_list.items(): sld_region_count[k]=len(v) sld_region_count_sorted = dict(sorted(sld_region_count.items(), key=lambda x: x[1], reverse=True))
file1 = open('./mydata/sld_region_count_sorted.csv', 'w')writer = csv.writer(file1)for k,v in sld_region_count_sorted.items(): writer.writerow([k,v]) print('Success!')
cdn_name_path = "./mydata_level2/SLD_CNAME_count_sorted.csv"fp = open(cdn_name_path,"r")cdns = fp.readlines()cdns = [ci.split(",")[0] for ci in cdns][:
200]fp.close()
file_names = os.listdir('./cdn_level2/datacon_cdn_ad')
# fo = open("./mydata_level2/level2_sld_geo_data.txt","w")sld_dict = {}
for file_name in tqdm(file_names): file_path = os.path.join('./cdn_level2/datacon_cdn_ad',file_name) with open(file_path,"r") as fp: for line in fp: if line.startswith("sld,md5_fqdn"): continue line = line.strip().split(",") try: if line[3]=="5" and (line[0] in cdns or ".".join(line[4].split(".")[1:]) in cdns): continue 
except Exception as e: print(e) pass
 if line[0] not in sld_dict: sld_dict[line[0]] = [0,0,0,0,set(),set(),set()]# FQDN, A,CNAME, 被 CNAME, geo，IP,ASO if line[3]=="5": sld_dict[line[0]][2] += 1 if ".".join(line[4].split(".")[1:]) not in sld_dict: sld_dict[".".join(line[4].split(".")[1:])] = [0,0,0,0,set(),set(),set()] sld_dict[".".join(line[4].split(".")[1:])][3] += 1
 if line[3]=="1" and line[0] != line[1]: sld_dict[line[0]][0] += 1 sld_dict[line[0]][4].update([line[10]]) sld_dict[line[0]][5].update([line[4]]) sld_dict[line[0]][6].update([line[6]]) if line[3]=="1" and line[0] ==line[1]: sld_dict[line[0]][1] += 1 sld_dict[line[0]][4].update([line[10]]) sld_dict[line[0]][5].update([line[4]]) sld_dict[line[0]][6].update([line[6]])

sld_dict_sorted = dict(sorted(sld_dict.items(), key=lambda x: x[1], reverse=True))
fo = open("./mydata_level2/sld_fqdn_a_canme_r_ip_aso.txt","w")
for key in tqdm(sld_dict_sorted): fo.write(",".join([key]+list(map(str,sld_dict_sorted[key][:4]+[len(sld_dict_sorted[key][4])]+[len(sld_dict_sorted[key][5])]+[len(sld_dict_sorted[key][6])])))+"n")fo.close()
# step 统计每个 IP 的解析域名的数量，并标记已知的类别fp = open("./mydata_level2/level2_sld_geo_data.txt","r")cdn_ips = {}hidden_ips = {}other_ips = {}
for line in tqdm(fp): line = line.split(",") if line[0] in bloom_cdn: if line[1] not in cdn_ips: cdn_ips[line[1]] = 1 else: cdn_ips[line[1]] += 1 elif line[0] in bloom_hidden: if line[1] not in hidden_ips: hidden_ips[line[1]] = 1 else: hidden_ips[line[1]] += 1 else: if line[1] not in other_ips: other_ips[line[1]] = 1 else: other_ips[line[1]] += 1
fo = open("./mydata_level2/all_ip_count.txt","w")
cdn_ips_sorted = dict(sorted(cdn_ips.items(), key=lambda x: x[1], reverse=True)) hidden_ips_sorted = dict(sorted(hidden_ips.items(), key=lambda x: x[1], reverse=True)) other_ips_sorted = dict(sorted(other_ips.items(), key=lambda x: x[1], reverse=True))
for key in cdn_ips_sorted: fo.write(key+","+str(cdn_ips_sorted[key])+","+"1"+"n")for key in hidden_ips_sorted: fo.write(key+","+str(hidden_ips_sorted[key])+","+"2"+"n")for key in other_ips_sorted: fo.write(key+","+str(other_ips_sorted[key])+","+"0"+"n")fo.close()
import os
from tqdm import tqdm
from pybloom_live import ScalableBloomFilter, BloomFilter
# step 0 提取特定 ASO 信息的 IP 地址
# step 1 统计每个 IP 解析的 FQDN 数fp = open("./answer/cdn_level2/result.txt","r")hdomains = fp.readlines()hdomains = [hi.strip().split("t")[1] for hi in hdomains]print(hdomains[9])file_names = os.listdir('./cdn_level2/datacon_cdn_ad')
ip_dict = {}
for file_name in tqdm(file_names): file_path = os.path.join('./cdn_level2/datacon_cdn_ad',file_name) with open(file_path,"r") as fp: for line in tqdm(fp): if line.startswith("sld,md5_fqdn"): continue line = line.strip().split(",") if line[3]=="5": continue if line[3] == "1" and line[0] in hdomains: if line[4] not in ip_dict: ip_dict[line[4]] = 0 ip_dict[line[4]] += 1

ip_dict_sorted = dict(sorted(ip_dict.items(), key=lambda x: x[1], reverse=True))
fo = open("./mydata_level2/hidden_ip_fqdn_count_sorted.txt","w")
for key in ip_dict_sorted: fo.write(key+","+str(ip_dict_sorted[key])+"n")fo.close()

# step 2 取前 591 个 IP，这些 IP 每个平均解析了 14 万的域名，找出其解析过的 SLDfp = open("./mydata_level2/hidden_591.ip","r")hips = fp.readlines()hips = [hi.strip() for hi in hips]
file_names = os.listdir('./cdn_level2/datacon_cdn_ad')
sld_dict = set()
for file_name in tqdm(file_names): file_path = os.path.join('./cdn_level2/datacon_cdn_ad',file_name) with open(file_path,"r") as fp: for line in tqdm(fp): if line.startswith("sld,md5_fqdn"): continue line = line.strip().split(",") if line[3]=="5": continue if line[3] == "1" and line[4] in hips: sld_dict.update([line[0]])
fo = open("./mydata_level2/hidden_ip_591_to_sld.txt","w")for si in list(sld_dict):    fo.write(si+"n")
# webhosting provider["Dreamscape Networks Limited", "BIZLAND-SD", "Cizgi Telekomunikasyon Anonim Sirketi","Marcin Waligorski Greener", "Namesco Limited","Register S.p.A.","Host Europe GmbH", "AUTOMATTIC","InterNetX GmbH", "WEBAIR-INTERNET","Strato AG","FASTLY","LIQUIDWEB","WEEBLY","BIZLAND-SD","Wix.com","SQUARESPACE","Trellian Pty. Limited"]# domain parking["Linode","SEDO GmbH","BODIS-NJ","CONFLUENCE-NETWORK-INC","CENTURYLINK-LEGACY-SAVVIS","IONOS SE","UK-2 Limited"]
v=DMARC1; p=none; fo=1; ruf=mailto:
xxx@xxxxxx.com; rua=mailto:
xxx@xxxxxx.com
;; QUESTION SECTION: ;datacon2022.secrank.cn. IN A
 ;; ANSWER SECTION: datacon2022.secrank.cn. 30  IN  CNAME   admin.datacon.cdn.
;; ANSWER SECTION: datacon2022.secrank.cn. 30 IN CNAME admin.datacon.cdn. ;; ANSWER SECTION: secrank.cn.     60  IN  TXT "5ca162f89d93a4e7e5661a4b290b6d33"
;; ANSWER SECTION: datacon2022.secrank.cn. 30 IN CNAME admin.datacon.cdn. ;; ANSWER SECTION: secrank.cn.     60  IN  TXT "fdf82d037bff4fbb42495e6232c1d7f3"
secrank.cn TXT e1f6c5df7297f459d2eae4783361613a
secrank.cn TXT 982a0de018edf5bf12d042284629106a
secrank.cn TXT fdf82d037bff4fbb42495e6232c1d7f3
secrank.cn TXT fdf82d037bff4fbb42495e6232c1d7f3
secrank.cn TXT fdf82d037bff4fbb42495e6232c1d7f3
datacon2022.secrank.cn. 30 IN CNAME admin.datacon.cdn. admin.datacon.cdn.  3600    IN  A   xxx.xxx.xxx.xxx(IP)
_verify.secrank.cn. 86400 IN TXT "f3c5e853dbd3c50b66d1545aaa074b86" _dmarc.secrank.cn.  86400   IN  TXT "v=DMARC1; p=quarantine; rua=mailto:
da1ef3b3@secrank.cn"
邮箱：da1ef3b3@secrank.c用户名：nda1ef3b3
$TTL 1D @ IN SOA _verify.secrank.cn. rname.invalid. ( 0 ; serial 1D ; refresh 1H ; retry 1W ; expire 3H ) ; minimum NS _verify.secrank.cn. A xxx.xxx.xxx.xxx(攻击者 DNS IP 地址) AAAA ::1     TXT "b6406817af968a444aa934fc2e0c6f3f"
