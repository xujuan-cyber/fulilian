"""``agent.orchestration.reaper`` 的测试（阶段 5 验收 ①–⑤，R1/R2/R3/R5）。

``test_kill_tree_reaps_grandchild`` 是关键用例：它断言**孙进程**也死了。只断言
子进程死了证明不了进程组生效——单杀一个 pid 也能让子进程死。

Windows 分支（Job Object）未经本机验证（R3），三个进程树用例在 win32 上跳过；
``test_isolation_flag_defaults_to_off`` 与平台无关，照跑。
"""

from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import time

import pytest

from agent.orchestration.contracts import TaskCard
from agent.orchestration.launcher import _process_main
from agent.orchestration.reaper import (
    ISOLATION_ENV,
    ProcessReaper,
    isolation_enabled,
)
from agent.orchestration.store import Store
from agent.orchestration.worker import TaskResult, WorkerContext

#: 子进程把孙进程 pid 写进这个环境变量指向的文件（spawn 会继承环境）。
_GRANDCHILD_PIDFILE = "FULILIAN_TEST_REAPER_GRANDCHILD_PIDFILE"

_posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows 走 Job Object 分支，本机（Linux）从未执行过该分支，见 R3",
)


# ------------------------------------------------------------------- helpers


def _card(task_id: str = "t1", *, pool: str = "solve") -> TaskCard:
    return TaskCard(
        task_id=task_id,
        goal=f"goal of {task_id}",
        dod=("done",),
        output_path=f"/tmp/out/{task_id}.md",
        pool=pool,
    )


def _block_with_grandchild(_ctx: WorkerContext) -> TaskResult:
    """模块级：spawn 按限定名 import 它，闭包/lambda 会 pickle 失败。

    起一个 ``sleep 60`` 的孙进程，把它的 pid 写盘，然后永远阻塞——子进程必须活着，
    ``kill_tree`` 才有进程组可查。
    """
    pidfile = os.environ[_GRANDCHILD_PIDFILE]
    child = subprocess.Popen(["sleep", "60"])
    tmp = f"{pidfile}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(str(child.pid))
    os.replace(tmp, pidfile)
    while True:
        time.sleep(0.2)


def _sleep_briefly() -> None:
    time.sleep(0.05)


def _sleep_forever() -> None:
    """和 ``_process_main`` 一样先 setsid：reaper 只处理自成一组的子进程。"""
    os.setsid()
    time.sleep(30.0)


def _ignore_sigterm_then_sleep(ready) -> None:
    """忽略 SIGTERM 后阻塞：逼 ``grace > 0`` 走完宽限期再升级到 SIGKILL。"""
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()  # 处理器装好了才通知，否则父进程的 SIGTERM 会直接杀掉本进程
    time.sleep(30.0)


def _wait_new_group(pid: int, timeout: float = 10.0) -> int:
    """等子进程执行完 ``os.setsid()``（它的进程组变成它自己）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            raise AssertionError("子进程提前退出，测试前提不成立") from None
        if pgid != os.getpgid(0):
            return pgid
        time.sleep(0.02)
    raise AssertionError("子进程没有执行 os.setsid()，测试前提不成立")


def _wait_pid(path: str, timeout: float = 30.0) -> int:
    """等子进程把孙进程 pid 写进文件。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read().strip()
        except FileNotFoundError:
            raw = ""
        if raw:
            return int(raw)
        time.sleep(0.05)
    raise AssertionError(f"{timeout}s 内没等到孙进程 pid 文件：{path}")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_gone(pid: int, timeout: float = 10.0) -> bool:
    """等 pid 消失。

    被 SIGKILL 的孙进程会短暂变成僵尸（父进程已死，等 init 回收），僵尸对
    ``kill(pid, 0)`` 仍然"存在"，所以这里必须轮询而不是查一次。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _make_db(tmp_path) -> str:
    path = str(tmp_path / "orchestration.db")
    Store(path, worker_id="setup").close()
    store = Store(path, worker_id="setup")
    try:
        store.enqueue(_card("t1"))
    finally:
        store.close()
    return path


# ------------------------------------------------- 验收 ① 杀掉进程树无孤儿


@_posix_only
def test_kill_tree_reaps_grandchild(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv(_GRANDCHILD_PIDFILE, str(pidfile))

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_process_main,
        args=(db_path, "solve", _block_with_grandchild, "w-tree", 300, 5.0, None),
        name="worker-w-tree",
        daemon=False,
    )
    reaper = ProcessReaper()
    reaper.attach(process)  # 契约：start() 之前
    process.start()
    try:
        grandchild = _wait_pid(str(pidfile))
        assert _alive(grandchild), "孙进程没起来，测试前提不成立"

        # setsid 生效的前提：子进程自成一个进程组。先断言再杀——否则 setsid 没执行
        # 时下面的 killpg 会打到测试自己的进程组，把 pytest 一起带走。
        assert os.getpgid(process.pid) != os.getpgid(0), (
            "子进程与测试进程同组：_process_main 的 os.setsid() 没执行"
        )

        assert reaper.kill_tree(process) is True

        # 关键断言：孙进程也必须没了。只看子进程死没死证明不了进程组生效。
        assert _wait_gone(grandchild, 10.0), "孙进程仍存活：killpg 没带走整棵进程树"

        process.join(10.0)
        assert process.is_alive() is False
        assert process.exitcode == -signal.SIGKILL
    finally:
        if process.is_alive():
            process.kill()
            process.join(5.0)
        reaper.close()


# -------------------------------------------- 验收 ② 已死进程返回 False


@_posix_only
def test_kill_tree_on_dead_process_returns_false():
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_sleep_briefly)
    reaper = ProcessReaper()
    reaper.attach(process)
    process.start()
    try:
        process.join(30.0)
        assert process.exitcode == 0
        assert reaper.kill_tree(process) is False
    finally:
        reaper.close()


# ------------------------------------- 验收 ③ PermissionError 必须冒泡

@_posix_only
def test_kill_tree_propagates_permission_error(monkeypatch):
    def _deny(_pgid: int, _sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_sleep_forever)
    reaper = ProcessReaper()
    reaper.attach(process)
    process.start()
    try:
        _wait_new_group(process.pid)
        monkeypatch.setattr(os, "killpg", _deny)
        with pytest.raises(PermissionError):
            reaper.kill_tree(process)
    finally:
        monkeypatch.undo()
        if process.is_alive():
            process.kill()
        process.join(10.0)
        reaper.close()


# ---------------------------- grace > 0：SIGTERM 宽限期后升级到 SIGKILL


@_posix_only
def test_kill_tree_grace_escalates_to_sigkill():
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=_ignore_sigterm_then_sleep, args=(ready,))
    reaper = ProcessReaper(grace=0.3)
    reaper.attach(process)
    process.start()
    try:
        assert ready.wait(10.0), "子进程没装好 SIGTERM 处理器，测试前提不成立"
        started = time.monotonic()
        assert reaper.kill_tree(process) is True
        elapsed = time.monotonic() - started
        process.join(10.0)
        assert process.is_alive() is False
        assert process.exitcode == -signal.SIGKILL, "宽限期结束后应升级到 SIGKILL"
        assert elapsed >= 0.2, "没有真的等宽限期（SIGTERM 后直接 SIGKILL）"
    finally:
        if process.is_alive():
            process.kill()
            process.join(5.0)
        reaper.close()


# ---------------------------------------------- 验收 ⑤ 灰度开关默认关

def test_isolation_flag_defaults_to_off(monkeypatch):
    monkeypatch.delenv(ISOLATION_ENV, raising=False)
    assert isolation_enabled() is False, "未设环境变量时必须默认关"

    monkeypatch.setenv(ISOLATION_ENV, "0")
    assert isolation_enabled() is False

    monkeypatch.setenv(ISOLATION_ENV, "1")
    assert isolation_enabled() is True
