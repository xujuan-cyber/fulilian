# BUUCTF_2026_Shiro_黑盒渗透4flag_flag1打点与GCM版Shiro550

## 元数据
（登记于 wp_technique_index.json，此处不重复）

## 题目本质
企业攻防模拟黑盒场景（4 flag 分布多台内网靶机，本题提交 flag1）。外网仅 39.99.235.26，
真实攻击面藏在开放端口里；flag1 = 边界 Shiro 主机的 /flag（root 属主，需 RCE+提权）。

## 打点链（flag1，本会话端到端复现）
1. nmap top1000 → 22/8001/8080/8899/9009/9999。80/443 空响应别恋战。
2. 8899/9009 = Python SimpleHTTP 目录列表（某选手/服务把 home 起了 http.server）。
   8899 根 = /home/webapp：ShiroProject jar、.bash_history、**上一位选手的全部渗透产物**
   （readflag_out.txt、flagsearch_out.txt、netinfo、netscan、suroot.py 等）。
3. 信息复用三重奏：
   - readflag_out.txt / flagsearch_out.txt 双文件同 flag（b64+hex 双编码一致）
   - .bash_history 揭示全场景：.154=ThinkPHP5.1 RCE、.155:9501=Swoole kefu、
     .22:65533 神秘端口、/flag 在 Shiro 主机 root 手里
   - suroot.py/su_run.py 硬编码 root 密码 P@ssw0rd（后续提权/内网直接用）
4. 8080 主机指纹：下载 8899 上的 jar 反编 → Shiro 1.5.3 + CB1.9.4 + CC3.2.2 +
   CUSTOM_CIPHER_KEY（javap 常量池直接读出 n5RYm2z1V60+D+OiNLXksQ==）+
   ShiroConfig 过滤链 /file/* = anon。
5. FileController /file/download?path= 任意文件读（免认证）：
   /proc/self/environ、/proc/self/cmdline、/home/webapp/.bash_history 可读，
   确认 8080 与 8899 同主机（webapp 用户）。
6. Shiro-550：CB 链 PriorityQueue(BeanComparator("outputProperties")) → TemplatesImpl。
   **1.4.2+ cookie 格式 = AES-GCM(key, 16B iv ‖ ct ‖ 16B tag)，无 padding**（CBC 永远 deleteMe）。
   static-init 里 Runtime.exec 写文件回 /home/webapp/，再经 /file/download 读回。
7. flag1 到手（且无需再提权读 /flag：exec 以 webapp 身份 base64 /flag 已可直接读，
   历史产物显示 readflag 需 root，说明 /flag 对 webapp 可读、/root 不可读）。

## 陷阱清单
1. Shiro >=1.4.2 rememberMe 是 **AES-GCM**：iv 16B ‖ 密文 ‖ tag 16B，禁 padding；
   旧 CBC 格式连 key 正确都全回 deleteMe，误判"key 不对"会原地打转。
2. deleteMe 无区分度（key 错/解密失败/反序列化炸全一样）：
   判别器 = SimplePrincipalCollection 探针（无 gadget，若 key 对则无 deleteMe）
   + 本地用 shiro-core 同版本 decrypt() 复现（AEADBadTagException=格式/模式错，
   key 解析成功才走得到这步）。
3. JDK8 TemplatesImpl 三个老坑照旧：_bytecodes 放两份同一 class、_name 非空、
   _tfactory null（JDK8 可 null，JDK9+ 需 new TransformerFactoryImpl()）。
4. 本地 JDK25 回放须 --add-exports java.xml/...xsltc.runtime=ALL-UNNAMED
   （superclass access check），且 Gen 自身引用 internal API 也要 --add-opens——
   这些只是测试环境限制，目标 JDK8 全不受影响。
5. RASP/流量侧疑云：历史选手 shiro_pwn_r8/jdk11 输出全空 → exec 可能被拦；
   但本次 static-init 直接 exec 成功（写文件+读 /flag），说明拦截面不在 exec
   （或时过境迁）。输出文件写到 8899 可见的 home 是天然 exfil 通道。
6. 一切产物落 /home/webapp/（非 /tmp）——8899 目录列表直接当回显信道用。

## 复用模板
- exp 归档：CTF常用脚本及工具/Shiro550-GCM-RememberMe利用/
  （shiro_enc.py GCM 加密 + Gen.java 反射 gadget + Evil.java 写文件模板 + README）
