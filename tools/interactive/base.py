"""InteractiveTool — 交互式工具基类。

封装 PTYManager，提供统一的交互式工具接口。
"""

from __future__ import annotations

from typing import Optional

from .pty_manager import PTYManager


class InteractiveTool:
    """交互式工具基类。

    Args:
        command: 启动命令
        timeout: 默认超时秒数（默认 30）
    """

    def __init__(self, command: str | list[str], timeout: float = 30.0) -> None:
        self._pty = PTYManager(command, timeout=timeout, shell=True)
        self._started = False

    def start(self) -> None:
        """启动交互式进程。"""
        if not self._started:
            self._pty.start()
            self._started = True

    def send(self, cmd: str, timeout: Optional[float] = None) -> str:
        """发送命令并读取响应。

        Args:
            cmd: 命令字符串
            timeout: 超时秒数

        Returns:
            str: 响应文本
        """
        self.start()
        return self._pty.sendline(cmd, timeout=timeout)

    def close(self) -> None:
        """关闭交互式进程。"""
        if self._started:
            self._pty.close()
            self._started = False

    @property
    def is_alive(self) -> bool:
        """进程是否仍在运行。"""
        return self._pty.is_alive

    # ── 上下文管理器 ─────────────────────────────────────────────────────

    def __enter__(self) -> "InteractiveTool":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.close()


__all__ = ["InteractiveTool"]