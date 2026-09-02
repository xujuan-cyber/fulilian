"""PythonShell — 交互式 Python shell 工具。

封装 Python 交互式解释器，用于动态执行代码和评估表达式。
"""

from __future__ import annotations

from typing import Any, Optional

from .base import InteractiveTool


class PythonShell(InteractiveTool):
    """交互式 Python shell 封装。

    Args:
        timeout: 默认超时秒数（默认 30）
    """

    def __init__(self, timeout: float = 30.0) -> None:
        super().__init__(["python3", "-q"], timeout=timeout)

    # ── Python 操作 ─────────────────────────────────────────────────────

    def execute(self, code: str, timeout: Optional[float] = None) -> str:
        """执行 Python 代码。

        Args:
            code: Python 代码字符串
            timeout: 超时秒数

        Returns:
            str: 执行输出
        """
        return self.send(code, timeout=timeout)

    def evaluate(self, expression: str, timeout: Optional[float] = None) -> str:
        """评估 Python 表达式并返回结果。

        通过 ``print(repr(...))`` 包装表达式来获取可读结果。

        Args:
            expression: Python 表达式
            timeout: 超时秒数

        Returns:
            str: 表达式结果
        """
        return self.send(f"print(repr({expression}))", timeout=timeout)

    def run_script(self, script: str, timeout: Optional[float] = None) -> str:
        """运行多行 Python 脚本。

        Args:
            script: 多行 Python 脚本
            timeout: 超时秒数

        Returns:
            str: 脚本输出
        """
        lines = script.strip().split("\n")
        output_parts: list[str] = []
        for line in lines:
            if line.strip():
                result = self.send(line, timeout=timeout)
                if result:
                    output_parts.append(result)
        return "\n".join(output_parts)


__all__ = ["PythonShell"]