"""LSP 集成 — 编译报错自动反馈（F4-008）。

Pwn/Reverse 题常要编译 exploit 或写解析脚本。此桥接提供两个层级：

1. 轻量编译诊断（本模块自身，零依赖）：gcc -fsyntax-only / cargo check，
   把报错文本喂回 agent 修正——通过 ``compile_check`` CTF 工具
   （tools/ctf_solve.py 注册，ctf_solve 工具集）暴露给 agent。
2. Hermes LSP 基础设施（agent/lsp/，按需）：:func:`lsp_diagnostics`
   在 agent/lsp 服务可用时取 LSP 诊断快照；不可用时安静返回 None，
   不影响轻量路径。

设计为纯函数、无全局状态，方便单测与 hook/工具两侧复用。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

# 语言 → （检查命令构造器，说明）
_SUPPORTED_LANGUAGES = ("c", "cpp", "rust")


def _compile_command(source_file: str, language: str) -> Optional[list]:
    """构造单文件语法检查命令；工具链缺失时返回 None。"""
    if language in ("c", "cpp"):
        compiler = "gcc" if language == "c" else "g++"
        if not shutil.which(compiler):
            return None
        return [compiler, "-fsyntax-only", source_file]
    if language == "rust":
        if not shutil.which("cargo"):
            return None
        return ["cargo", "check"]
    return None


def get_compile_errors(source_file: str, language: str) -> list:
    """获取编译错误，喂回 agent 修正。

    Args:
        source_file: 源码文件
        language: 语言（c/cpp/rust）

    Returns:
        编译错误消息列表（stderr 非空行）；无错误/工具链缺失返回 []。
        rust 的 cargo check 需在 crate 目录内运行（取 source_file 所在目录）。
    """
    language = (language or "").lower().strip()
    source = Path(source_file)
    if language not in _SUPPORTED_LANGUAGES:
        return [f"compile_check: unsupported language {language!r} (c/cpp/rust)"]
    if not source.exists():
        return [f"compile_check: file not found: {source_file}"]

    cmd = _compile_command(str(source), language)
    if cmd is None:
        tool = "cargo" if language == "rust" else ("gcc" if language == "c" else "g++")
        return [f"compile_check: {tool} not found on PATH"]

    kwargs = {"capture_output": True, "text": True, "timeout": 60}
    if language == "rust":
        kwargs["cwd"] = str(source.parent)
    try:
        result = subprocess.run(cmd, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"compile_check: {type(e).__name__}: {e}"]

    stderr = result.stderr or ""
    lines = [ln for ln in stderr.split("\n") if ln.strip()]
    if result.returncode != 0 and not lines:
        return [f"compile_check: exit {result.returncode} (no stderr)"]
    return lines


def diagnostics_summary(source_file: str, language: str, max_lines: int = 40) -> str:
    """编译诊断的人读摘要（供工具返回值 / 喂回 prompt）。"""
    errors = get_compile_errors(source_file, language)
    if not errors:
        return f"compile_check: {source_file} OK (no {language} errors)"
    body = "\n".join(errors[:max_lines])
    if len(errors) > max_lines:
        body += f"\n... ({len(errors) - max_lines} more lines)"
    return f"compile_check: {len(errors)} diagnostic line(s) for {source_file}:\n{body}"


def lsp_diagnostics(file_path: str, timeout: Optional[float] = None) -> Optional[list]:
    """从 Hermes agent/lsp 服务取 LSP 诊断（服务未启用时返回 None）。"""
    try:
        from agent.lsp import get_service

        service = get_service()
        if service is None or not service.is_active():
            return None
        diags = service.get_diagnostics_sync(file_path, timeout=timeout) or []
        return [
            f"{d.get('severity', '?')}: {d.get('message', '')} "
            f"({d.get('range', {}).get('start', {})})"
            if isinstance(d, dict)
            else str(d)
            for d in diags
        ]
    except Exception:  # noqa: BLE001 — LSP 基础设施缺失/异常时不影响轻量路径
        return None


__all__ = [
    "diagnostics_summary",
    "get_compile_errors",
    "lsp_diagnostics",
]
