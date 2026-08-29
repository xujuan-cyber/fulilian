# Web 知识卡

## 常用工具
- nmap, curl, ffuf, gobuster, dirsearch, whatweb, hydra, sqlmap, burpsuite, nc

## 常见漏洞
- **SQL 注入**: `' OR 1=1--`, 时间盲注, 报错注入, 堆叠注入, 宽字节, WAF 绕过
- **XSS**: `<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, cookie 窃取
- **SSTI**: `{{7*7}}`, `${7*7}`, `<%=7*7%>`, `#{}` — 模板引擎判别
- **路径穿越**: `../`, `..%2f`, `%2e%2e%2f`, `....//....//`
- **命令注入**: `;id`, `|id`, `$(id)`, `` `id` ``, `||id`（无回显探 DNSlog）
- **文件包含**: `php://filter/convert.base64-encode/resource=`, `data://`, `phar://`
- **文件上传**: 绕过 MIME 检查、扩展名绕过、.htaccess、图片马
- **SSRF**: `gopher://`, `file:///`, `dict://`, 内网探测, 云 metadata
- **反序列化（PHP/Java/Python）**: POP 链、原生类、Shiro/Log4j
- **JWT**: alg=none、弱密钥爆破、kid 注入

## 常见思路
1. 扫端口 → 识别服务 → 查已知 CVE → 抓包分析注入点
2. 检查 robots.txt, sitemap.xml, .git/, .env, 备份文件（.bak/.swp/~）
3. 源码审计（如果可下载）→ 找参数注入点、逻辑漏洞
4. 鉴权绕过：cookie 篡改、JWT 伪造、越权测试
5. 二次漏洞：找到 CMS 版本 → 查公开 exploit

## 常见 Flag 格式
- `flag{...}`, `CTF{...}`, `HTB{...}`, `qwb{...}`, `D0g3{...}`