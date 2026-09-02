"""NetcatTool — Netcat 网络交互工具。

封装 netcat 用于与远程 CTF 服务交互：发送 payload、读取响应等。
"""

from __future__ import annotations

from typing import Optional

from .base import InteractiveTool


class NetcatTool(InteractiveTool):
    """Netcat 连接封装。

    Args:
        host: 目标主机
        port: 目标端口
        timeout: 默认超时秒数（默认 30）
    """

    def __init__(self, host: str, port: int, timeout: float = 30.0) -> None:
        self._host = host
        self._port = port
        super().__init__(["nc", host, str(port)], timeout=timeout)

    # ── 网络操作 ────────────────────────────────────────────────────────

    def send_payload(self, payload: str, timeout: Optional[float] = None) -> str:
        """发送 payload 并读取响应。

        Args:
            payload: 要发送的数据
            timeout: 超时秒数

        Returns:
            str: 服务端响应
        """
        return self.send(payload, timeout=timeout)

    def send_hex(self, hex_data: str, timeout: Optional[float] = None) -> str:
        """发送十六进制编码的数据（自动解码为原始字节）。

        Args:
            hex_data: 十六进制字符串（如 ``"48656c6c6f"``）
            timeout: 超时秒数

        Returns:
            str: 服务端响应
        """
        import binascii

        raw = binascii.unhexlify(hex_data.replace(" ", ""))
        # 通过管道写入原始字节
        self._pty.send(raw.decode("latin-1"), timeout=timeout)
        return self._pty.send("", timeout=timeout)

    def read_until(self, delimiter: str, timeout: Optional[float] = None) -> str:
        """读取直到遇到指定分隔符。

        Args:
            delimiter: 分隔符字符串
            timeout: 超时秒数

        Returns:
            str: 累积读取内容
        """
        output, _ = self._pty._read_until_prompt([delimiter], timeout=timeout)  # noqa: SLF001
        return output

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port


__all__ = ["NetcatTool"]