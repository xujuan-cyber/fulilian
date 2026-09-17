# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write_Up（下）.md
# TITLE: 第八届西湖论剑·中国杭州网络安全技能大赛初赛官方Write Up（下）
# CATEGORY: forensics

lib=CDLL('./dll.so') COM_UnMunge=lib.COM_UnMunge2
 pcaps = rdpcap("secret.pcapng")
 f=open('res','wb')for mpacket in pcaps.filter(lambda x:
UDP in x and x[UDP].sport==27015):# mpacket.show() udp=mpacket[UDP] data=bytes(udp.payload)[8:] seq=bytes(udp.payload)[:4] ack=bytes(udp.payload)[4:8] c=create_string_buffer(data) COM_UnMunge(c,len(data),seq[0]) print(mpacket.time,mpacket[IP].src,'->',mpacket[IP].dst) decode_bytes=bytes(c)if len(decode_bytes)>10:if struct.unpack('<L', seq)[0] & (1<<30):if len(decode_bytes)>10+struct.unpack('<h', decode_bytes[7:9])[0]+1: print('find extra data block:') print(decode_bytes[10+struct.unpack('<h', decode_bytes[7:9])[0]:]) decode_bytes=decode_bytes[10:10+struct.unpack('<h', decode_bytes[7:9])[0]]# f.write(decode_bytes) print(f'finally decode data:{decode_bytes}nlength:{len(decode_bytes)}') f.close    ```

PWN

PWN

babytrace
