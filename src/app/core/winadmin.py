"""权限（UAC）工具：判断是否已提权、以管理员身份重新启动自身。

为什么需要它
------------
Windows 上启动 ETW 会话必须有管理员权限，否则内核会返回 ACCESS_DENIED。
默认要求用户「右键 → 以管理员身份运行」体验很差，所以程序启动时自己检查：
没有权限就通过 ShellExecuteW("runas") 重新拉起一个提权实例，原实例退出。

两种失败都不影响使用：
  · 用户在 UAC 弹窗点「否」→ 返回 ERROR_CANCELLED，原进程继续跑（估算模式）
  · 系统策略禁止提权        → 同样继续跑，界面会给出说明

`--no-elevate` 是内部标记：提权后的新实例会带上它，避免无限互相拉起。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

_SW_SHOWNORMAL = 1
_ERROR_CANCELLED = 1223
_NO_ELEVATE_FLAG = "--no-elevate"


def is_elevated() -> bool:
    """当前进程是否具备管理员权限。非 Windows 平台视为「无需提权」。"""
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def can_elevate() -> bool:
    """是否值得尝试提权（Windows 且当前不是管理员）。"""
    return os.name == "nt" and not is_elevated()


def _build_params(extra_args: list[str] | None) -> list[str]:
    """拼出交给新实例的参数：源码模式要带上脚本路径，冻结模式直接传参数。"""
    args = list(sys.argv[1:] if extra_args is None else extra_args)
    if getattr(sys, "frozen", False):
        params = args
    else:
        script = Path(sys.argv[0])
        try:
            script = script.resolve()
        except OSError:
            pass
        if not script.exists():                        # python - 之类没有脚本路径的场景
            script = Path(__file__).resolve().parents[1] / "main.py"
        params = [str(script)] + args
    if _NO_ELEVATE_FLAG not in params:
        params.append(_NO_ELEVATE_FLAG)
    return params


def _call_shell_execute(exe: str, params: list[str], cwd: str) -> int:
    """实际执行 ShellExecuteW("runas")，返回其数值结果（>32 表示成功）。

    单独抽出来是为了能替换成假实现来测试失败分支（否则一测就弹 UAC）。
    """
    shell32 = ctypes.windll.shell32
    # 返回 HINSTANCE（指针宽度），必须显式声明，
    # 否则默认 c_int 会把成功的句柄截断成负数，误判为失败。
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int,
    ]
    result = shell32.ShellExecuteW(
        None, "runas", exe, subprocess.list2cmdline(params), cwd, _SW_SHOWNORMAL)
    return 0 if result is None else int(result)


def relaunch_elevated(extra_args: list[str] | None = None) -> str:
    """以管理员权限重新启动自己。

    返回空字符串表示已成功拉起提权实例（本进程应当退出）；
    返回非空字符串是失败原因，调用方应继续以当前权限运行。
    """
    if os.name != "nt":
        return "当前平台无需提权"
    if is_elevated():
        return "已经是管理员权限，无需提权"

    exe = sys.executable
    if not exe:
        return "无法确定可执行文件路径"

    params = _build_params(extra_args)
    try:
        code = _call_shell_execute(exe, params, os.getcwd())
    except Exception as exc:                            # pragma: no cover
        return f"调用提权接口失败：{exc}"

    # 注意顺序：ERROR_CANCELLED(1223) 本身就大于 32，
    # 若先判 code > 32 会把「用户点了否」误判成提权成功。
    if code == _ERROR_CANCELLED:
        return "用户在 UAC 弹窗中选择了「否」"
    if code > 32:                                      # 大于 32 才是成功
        return ""
    return f"提权被系统拒绝（ShellExecuteW 返回 {code}）"


def describe() -> str:
    """给界面用的一句话权限描述。"""
    if os.name != "nt":
        return "非 Windows 平台，无需管理员权限"
    return "管理员权限（可逐连接精确统计）" if is_elevated() else "普通用户权限"
