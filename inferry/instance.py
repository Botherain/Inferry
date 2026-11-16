"""单实例与唤起：托盘模式下再次双击快捷方式时，把已有窗口叫出来。

第一个 GUI 进程持有命名互斥量，并创建一个自动复位的命名事件；第二个进程
发现互斥量已存在，就 ``SetEvent`` 后退出。第一个进程的监听线程收到事件后往
Tk 队列里放一条「show」，由主线程恢复窗口。
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from .paths import get_logger

log = get_logger()

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MUTEX_NAME = r"Local\Inferry.Gui"
EVENT_NAME = r"Local\Inferry.Show"
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateEventW.argtypes = [
    wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR
]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

_mutex: int | None = None
_event: int | None = None
_watcher: threading.Thread | None = None
_stop: threading.Event | None = None


def acquire() -> bool:
    """尝试成为唯一 GUI 实例；已有实例时返回 False。"""
    global _mutex
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if not handle:
        # 互斥量都建不出来时宁可放行，也不要让用户完全打不开程序
        log.warning("创建单实例互斥量失败：%s", ctypes.get_last_error())
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex = int(handle)
    return True


def release() -> None:
    global _mutex
    if _mutex:
        kernel32.ReleaseMutex(_mutex)
        kernel32.CloseHandle(_mutex)
        _mutex = None


def signal_show(retries: int = 60, delay: float = 0.1) -> bool:
    """叫已有实例显示窗口；它可能还在启动，短暂重试。"""
    for _ in range(max(1, retries)):
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, EVENT_NAME)
        if handle:
            try:
                return bool(kernel32.SetEvent(handle))
            finally:
                kernel32.CloseHandle(handle)
        time.sleep(delay)
    return False


def watch_show(callback: Callable[[], None]) -> None:
    """启动监听线程；收到第二实例的信号时调用 ``callback``。"""
    global _event, _watcher, _stop
    if _watcher is not None:
        return
    handle = kernel32.CreateEventW(None, False, False, EVENT_NAME)
    if not handle:
        log.warning("创建唤起事件失败：%s", ctypes.get_last_error())
        return
    _event = int(handle)
    _stop = threading.Event()

    def _run() -> None:
        while _stop is not None and not _stop.is_set():
            result = kernel32.WaitForSingleObject(_event, 500)
            if result == WAIT_OBJECT_0:
                try:
                    callback()
                except Exception:
                    log.exception("处理唤起事件失败")

    _watcher = threading.Thread(target=_run, name="inferry-show", daemon=True)
    _watcher.start()


def stop_watch() -> None:
    global _event, _watcher, _stop
    if _stop is not None:
        _stop.set()
    if _event:
        kernel32.SetEvent(_event)
    if _watcher is not None and _watcher.is_alive():
        _watcher.join(2)
    if _event:
        kernel32.CloseHandle(_event)
    _event = None
    _watcher = None
    _stop = None
