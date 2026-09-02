"""GDBTool — GDB 交互式调试工具。

封装 GDB 的常用命令：断点、运行、单步、寄存器查看、内存查看、反汇编等。
"""

from __future__ import annotations

from typing import Optional

from .base import InteractiveTool


class GDBTool(InteractiveTool):
    """GDB 调试器封装。

    Args:
        binary: 要调试的二进制文件路径
        timeout: 默认超时秒数（默认 60）
    """

    def __init__(self, binary: str, timeout: float = 60.0) -> None:
        super().__init__(["gdb", "-q", binary], timeout=timeout)

    # ── GDB 命令 ────────────────────────────────────────────────────────

    def set_breakpoint(self, location: str, timeout: Optional[float] = None) -> str:
        """设置断点。

        Args:
            location: 断点位置（函数名、行号、地址）
            timeout: 超时秒数

        Returns:
            str: GDB 响应
        """
        return self.send(f"break {location}", timeout=timeout)

    def run(self, args: str = "", timeout: Optional[float] = None) -> str:
        """运行程序（可带参数）。

        Args:
            args: 命令行参数
            timeout: 超时秒数

        Returns:
            str: GDB 响应
        """
        cmd = f"run {args}".strip()
        return self.send(cmd, timeout=timeout)

    def continue_exec(self, timeout: Optional[float] = None) -> str:
        """继续执行。

        Args:
            timeout: 超时秒数

        Returns:
            str: GDB 响应
        """
        return self.send("continue", timeout=timeout)

    def next_instruction(self, count: int = 1, timeout: Optional[float] = None) -> str:
        """单步执行（nexti）。

        Args:
            count: 步数（默认 1）
            timeout: 超时秒数

        Returns:
            str: GDB 响应
        """
        return self.send(f"nexti {count}", timeout=timeout)

    def step_instruction(self, count: int = 1, timeout: Optional[float] = None) -> str:
        """单步进入（stepi）。

        Args:
            count: 步数（默认 1）
            timeout: 超时秒数

        Returns:
            str: GDB 响应
        """
        return self.send(f"stepi {count}", timeout=timeout)

    def info_registers(self, timeout: Optional[float] = None) -> str:
        """查看寄存器值。

        Args:
            timeout: 超时秒数

        Returns:
            str: 寄存器信息
        """
        return self.send("info registers", timeout=timeout)

    def examine_memory(
        self,
        address: str,
        fmt: str = "xwx",
        count: int = 16,
        timeout: Optional[float] = None,
    ) -> str:
        """查看内存内容。

        Args:
            address: 内存地址（如 ``0x7fffffff``）
            fmt: 显示格式（默认 ``xwx`` = 十六进制字）
            count: 显示单元数（默认 16）
            timeout: 超时秒数

        Returns:
            str: 内存内容
        """
        return self.send(f"x/{count}{fmt} {address}", timeout=timeout)

    def disassemble(
        self,
        location: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """反汇编。

        Args:
            location: 反汇编位置（函数名或地址，默认当前 PC）
            timeout: 超时秒数

        Returns:
            str: 反汇编结果
        """
        if location:
            return self.send(f"disassemble {location}", timeout=timeout)
        return self.send("disassemble", timeout=timeout)

    def backtrace(self, timeout: Optional[float] = None) -> str:
        """查看调用栈。

        Args:
            timeout: 超时秒数

        Returns:
            str: 调用栈信息
        """
        return self.send("backtrace", timeout=timeout)

    def info_functions(self, timeout: Optional[float] = None) -> str:
        """查看函数信息。

        Args:
            timeout: 超时秒数

        Returns:
            str: 函数信息
        """
        return self.send("info functions", timeout=timeout)

    def print_variable(self, name: str, timeout: Optional[float] = None) -> str:
        """打印变量值。

        Args:
            name: 变量名
            timeout: 超时秒数

        Returns:
            str: 变量值
        """
        return self.send(f"print {name}", timeout=timeout)

    def set_variable(self, name: str, value: str, timeout: Optional[float] = None) -> str:
        """设置变量值。

        Args:
            name: 变量名
            value: 要设置的值
            timeout: 超时秒数

        Returns:
            str: GDB 响应
        """
        return self.send(f"set {name} = {value}", timeout=timeout)

    def continue_execution(self, timeout: Optional[float] = None) -> str:
        """继续执行（continue_exec 的别名）。"""
        return self.continue_exec(timeout=timeout)

    def info_frame(self, timeout: Optional[float] = None) -> str:
        """查看当前栈帧信息。

        Args:
            timeout: 超时秒数

        Returns:
            str: 栈帧信息
        """
        return self.send("info frame", timeout=timeout)

    def quit(self, timeout: Optional[float] = None) -> None:
        """退出 GDB。"""
        try:
            self.send("quit", timeout=timeout or 5)
        except Exception:  # noqa: BLE001
            pass
        self.close()


__all__ = ["GDBTool"]