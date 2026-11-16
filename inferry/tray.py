"""Windows 系统托盘图标：用 ctypes 调 shell32，不引入第三方 GUI 依赖。

托盘图标跑在独立线程的消息循环里；窗口相关操作通过回调抛回 Tk 主线程
（GUI 侧只往队列里放一条消息，不直接碰控件）。关闭窗口时程序可以只
``withdraw()`` 主窗口，进程留在托盘里继续执行自动同步与计划任务。
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from .paths import PROJECT_DIR, get_logger

log = get_logger()

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1

NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
SM_CXSMICON = 49
SM_CYSMICON = 50
ID_SHOW = 1001
ID_QUIT = 1002

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = ctypes.c_ushort
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR
]
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, wintypes.HWND, wintypes.LPVOID,
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.ExtractIconExW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.HICON),
    ctypes.POINTER(wintypes.HICON), wintypes.UINT,
]
shell32.ExtractIconExW.restype = wintypes.UINT
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def _load_icon() -> int:
    """优先从 exe 资源取图标，源码运行时用仓库里的 .ico。"""
    cx = user32.GetSystemMetrics(SM_CXSMICON) or 16
    cy = user32.GetSystemMetrics(SM_CYSMICON) or 16
    if getattr(sys, "frozen", False):
        large = wintypes.HICON()
        small = wintypes.HICON()
        count = shell32.ExtractIconExW(
            str(sys.executable), 0, ctypes.byref(large), ctypes.byref(small), 1
        )
        if count:
            handle = small.value or large.value
            if handle:
                return int(handle)
    ico = Path(PROJECT_DIR) / "docs" / "icons" / "inferry.ico"
    if ico.is_file():
        handle = user32.LoadImageW(
            None, str(ico), IMAGE_ICON, cx, cy, LR_LOADFROMFILE
        )
        if handle:
            return int(handle)
    return 0


class TrayIcon:
    """一个托盘图标与右键菜单；``start`` 在独立线程里建窗口和消息循环。"""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        title: str = "Inferry",
    ) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._title = title
        self._ready = threading.Event()
        self._ok = False
        self._thread: threading.Thread | None = None
        self._hwnd: int | None = None
        self._icon = 0
        self._nid = NOTIFYICONDATAW()
        self._added = False
        self._class_name = "InferryTrayWindow"
        self._wndproc = WNDPROC(self._wnd_proc)

    # ---------- 生命周期 ----------

    def start(self, timeout: float = 5.0) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return self._ok
        self._ready.clear()
        self._ok = False
        self._thread = threading.Thread(target=self._run, name="inferry-tray", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout) or not self._ok:
            self._thread = None
            return False
        return True

    def stop(self, timeout: float = 2.0) -> None:
        hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None
        self._ok = False

    # ---------- 线程内 ----------

    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self._class_name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() != 1410:  # 1410 = class already exists
            log.error("注册托盘窗口类失败：%s", ctypes.get_last_error())
            self._ready.set()
            return

        hwnd = user32.CreateWindowExW(
            0, self._class_name, "InferryTray", 0,
            0, 0, 0, 0, None, None, hinst, None,
        )
        if not hwnd:
            log.error("创建托盘窗口失败：%s", ctypes.get_last_error())
            user32.UnregisterClassW(self._class_name, hinst)
            self._ready.set()
            return
        self._hwnd = int(hwnd)

        self._icon = _load_icon()
        if not self._icon:
            log.error("托盘图标加载失败")
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(self._class_name, hinst)
            self._ready.set()
            return

        self._nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self._nid.hWnd = hwnd
        self._nid.uID = 1
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._nid.uCallbackMessage = WM_TRAY
        self._nid.hIcon = self._icon
        self._nid.szTip = self._title
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)):
            log.error("添加托盘图标失败：%s", ctypes.get_last_error())
            user32.DestroyWindow(hwnd)
            user32.DestroyIcon(self._icon)
            user32.UnregisterClassW(self._class_name, hinst)
            self._ready.set()
            return

        self._added = True
        self._ok = True
        self._ready.set()
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._added:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                self._added = False
            if self._icon:
                user32.DestroyIcon(self._icon)
                self._icon = 0
            self._hwnd = None
            self._ok = False

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = int(lparam) & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._on_show()
            elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu(hwnd)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        user32.AppendMenuW(menu, MF_STRING, ID_SHOW, "打开主界面")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(hwnd)
        command = user32.TrackPopupMenu(
            menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
            point.x, point.y, 0, hwnd, None,
        )
        user32.DestroyMenu(menu)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        if command == ID_SHOW:
            self._on_show()
        elif command == ID_QUIT:
            self._on_quit()
