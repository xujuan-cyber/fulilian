# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/HackPack（LLM挑战）Writeup.md
# TITLE: HackPack（LLM挑战）Writeup
# CATEGORY: web

import requests
import re
import json

s = requests.session()
url = 'http://example.com/api/endpoint'
s.get("https://llpm.cha.hackpack.club/")
for i in range(1,11):
 r = s.get("https://llpm.cha.hackpack.club/level/"+str(i))
 reg = re.findall("code.*?}",r.text)
 if(len(reg[0])<len(reg[1])):
 data = {"answer": 1, "level": i}
 json_data = json.dumps(data)
 r2 = s.post("https://llpm.cha.hackpack.club/validate-point", data=json_data, headers={'Content-Type': 'application/json'})
 else:
 data = {"answer": 2, "level": i}
 json_data = json.dumps(data)
 r2 = s.post("https://llpm.cha.hackpack.club/validate-point", data=json_data, headers={'Content-Type': 'application/json'})

 print(r2.text)
rrr = s.get("https://llpm.cha.hackpack.club/flag")
print(rrr.text)
ARC,Architecture,AvailableHub,Average,entry_id,Flagged,GSM8K,HellaSwag,HubLicense,HubLikes,Merged,MMLU,Model,ModelSHA,MoE,NumberParameters,Precisions,TruthfulQA,Types,WeightType,Winogrande
select from rankings desc arc
