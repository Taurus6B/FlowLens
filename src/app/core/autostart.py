"""开机自启动：写入当前用户的 Run 注册表项。

写的是 `HKEY_CURRENT_USER\\...\\Run`，属于「当前用户」级启动项：
  * 不需要管理员权限，也不会触发 UAC；
  * 能在「任务管理器 → 启动应用」里看到并被用户随时禁用；
  * 卸载/删掉 exe 后该项成为无效路径，Windows 会直接忽略，不会报错。

自启动的命令固定带 `--tray`：开机时直接驻留托盘后台统计，不弹主窗口。
exe 换位置后旧路径会失效，因此每次启动都会校对一次（`sync()`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FlowLens"
# 更名（NetUsage Monitor → FlowLens）之前写下的启动项，启动时顺手清掉，
# 免得任务管理器里留一条指向已删除 exe 的死链。
LEGACY_VALUES = ("NetUsageMonitor",)
TRAY_FLAG = "--tray"


class AutostartError(RuntimeError):
    """写入/删除启动项失败（权限、组策略、安全软件拦截等）。"""


def _winreg():
    import winreg          # 仅 Windows 有；延迟导入便于非 Windows 下 import 本模块
    return winreg


def supported() -> bool:
    return sys.platform == "win32"


def can_install() -> bool:
    """只有打包成 exe 才有稳定的启动入口（源码运行不注册）。"""
    return supported() and bool(getattr(sys, "frozen", False))


def exe_path() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def build_command(extra_args: list[str] | None = None) -> str | None:
    """生成注册表里的启动命令，例如 `"C:\\...\\FlowLens.exe" --tray`。"""
    exe = exe_path()
    if exe is None:
        return None
    parts = [f'"{exe}"', TRAY_FLAG]
    for arg in extra_args or []:
        parts.append(f'"{arg}"' if " " in arg else arg)
    return " ".join(parts)


def current_command() -> str | None:
    """读取已注册的启动命令；没有则返回 None。"""
    if not supported():
        return None
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            text = str(value).strip()
            return text or None
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_enabled() -> bool:
    return current_command() is not None


def enable(command: str) -> None:
    if not supported():
        raise AutostartError("当前系统不支持开机自启动设置")
    winreg = _winreg()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    except OSError as exc:
        raise AutostartError(_explain(exc)) from exc


def disable() -> None:
    if not supported():
        return
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AutostartError(_explain(exc)) from exc


def sync(extra_args: list[str] | None = None) -> bool:
    """已启用时校正命令（exe 搬家 / 数据目录变更后旧路径会失效）。

    返回是否发生了改写；未启用或无法写入时静默返回 False。
    """
    if not can_install() or not is_enabled():
        return False
    desired = build_command(extra_args)
    if not desired or desired == current_command():
        return False
    try:
        enable(desired)
        return True
    except AutostartError:
        return False


def drop_legacy() -> list[str]:
    """删掉旧名称留下的启动项，返回实际清掉的项名。"""
    if not supported():
        return []
    winreg = _winreg()
    removed = []
    for name in LEGACY_VALUES:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
                removed.append(name)
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed


def _explain(exc: OSError) -> str:
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", 0)
    if code == 5:
        return ("没有权限修改启动项。可能是安全软件拦截，或被组策略"
                "（计算机配置 → 管理模板 → 系统 → 登录）禁止。")
    return f"写入启动项失败：{exc}"
