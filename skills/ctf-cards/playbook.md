# 解题流程 Playbook（常驻卡）

> 此卡每题必注入，与分类无关。先按本卡决策，再叠加对应分类知识卡。
> 原则：在时间盒内拿到 flag；超时果断止损换题，不恋战。

## 时间盒决策表
| 难度 | 首次尝试 | 看 hint 后追加 | 总上限 |
|------|---------|---------------|--------|
| Easy | 3 分钟 | +2 分钟 | 5 分钟 |
| Medium | 5 分钟 | +3 分钟 | 8 分钟 |
| Hard | 8 分钟 | +5 分钟 | 13 分钟 |

- 换题规则：一个时间盒内无任何新信息/新报错 → 直接换题；Hard 最多烧 2 个总上限
- 基础设施：端口不通 → 扫常见端口(80/443/8080/8000/5000/3000/9999/1337) → 仍不通标记 INFRA_BLOCKED 即弃
- 优先级：Easy > Medium > Hard；同难度分值高者先做
- 容器：同时最多 3 个活跃，保留 1 个空槽；5 分钟无进展的容器直接回收换题

## Hint 决策规则
- Easy：裸试满 3 分钟再看；Medium：卡 3 分钟或主路线走完再看；Hard：动手前先看
- hint 只扣少量分，换回的时间通常净赚；目标是 flag 不是满分
- hint 内容本身就是方向：拿到后立即把关键词转成检索词重跑路线

## 信息收集 3 分钟固定动作（每题开场必做）
- 第 1 分钟：`curl -s http://t:p/` 首页 + `curl -sI` 响应头 + robots.txt + sitemap.xml；附件通读一遍
- 首页源码注释常藏路径/密钥：view-source 逐行看一遍再打路径
- 第 2 分钟：常见路径一次打完：/admin /login /flag /api /api/docs /swagger.json /graphql /.env /.git/config /.DS_Store /backup.zip /index.php.bak
- 第 3 分钟：ffuf 目录扫（dirb common.txt）+ 参数 fuzz；怀疑隐藏服务才 nmap
- 每步发现（路径/参数/版本号/报错原文）随手记录，作为后续路线选择依据

## 信息泄露类优先检查项（命中率最高）
- S3/对象存储：页面源码 grep -i bucket → 直接 GET /bucket-name/ 列举对象
- Lambda/云函数管理页：/lambda/ /functions/ /env → 环境变量里翻 FLAG/AK/SK
- SSRF → IMDS：http://169.254.169.254/latest/meta-data/（含 IAM 临时凭据）
- 调试端点：/debug /status /health /actuator /phpinfo.php /console /metrics
- 默认凭证：admin:admin、admin:password、guest:guest；固定 session/JWT 先试伪造
- Git 仓库泄露：/.git/config 确认存在后用 GitHack/dumpall 恢复源码

## 检索纪律（硬性规则）
- 同一题卡 2 轮（约 2 个时间盒）无进展 → 必须调 knowledge_retriever 检索历史 WP，禁止继续盲试
- 检索词 = 分类 + 已确认技术特征（例："tcache 2.34"、"php filter chain"、"Shiro550"）
- 命中相似 WP 只取思路骨架（漏洞类型 → 利用链 → 落点），不复述全文，仍按时间盒执行
- 检索无结果：换关键词抽象层级再试（"堆题"→"tcache"，"登录"→"JWT"，中文↔英文）

## 快速决策
- 有明确报错/报文特征 → 直接按分类知识卡路线打
- 毫无线索 → 先把信息泄露清单全查一遍（约 2 分钟），再回分类卡
- 题目附带源码/附件 → 先读源码再打请求，不要先盲测
- 多题并行：每题独立计时，任何一题超时间盒立即切换
- 同题连续 2 次 INFRA_BLOCKED：等 30 秒重试一次，仍不通才最终放弃
- 连续 3 题失败：停 30 秒重读本卡，检查是否跳过了开场固定动作

## 收尾
- 拿到 flag 立即提交；格式不匹配先规范化（大小写/前后缀）再重试一次
- 无论成败记录：题目类型 / 卡点关键词 / 关键命令，供复盘与知识库沉淀
