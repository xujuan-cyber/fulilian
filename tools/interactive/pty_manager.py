"""PTYManager — PTY 伪终端进程管理器。

封装 ``pty.openpty()`` + ``subprocess``，提供交互式进程的发送/接收/超时控制。
支持 with 上下文管理器。在 Windows 上 PTY 不可用时自动降级为 ``subprocess.PIPE`` 模式。
"""

from __future__ import annotations

import os
import select
import subprocess
import signal
import time
from typing import Optional

_HAVE_PTY = False
try:
    import pty
    import termios
    import fcntl
    import struct

    _HAVE_PTY = True
except ImportError:
    pass


class PTYError(Exception):
    """PTY 操作错误。"""


class PTYManager:
    """PTY 伪终端进程管理器。

    Args:
        command: 启动命令（字符串或列表）
        timeout: 默认超时秒数（默认 30）
        shell: 是否通过 shell 执行（默认 True）
    """

    def __init__(
        self,
        command: str | list[str],
        timeout: float = 30.0,
        shell: bool = True,
    ) -> None:
        self._command = command
        self._timeout = timeout
        self._shell = shell
        self._process: Optional[subprocess.Popen] = None
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._closed = False
        self._buffer = b""

    # ── 生命周期 ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """启动进程并创建 PTY。"""
        if self._process is not None:
            raise PTYError("Process already started")

        if _HAVE_PTY:
            self._master_fd, self._slave_fd = pty.openpty()
            kwargs: dict = {
                "stdin": self._slave_fd,
                "stdout": self._slave_fd,
                "stderr": self._slave_fd,
                "close_fds": True,
                "preexec_fn": os.setsid if hasattr(os, "setsid") else None,
            }
        else:
            # Windows 降级：使用 PIPE 模式（不支持完整交互）
            self._master_fd = None
            self._slave_fd = None
            kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
            }

        try:
            if self._shell and isinstance(self._command, str):
                self._process = subprocess.Popen(
                    self._command,
                    shell=True,
                    **kwargs,
                )
            else:
                cmd = self._command if isinstance(self._command, list) else [self._command]
                self._process = subprocess.Popen(
                    cmd,
                    shell=False,
                    **kwargs,
                )
        except Exception as e:
            self._cleanup_fds()
            raise PTYError(f"Failed to start process: {e}") from e

        # 关闭 slave 端（子进程持有），master 留在父进程用于读写
        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None

        self._closed = False
        self._buffer = b""

    def send(self, data: str, timeout: Optional[float] = None) -> str:
        """发送数据并读取响应。

        Args:
            data: 要发送的字符串
            timeout: 超时秒数（默认使用实例超时）

        Returns:
            str: 读取到的响应文本
        """
        self._check_alive()
        self._write(data.encode("utf-8", errors="replace"))
        return self._read_response(timeout)

    def sendline(self, data: str, timeout: Optional[float] = None) -> str:
        """发送一行数据（自动追加换行）并读取响应。

        Args:
            data: 要发送的字符串
            timeout: 超时秒数（默认使用实例超时）

        Returns:
            str: 读取到的响应文本
        """
        return self.send(data + "\n", timeout)

    def close(self) -> None:
        """关闭进程和 PTY。"""
        self._closed = True
        if self._process is not None:
            try:
                # 先尝试杀死整个进程组
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    try:
                        pgid = os.getpgid(self._process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._process.kill()
                    self._process.wait(timeout=2)
                except Exception:  # noqa: BLE001
                    pass
            self._process = None
        self._cleanup_fds()

    @property
    def is_alive(self) -> bool:
        """进程是否仍在运行。"""
        if self._process is None:
            return False
        return self._process.poll() is None

    # ── 上下文管理器 ─────────────────────────────────────────────────────

    def __enter__(self) -> "PTYManager":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _write(self, data: bytes) -> None:
        """写入数据到 master fd。"""
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError as e:
                raise PTYError(f"PTY write error: {e}") from e
        elif self._process and self._process.stdin:
            try:
                self._process.stdin.write(data)
                self._process.stdin.flush()
            except OSError as e:
                raise PTYError(f"PIPE write error: {e}") from e
        else:
            raise PTYError("No writable output available")

    def _read_response(self, timeout: Optional[float] = None) -> str:
        """读取进程响应直到超时或没有更多数据。

        Args:
            timeout: 超时秒数

        Returns:
            str: 累积的响应文本
        """
        deadline = time.time() + (timeout if timeout is not None else self._timeout)
        output = self._buffer
        self._buffer = b""

        while time.time() < deadline:
            if self._master_fd is not None:
                # PTY 模式：select + read
                r, _, _ = select.select([self._master_fd], [], [], max(0.1, deadline - time.time()))
                if not r:
                    break
                try:
                    chunk = os.read(self._master_fd, 4096)
                    if not chunk:
                        break
                    output += chunk
                except OSError:
                    break
            elif self._process and self._process.stdout:
                # PIPE 模式：readline 循环
                r, _, _ = select.select([self._process.stdout], [], [], max(0.1, deadline - time.time()))
                if not r:
                    break
                try:
                    line = self._process.stdout.readline()
                    if not line:
                        break
                    output += line
                except OSError:
                    break
            else:
                break

        # 解码输出，过滤控制字符
        text = output.decode("utf-8", errors="replace")
        return self._clean_output(text)

    def _read_until_prompt(
        self,
        prompts: list[str],
        timeout: Optional[float] = None,
    ) -> tuple[str, Optional[str]]:
        """读取直到看到提示符或超时。

        Args:
            prompts: 提示符列表（如 ``["(gdb) ", ">>> "]``）
            timeout: 超时秒数

        Returns:
            tuple[str, Optional[str]]: (累积输出, 匹配到的提示符或 None)
        """
        deadline = time.time() + (timeout if timeout is not None else self._timeout)
        output = self._buffer
        self._buffer = b""

        while time.time() < deadline:
            # 检查是否匹配提示符
            text = output.decode("utf-8", errors="replace")
            for prompt in prompts:
                if prompt in text:
                    # 保留提示符后的内容到 buffer
                    idx = text.rindex(prompt) + len(prompt)
                    self._buffer = text[idx:].encode("utf-8", errors="replace")
                    return self._clean_output(text[:idx]), prompt

            if self._master_fd is not None:
                r, _, _ = select.select([self._master_fd], [], [], max(0.1, deadline - time.time()))
                if not r:
                    break
                try:
                    chunk = os.read(self._master_fd, 4096)
                    if not chunk:
                        break
                    output += chunk
                except OSError:
                    break
            elif self._process and self._process.stdout:
                r, _, _ = select.select([self._process.stdout], [], [], max(0.1, deadline - time.time()))
                if not r:
                    break
                try:
                    line = self._process.stdout.readline()
                    if not line:
                        break
                    output += line
                except OSError:
                    break
            else:
                break

        text = output.decode("utf-8", errors="replace")
        return self._clean_output(text), None

    def _check_alive(self) -> None:
        """检查进程是否仍在运行。"""
        if self._closed:
            raise PTYError("PTYManager is closed")
        if self._process is None:
            raise PTYError("Process not started. Call start() first")
        if not self.is_alive:
            raise PTYError(f"Process exited with code {self._process.returncode}")

    def _cleanup_fds(self) -> None:
        """清理文件描述符。"""
        for fd in (self._master_fd, self._slave_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._master_fd = None
        self._slave_fd = None

    @staticmethod
    def _clean_output(text: str) -> str:
        """清理输出中的控制字符和 ANSI 转义序列。"""
        import re

        # 移除 ANSI 转义序列
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        # 移除回车（保留换行）
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip()


__all__ = ["PTYManager", "PTYError"]