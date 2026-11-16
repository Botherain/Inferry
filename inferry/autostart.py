"""开机自启动：写入当前用户的 ``Run`` 注册表项，不碰系统级设置。

值名固定为 ``Inferry``，内容是一条带 ``--tray`` 的完整命令行：登录后由
``pythonw.exe`` / ``Inferry.exe`` 直接启动到托盘，不弹出主窗口。卸载器会删除
同一个值，旧的 ``CanvasHelper`` 值也一并清理。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .paths import PROJECT_DIR, get_logger

log = get_logger()

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Inferry"
LEGACY_VALUES = ("CanvasHelper",)


def build_command(exe: Path | None = None, project_dir: Path | None = None,
                  *, frozen: bool | None = None) -> str:
    """返回应写入注册表的命令行（带引号，能处理中文与空格路径）。"""
    packed = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe_path = Path(exe or sys.executable)
    if packed:
        return f'"{exe_path}" --tray'

    root = Path(project_dir or PROJECT_DIR)
    pyw = root / "Inferry.pyw"
    pythonw = exe_path.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.is_file() else exe_path
    if pyw.is_file():
        return f'"{interpreter}" "{pyw}" --tray'
    return f'"{interpreter}" -m inferry gui --tray'


def _read_value(name: str) -> str:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return str(value)
    except (OSError, ImportError):
        return ""


def current() -> str:
    return _read_value(VALUE)


def enabled() -> bool:
    return bool(current())


def ensure(command: str | None = None) -> bool:
    """配置要求自启时调用：命令与当前路径不一致（程序搬过家）就重写。"""
    wanted = command or build_command()
    if current() == wanted:
        return True
    return enable(wanted)


def enable(command: str | None = None) -> bool:
    import winreg

    value = command or build_command()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, value)
        log.info("已设置开机自启动：%s", value)
        return True
    except OSError as exc:
        log.warning("设置开机自启动失败: %s", exc)
        return False


def disable() -> bool:
    import winreg

    ok = True
    for name in (VALUE, *LEGACY_VALUES):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
            log.info("已取消开机自启动：%s", name)
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("取消开机自启动失败 %s: %s", name, exc)
            ok = False
    return ok


def remove_legacy() -> None:
    """改名后清掉旧值，避免 CanvasHelper 与 Inferry 同时随登录启动。"""
    for name in LEGACY_VALUES:
        if _read_value(name):
            disable_name(name)


def disable_name(name: str) -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, name)
        return True
    except OSError:
        return False
