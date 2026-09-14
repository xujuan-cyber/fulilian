# web-tokenforge-01

一台 token 签名服务的主机被取证：拿到的是部署源码（`app.py`）、
scheme 文档（`policy.md`）和一份正向代理侧的明文抓包（`traffic.log`）。
主机上有三份加密的 vault —— 都用同一条 keystream 公式，但各认不同
时代的会话 sig：admin 层、root 层，以及一份季度切换留下的旧窗口副本。

`SECRET` 只存在于部署环境，不在盘上。

flag 格式：`flag{...}`
