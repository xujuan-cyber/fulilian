# EXP 片段库（snippets/）

从 CTF 知识库全量 Markdown 中自动提取的 Python exp/exploit 代码片段，供 agent 检索复用（`fulilian_ctf/` 的 snippets FTS5 表按本目录文件的头注释建索引）。

## 来源

- **知识库根目录**: `/home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/`（只读，扫描其下全部 `.md`，跳过 `.git`）
- **提取脚本**: `~/.fulilian/fulilian-agent/tools/extract_exp_snippets.py`（纯标准库）
- **提取规则**: 抓取 ` ```python / ```py / ```python3 ` 围栏块（另含通过 python 似真度判定的无标注围栏块）；需命中任一 exp 特征（`from pwn import` / `requests.` / `socket.socket` / `subprocess` / `sqlmap` / `system(` / `Crypto` / `gmpy` 等）且 ≥6 行；按代码内容 md5 去重。
- **分类**: 路径关键词 > WP 标题关键词 > 代码特征推断，兜底 `misc`。目录即分类：`web / crypto / reverse / pwn / forensics / misc`。
- **文件命名**: `<安全化的WP标题>__<序号>.py`（中文保留；去除路径分隔符/引号/井号/括号类字符；超 80 字符截断）。

## 元数据格式（下游 FTS5 依赖）

每个片段文件头部固定三行注释，**顺序与格式不可变**：

```python
# SOURCE: <原始 md 的绝对路径>
# TITLE: <WP 标题>
# CATEGORY: web|crypto|reverse|pwn|forensics|misc
```

空一行后为代码正文。检索/回溯原文时解析 `# SOURCE:` 即可定位上游 md。

## 已知局限

- 片段忠实还原上游 md 围栏内容，因此部分文件继承上游质量问题：换行丢失、一个围栏混入多段代码/C 代码/shell 输出、Python2 语法。`py_compile` 通过率约 28%（225 中 64 过），属源数据质量所致；片段主要用于**检索参考**，直接执行前需人工修正。

## 重跑提取

脚本幂等：每次运行先**清空并重建** `snippets/`，再全量重提取。

```bash
~/.fulilian/fulilian-agent/venv/bin/python \
    ~/.fulilian/fulilian-agent/tools/extract_exp_snippets.py
# 可选参数: --kb-root <知识库根目录>  --out-dir <输出目录>
```

运行结束打印统计：扫描 md 数、python 围栏块总数、命中块数、去重剔除数、写入总数、按分类分布。
