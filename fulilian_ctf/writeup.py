"""自动生成 Writeup（F3-010）。

对应实施指南 09-P3-高级功能.md §9.4。从解题轨迹生成 Writeup，
包含：题目描述、解题思路、关键命令、flag、验证结果、耗时。

数据来源（均为已有产物，不侵入原生代码）：
- ``fulilian_ctf.trace`` 的 Trace（solver.log 步骤 + 黑板 facts + flag 校验）
- Project 元信息（title/category/difficulty/description）

生成策略：确定性模板为主（可测、离线可用）；``polish_fn`` 可注入
LLM 润色叙事段落（默认关闭路径，LLM 失败回退模板文本）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from .trace import Trace, get_or_build_trace

# 关键命令提取：只取「命令」类步骤，每步截断，最多 10 条
MAX_KEY_COMMANDS = 10
MAX_CMD_CHARS = 300


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line[:MAX_CMD_CHARS]


def extract_key_commands(trace: Trace) -> list[str]:
    """从轨迹提取关键命令（command 类步骤，去重保序）。"""
    commands: list[str] = []
    seen: set[str] = set()
    for step in trace.steps:
        if step.kind != "command":
            continue
        cmd = _first_line(step.text)
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        commands.append(cmd)
        if len(commands) >= MAX_KEY_COMMANDS:
            break
    return commands


def _narrative_from_facts(trace: Trace) -> str:
    """解题思路段：黑板 Fact 时间线（启发式叙事）。"""
    if not trace.facts:
        return "（黑板无记录的中间发现）"
    return "\n".join(f"{i}. {c}" for i, c in enumerate(trace.facts, 1))


def generate_writeup(
    challenge_id: str,
    work_dir: str | Path,
    project=None,
    trace: Optional[Trace] = None,
    polish_fn: Optional[Callable[[str], str]] = None,
) -> str:
    """从解题轨迹生成 Writeup（F3-010）。

    Args:
        challenge_id: 题目 ID
        work_dir: 挑战工作目录（trace/blackboard/FLAG 所在）
        project: 可选 Project（title/category/difficulty/description）
        trace: 可选已构建 Trace；None 自动 get_or_build_trace
        polish_fn: 可注入 LLM 润色（输入模板全文 → 返回润色文本）；
            失败/为 None 时返回模板原文

    Returns:
        str: Writeup Markdown
    """
    work_dir = Path(work_dir)
    if trace is None:
        trace = get_or_build_trace(work_dir, project)

    title = getattr(project, "title", "") or challenge_id
    category = getattr(project, "category", "") or trace.category or "misc"
    difficulty = getattr(project, "difficulty", "") or trace.difficulty or "unknown"
    description = getattr(project, "description", "") or ""

    duration = int(trace.duration) if trace.duration else 0
    commands = extract_key_commands(trace)

    lines = [
        f"# Writeup: {title}",
        "",
        f"- **Challenge**: `{trace.challenge_id or challenge_id}`",
        f"- **Category**: {category}",
        f"- **Difficulty**: {difficulty}",
        f"- **Model**: `{trace.model or 'n/a'}`",
        f"- **Duration**: {duration}s" if duration else "- **Duration**: n/a",
        "",
        "## 题目描述",
        "",
        description or "（无描述）",
        "",
        "## 解题思路",
        "",
        _narrative_from_facts(trace),
        "",
    ]

    if commands:
        lines += ["## 关键命令", ""]
        lines += [f"```bash\n{c}\n```" for c in commands]
        lines.append("")

    if trace.flag:
        verified = trace.flag_verified or "unverified"
        lines += [
            "## Flag",
            "",
            f"```\n{trace.flag}\n```",
            "",
            f"验证结果：`{verified}`（三重校验门）",
            "",
        ]
    else:
        lines += ["## Flag", "", "（未解出）", ""]

    if trace.dead_ends:
        lines += [
            "## 踩过的坑（死路）",
            "",
        ]
        lines += [f"- {d}" for d in trace.dead_ends[:10]]
        lines.append("")

    writeup = "\n".join(lines)

    if polish_fn is not None:
        try:
            polished = polish_fn(writeup)
            if polished and polished.strip():
                return polished.strip()
        except Exception:  # noqa: BLE001 — 润色失败回退模板
            pass
    return writeup


def writeup_to_format(writeup_md: str, fmt: str, trace: Optional[Trace] = None) -> str:
    """按输出格式转换（markdown 原样 / json 结构化 / html 简单包裹）。"""
    if fmt == "markdown":
        return writeup_md
    if fmt == "json":
        payload = {"format": "markdown", "writeup": writeup_md}
        if trace is not None:
            payload["trace"] = trace.to_dict()
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if fmt == "html":
        body = writeup_md
        # 最小 HTML 包裹：标题/代码块粗转换，避免引入依赖
        body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", body, flags=re.MULTILINE)
        body = re.sub(r"^## (.+)$", r"<h2>\1</h2>", body, flags=re.MULTILINE)
        body = re.sub(r"```(?:bash)?\n(.*?)```", r"<pre><code>\1</code></pre>", body, flags=re.DOTALL)
        body = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", body, flags=re.MULTILINE)
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>CTF Writeup</title></head><body>"
            + body.replace("\n", "\n")
            + "</body></html>"
        )
    raise ValueError(f"unsupported writeup format: {fmt}")


def save_writeup(writeup_md: str, fmt: str, output: str | Path) -> Path:
    """写 Writeup 文件（按格式选扩展名）。"""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ext = {"markdown": "md", "json": "json", "html": "html"}.get(fmt, "txt")
    if output.suffix == "":
        output = output.with_suffix(f".{ext}")
    output.write_text(writeup_md, encoding="utf-8")
    return output


__all__ = [
    "extract_key_commands",
    "generate_writeup",
    "save_writeup",
    "writeup_to_format",
]
