"""进程名规范化与友好名称映射。

采集到的原始标识可能是 EXE 名、完整路径或 PID（可能已退出）。
这里统一转换为「应用键 (key)」，保证同一应用的多个进程实例被归入同一条记录；
无法映射的流量统一进入「未分类」。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

UNCLASSIFIED_KEY = "__unclassified__"
UNCLASSIFIED_NAME = "未分类"
SYSTEM_KEY = "__system__"
SYSTEM_NAME = "系统进程"

# 常见应用友好名（键为小写 exe 名）
_FRIENDLY: dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "iexplore.exe": "Internet Explorer",
    "code.exe": "Visual Studio Code",
    "code - insiders.exe": "VS Code Insiders",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "wechat.exe": "微信",
    "weixin.exe": "微信",
    "qq.exe": "QQ",
    "dingtalk.exe": "钉钉",
    "wxwork.exe": "企业微信",
    "feishu.exe": "飞书",
    "telegram.exe": "Telegram",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "zoom.exe": "Zoom",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "epicgameslauncher.exe": "Epic Games",
    "battle.net.exe": "战网",
    "spotify.exe": "Spotify",
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "potplayermini64.exe": "PotPlayer",
    "vlc.exe": "VLC",
    "thunder.exe": "迅雷",
    "onedrive.exe": "OneDrive",
    "dropbox.exe": "Dropbox",
    "baidunetdisk.exe": "百度网盘",
    "aliyundrive.exe": "阿里云盘",
    "explorer.exe": "Windows 资源管理器",
    "svchost.exe": "Windows 服务宿主",
    "lsass.exe": "本地安全认证",
    "dllhost.exe": "COM 代理",
    "searchapp.exe": "Windows 搜索",
    "shellexperiencehost.exe": "Windows 外壳体验",
    "runtimebroker.exe": "运行时代理",
    "taskmgr.exe": "任务管理器",
    "python.exe": "Python",
    "pythonw.exe": "Python",
    "java.exe": "Java",
    "javaw.exe": "Java",
    "node.exe": "Node.js",
    "git.exe": "Git",
    "wps.exe": "WPS Office",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "msedgewebview2.exe": "Edge WebView2",
    "nvidia web helper.exe": "NVIDIA Web Helper",
    "adb.exe": "ADB",
    "curl.exe": "curl",
    "git-remote-https.exe": "Git",
    "openvpn.exe": "OpenVPN",
    "clash.exe": "Clash",
    "clash-verge.exe": "Clash Verge",
    "v2ray.exe": "V2Ray",
    "wemeetapp.exe": "腾讯会议",
    "txupd.exe": "腾讯更新",
}

# 系统级进程（非用户应用，单列展示）
_SYSTEM_KEYS = {
    "system", "system idle process", "registry", "memory compression",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "audiodg.exe",
}


@dataclass(frozen=True)
class AppIdentity:
    key: str
    name: str
    kind: str = "app"          # app | system | unclassified
    exe_path: str | None = None


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def identify(proc_name: str | None, exe_path: str | None = None) -> AppIdentity:
    """把采集到的进程标识转换为统一的应用身份。"""
    raw = _clean(proc_name or "")
    if not raw and exe_path:
        raw = _clean(os.path.basename(exe_path))
    if not raw:
        return AppIdentity(UNCLASSIFIED_KEY, UNCLASSIFIED_NAME, "unclassified")
    low = raw.lower()
    if low in ("system", "system process"):
        return AppIdentity(SYSTEM_KEY, SYSTEM_NAME, "system", exe_path)
    friendly = _FRIENDLY.get(low)
    if friendly:
        kind = "system" if low in _SYSTEM_KEYS else "app"
        return AppIdentity(low, friendly, kind, exe_path)
    if low in _SYSTEM_KEYS:
        return AppIdentity(low, raw, "system", exe_path)
    # 去掉扩展名作为展示名，保留原始大小写；全小写时首字母大写以更易读
    stem = raw[:-4] if low.endswith(".exe") else raw
    if stem and stem.islower():
        stem = stem[:1].upper() + stem[1:]
    return AppIdentity(low, stem or raw, "app", exe_path)


def unclassified() -> AppIdentity:
    return AppIdentity(UNCLASSIFIED_KEY, UNCLASSIFIED_NAME, "unclassified")
