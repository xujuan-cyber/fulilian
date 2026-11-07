"""按进程组回收 worker 进程树（阶段 5；决议 R1–R5）。

**这不是安全沙箱。** 本模块解决的是**故障隔离与资源回收**，不是安全边界：

=======================  ==============================
它解决                    它**不**解决
=======================  ==============================
子进程崩溃不拖垮父进程     恶意代码逃逸
杀掉进程树不留孤儿         文件系统权限隔离
租约被抢时旧 worker 作废    网络访问控制
=======================  ==============================

子进程与父进程**同用户、同文件系统、同网络命名空间**，能读到对方的一切。
任何把它当沙箱用的设计都是错的。（决议 §一）

平台
----
Linux：子进程入口第一句 ``os.setsid()``（见 ``launcher._process_main``）让它自成
会话 + 进程组，回收时 ``os.killpg()`` 一次带走整棵树（含它自己 ``Popen`` 出来的
孙进程）。Windows：Job Object + ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``——没有进程组
概念，Job 是唯一手段。

**但"父进程崩溃也会带走整棵树"这个保证有前提**：job 直到第一次 ``kill_tree`` 才创建
并 assign（见 ``_kill_tree_win32``），只有在那之后 KILL_ON_JOB_CLOSE 才成立；父进程若
在首次 kill 之前崩溃，子进程照样存活。别把它当成"从 spawn 起就有的保险"。

**Windows 分支未经本机测试。** 本机（WSL/kali）所有测试都跑在 Linux 上，
``if sys.platform == "win32"`` 里的代码一次都没被执行过。首次在 Windows 上使用前
**必须手工验证**，未验证的具体点见 ``notes/phase5-reaper-core.md``。
把未测试写成已测试，比不写更危险（决议 R3）。

已知窗口
--------
``Process.start()`` 返回到子进程执行 ``os.setsid()`` 之间有一个极短窗口，此间父进程
若崩溃，子进程会留在父进程的进程组里，``killpg`` 追不到它。这个窗口无法消除（除非
改用 ``subprocess.Popen(start_new_session=True)`` 并以模块方式启动），本阶段**接受
并记录**（决议 R1）。
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import multiprocessing.process

__all__ = ["ISOLATION_ENV", "ProcessReaper", "ReaperError", "isolation_enabled"]

logger = logging.getLogger(__name__)

#: R5 灰度开关。默认关。**不进 ``config.yaml``**（那份配置有 ``_config_version``
#: 和配套 schema，加段属于另一个变更集）。
ISOLATION_ENV = "FULILIAN_ORCH_PROCESS_ISOLATION"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_WINDOWS = sys.platform == "win32"

#: Windows 分支的默认等待轮询间隔（``grace`` 内反复检查进程组是否已消失）。
_POLL_INTERVAL = 0.05


class ReaperError(Exception):
    """回收失败。**杀不动**必须抛，不能静默返回——否则孤儿无人回收（R2）。"""


def isolation_enabled() -> bool:
    """R5：``FULILIAN_ORCH_PROCESS_ISOLATION`` 是否为开。

    默认 ``False``。开关**不控制** ``setsid``：那一步不受本开关影响（R1/R5），因为它
    无副作用且是"杀整组"的前提；关掉它不会更安全，只会让能力彻底不存在。``setsid``
    也只在 POSIX 上调用——win32 没有进程组概念，那里靠 Job Object。
    """
    return os.environ.get(ISOLATION_ENV, "").strip().lower() in _TRUTHY


@dataclass
class _Entry:
    """attach 时登记的进程。"""

    #: 强引用。用 ``id()`` 做键时若不留引用，对象被回收后 ``id`` 会被复用，
    #: 后来的进程可能命中上一条记录（Windows 上等于拿错 Job 句柄）。
    process: multiprocessing.process.BaseProcess
    #: Win32 Job Object 句柄，仅 Windows 用。
    job: object | None = None
    assigned: bool = False


class ProcessReaper:
    """按进程组回收子进程树。Linux 用 ``killpg``，Windows 用 Job Object。

    Args:
        grace: 先 ``SIGTERM`` 再等的宽限秒数。``0.0``（默认）直接 ``SIGKILL``。
            Windows 上被忽略——``TerminateJobObject`` 是即时的，没有可用的
            "先礼后兵"中间态。
    """

    def __init__(self, *, grace: float = 0.0) -> None:
        if grace < 0:
            raise ValueError(f"grace 不能为负：{grace}")
        self.grace = float(grace)
        self._entries: dict[int, _Entry] = {}

    # ------------------------------------------------------------- 登记

    def attach(self, process: multiprocessing.process.BaseProcess) -> None:
        """把进程登记进来。必须在 ``start()`` **之前**调用（要拿到 pid 前的句柄）。

        Windows 的 Job Object 要在子进程存在之前建好，否则子进程先跑起来的孙进程
        就漏在 job 外面。所以这里拒绝已启动的进程，而不是默默接受。
        """
        if process.pid is not None:
            raise ReaperError(
                "attach 必须在 start() 之前调用：Windows 要在拿到 pid 前建好 Job Object"
            )
        self._entries[id(process)] = _Entry(process=process)

    # ------------------------------------------------------------- 回收

    def kill_tree(self, process: multiprocessing.process.BaseProcess) -> bool:
        """杀掉该进程及其所有后代。返回是否确实发出过信号。

        Raises:
            ReaperError: 进程未登记、或 ``killpg`` 失败（``PermissionError`` 会
                原样冒泡，见 R2）。
        """
        entry = self._entry_for(process)
        if _WINDOWS:  # pragma: no cover - 本机不执行
            return self._kill_tree_win32(entry)
        return self._kill_tree_posix(entry)

    def reap(
        self,
        process: multiprocessing.process.BaseProcess,
        *,
        timeout: float = 5.0,
    ) -> bool:
        """``kill_tree`` + ``join(timeout)``。返回进程是否已死。"""
        self.kill_tree(process)
        process.join(timeout)
        return not process.is_alive()

    def close(self) -> None:
        """释放 Windows Job Object 句柄。Linux 上是 no-op。

        关闭后本实例不可再用（登记表已清空，``kill_tree`` 会抛 ``ReaperError``）。
        """
        if _WINDOWS:  # pragma: no cover - 本机不执行
            for entry in self._entries.values():
                _win32_close_job(entry.job)
                entry.job = None
                entry.assigned = False
        self._entries.clear()

    # ------------------------------------------------------------- 内部

    def _entry_for(
        self, process: multiprocessing.process.BaseProcess
    ) -> _Entry:
        entry = self._entries.get(id(process))
        # ``is`` 比较防 id 复用：登记表里那条记录的进程已经不是手上这个了。
        if entry is None or entry.process is not process:
            raise ReaperError("进程未登记：先调用 attach()（必须在 start() 之前）")
        return entry

    def _kill_tree_posix(self, entry: _Entry) -> bool:
        process = entry.process
        pid = process.pid
        if pid is None:
            return False
        if process.exitcode is not None:
            # 已被回收：pid 可能已被内核复用，按 pid 反查进程组会打到无关进程组。
            # 这是"返回 False"而不是"抛错"——进程确实已经死了（验收 ②）。
            return False
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return False
        except PermissionError:
            raise
        except OSError as exc:
            raise ReaperError(f"取进程组失败：pid={pid}: {exc}") from exc

        if pgid == os.getpgid(0):
            # 子进程没 setsid，和本进程同组：killpg 会先杀掉自己。
            raise ReaperError(
                f"拒绝杀掉自身进程组（pgid={pgid}）：子进程没有执行 os.setsid()"
            )

        if self.grace > 0 and self._signal_group(pgid, signal.SIGTERM):
            deadline = time.monotonic() + self.grace
            while time.monotonic() < deadline:
                if not self._group_exists(pgid):
                    return True
                time.sleep(_POLL_INTERVAL)

        return self._signal_group(pgid, signal.SIGKILL)

    def _signal_group(self, pgid: int, sig: int) -> bool:
        """向进程组发信号。R2：错误必须分类，不能一律吞。"""
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            # 组已经空了：不是错误，返回 False 让调用方知道"没发出信号"。
            return False
        except PermissionError:
            # 杀不动 = 真实故障。吞掉它会让孤儿进程从此无人回收。
            raise
        except OSError as exc:
            raise ReaperError(f"killpg 失败：pgid={pgid} sig={sig}: {exc}") from exc
        return True

    def _group_exists(self, pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            raise
        except OSError as exc:
            raise ReaperError(f"探测进程组失败：pgid={pgid}: {exc}") from exc
        return True

    def _kill_tree_win32(self, entry: _Entry) -> bool:  # pragma: no cover
        """**未在本机验证**（R3）。见 ``notes/phase5-reaper-core.md``。"""
        process = entry.process
        pid = process.pid
        if pid is None:
            return False
        if process.exitcode is not None:
            return False
        if entry.job is None:
            entry.job = _win32_create_job()
        if not entry.assigned:
            # attach 发生在 start() 之前，那时还没有 pid 可以 assign，所以第一次
            # 回收时才真正把子进程放进 job。此前它自己 spawn 出来的孙进程漏在
            # job 外面——这是本实现已知的缺口，不是"已验证可用"。
            _win32_assign(entry.job, pid)
            entry.assigned = True
        _win32_terminate(entry.job)
        return True


# ------------------------------------------------------------------ Windows
# 只有 win32 才 import ctypes.wintypes（R3 第 1 条）。整个块在本机从未执行过。


if _WINDOWS:  # pragma: no cover
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),  # ULONG_PTR
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _K32 = None

    def _k32():
        """kernel32 句柄 + 参数签名。不声明 argtypes 的话 HANDLE 会被截成 int。"""
        global _K32
        if _K32 is not None:
            return _K32
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        _K32 = k32
        return k32

    def _win32_error(what: str, *, pid: int | None = None) -> ReaperError:
        detail = ctypes.WinError(ctypes.get_last_error())
        where = f"pid={pid} " if pid is not None else ""
        return ReaperError(f"{what} 失败：{where}{detail}")

    def _win32_create_job():
        k32 = _k32()
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise _win32_error("CreateJobObject")
        info = _EXTENDED_LIMIT()
        # KILL_ON_JOB_CLOSE：父进程即使崩溃，句柄被内核关闭时整棵树一起走。
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = _win32_error("SetInformationJobObject")
            k32.CloseHandle(job)
            raise err
        return job

    def _win32_assign(job, pid: int) -> None:
        k32 = _k32()
        handle = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not handle:
            raise _win32_error("OpenProcess", pid=pid)
        try:
            if not k32.AssignProcessToJobObject(job, handle):
                raise _win32_error("AssignProcessToJobObject", pid=pid)
        finally:
            k32.CloseHandle(handle)

    def _win32_terminate(job) -> None:
        if not _k32().TerminateJobObject(job, 1):
            raise _win32_error("TerminateJobObject")

    def _win32_close_job(job) -> None:
        if job:
            _k32().CloseHandle(job)
