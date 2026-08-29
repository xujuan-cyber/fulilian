"""AGENTS.md 项目级配置（F4-001）。

每个题目工作目录在创建时自动生成 AGENTS.md，solver 进程 chdir 进题目
目录后由 prompt_builder 的 ``_load_agents_md()``（沿 cwd 目录链加载）
自动注入上下文——不需要任何额外接线。

约定：**AGENTS.md 只在不存在时生成**。solver / agent 在解题过程中会
更新「已尝试方向」等小节，覆盖生成内容会丢掉这些进展。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

AGENTS_MD_FILENAME = "AGENTS.md"

# 解题常用工具的默认清单（可用 --tools / challenge.json 覆盖）
DEFAULT_TOOLS = ["nmap", "curl", "ffuf", "python3", "nc"]


def generate_agents_md(
    challenge_id: str,
    description: str = "",
    flag_format: str = "",
    category: str = "",
    target: str = "",
    tools: Optional[list] = None,
) -> str:
    """生成题目目录的 AGENTS.md 内容。"""
    lines = [
        f"# AGENTS.md — 自动生成，题目 {challenge_id}",
        "",
        "## 题目描述",
        description or "（未提供）",
        "",
        "## Flag 格式",
        flag_format or "（未提供，从题目描述/附件推断）",
        "",
        "## 分类",
        category or "（未提供）",
        "",
        "## 目标",
        target or "（未提供）",
        "",
        "## 已尝试方向",
        "（初始为空，solver 更新）",
        "",
        "## 可用工具",
        ", ".join(tools or DEFAULT_TOOLS),
        "",
        "## 提示",
        "（初始为空）",
        "",
    ]
    return "\n".join(lines)


def project_target(project) -> str:
    """从 Project 对象拼 target 描述（host:port）。"""
    if not getattr(project, "target_host", ""):
        return ""
    port = getattr(project, "target_port", 0)
    return f"{project.target_host}:{port}" if port else project.target_host


def ensure_agents_md(work_dir, project) -> Optional[Path]:
    """确保题目工作目录有 AGENTS.md；已存在则不动。

    Returns:
        写入/已存在的 AGENTS.md 路径；work_dir 无法创建时返回 None。
    """
    work_dir = Path(work_dir)
    agents_md = work_dir / AGENTS_MD_FILENAME
    if agents_md.exists():
        return agents_md
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        flag_format = ""
        challenge_json = work_dir / "challenge.json"
        if challenge_json.is_file():
            import json

            try:
                flag_format = str(
                    (json.loads(challenge_json.read_text(encoding="utf-8")) or {}).get(
                        "flag_format", ""
                    )
                    or ""
                )
            except (OSError, ValueError):
                flag_format = ""
        agents_md.write_text(
            generate_agents_md(
                challenge_id=project.challenge_id,
                description=getattr(project, "description", "") or "",
                flag_format=flag_format,
                category=getattr(project, "category", "") or "",
                target=project_target(project),
            ),
            encoding="utf-8",
        )
        return agents_md
    except OSError:
        # 目录只读等场景：不阻断解题，只是没有 AGENTS.md 注入
        return None


__all__ = [
    "AGENTS_MD_FILENAME",
    "DEFAULT_TOOLS",
    "ensure_agents_md",
    "generate_agents_md",
    "project_target",
]
