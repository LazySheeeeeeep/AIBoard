# -*- coding: utf-8 -*-
"""
Windows 开机自动启动管理模块 (兼容 Python 源码运行态与 PyInstaller 独立 .exe 打包态)
使用当前用户级注册表 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run，无需管理员权限。
"""

import os
import sys
from typing import Tuple

try:
    import winreg  # type: ignore
except ImportError:
    winreg = None  # type: ignore


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "AIBoard"


def get_app_root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_autostart_command() -> str:
    """构建静默开机启动命令行（自动识别打包后的 .exe 或本地静默启动器）"""
    if getattr(sys, "frozen", False):
        return '"{}" --autostart'.format(os.path.abspath(sys.executable))

    root_dir = get_app_root_dir()
    # 若项目根目录或 dist 下存在打包好的独立 exe，优先指向 exe
    exe_direct = os.path.join(root_dir, "AIBoard.exe")
    if os.path.isfile(exe_direct):
        return '"{}" --autostart'.format(exe_direct)

    # 优先直接使用当前正在运行的解释器旁的 pythonw.exe（无黑框，且路径 100% 准确）
    app_py = os.path.join(root_dir, "app.py")
    pyw = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pythonw.exe")
    if os.path.isfile(pyw):
        return '"{}" "{}" --autostart'.format(pyw, app_py)

    vbs_launcher = os.path.join(root_dir, "launch_silent.vbs")
    if os.path.isfile(vbs_launcher):
        return 'wscript.exe "{}" --autostart'.format(vbs_launcher)

    return '"{}" "{}" --autostart'.format(sys.executable, app_py)


def is_autostart_enabled() -> bool:
    if winreg is None or os.name != "nt":
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
        val, _regtype = winreg.QueryValueEx(key, APP_REG_NAME)
        winreg.CloseKey(key)
        return bool(val and str(val).strip())
    except OSError:
        return False
    except Exception:
        return False


def set_autostart(enabled: bool) -> Tuple[bool, str]:
    """开启或关闭开机自动启动，返回 (是否成功, 状态消息)"""
    if winreg is None or os.name != "nt":
        return False, "当前系统不支持 Windows 注册表自启配置"

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        if enabled:
            cmd = build_autostart_command()
            winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            return True, "已开启开机自动启动"
        else:
            try:
                winreg.DeleteValue(key, APP_REG_NAME)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            winreg.CloseKey(key)
            return True, "已关闭开机自动启动"
    except Exception as exc:
        return False, "开机启动设置失败: {}".format(exc)
