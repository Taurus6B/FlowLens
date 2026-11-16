"""必要的配置内容：程序配置的默认值、读写与校验。

配置文件固定为「数据目录/config.json」，首次运行自动生成；
命令行参数（--data-dir / --demo）优先于配置文件。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_FILENAME = "config.json"
# 仅在「程序目录不可写」时才用到的兜底目录名。产品已更名为 FlowLens，
# 但这个目录名保持旧值不动：改了会让老用户的历史数据看起来凭空消失。
DEFAULT_APP_DIR = "NetUsageMonitor"

COLLECTOR_MODES = ("auto", "etw", "estimate", "demo")
MODE_LABELS = {
    "auto": "自动（优先精确模式）",
    "etw": "精确模式（ETW 逐连接，自动申请管理员）",
    "estimate": "估算模式（按活动连接分摊）",
    "demo": "演示模式（合成数据）",
}

# 点击窗口关闭按钮时的行为
CLOSE_ACTIONS = ("ask", "quit", "tray")
CLOSE_LABELS = {
    "ask": "每次询问",
    "quit": "直接退出程序",
    "tray": "留在后台继续统计",
}


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """程序所在目录：源码运行时是项目根目录，打包后是 exe 所在目录。

    单文件 exe 的 __file__ 在临时解压目录（_MEIPASS）里，用它定位 data/
    会导致每次启动都换一个空数据库，所以这里必须以 sys.executable 为准。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """只读资源（图标等）路径：打包后位于解压目录。"""
    base = Path(getattr(sys, "_MEIPASS", program_dir()))
    return base.joinpath(*parts)


def default_data_dir() -> Path:
    """默认数据目录：优先使用程序目录下的 data（便携），失败则用 LOCALAPPDATA。"""
    override = os.environ.get("NETUSAGE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    candidate = program_dir() / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / DEFAULT_APP_DIR


@dataclass
class AppConfig:
    # —— 采集 ——
    collector_mode: str = "auto"      # auto | etw | estimate | demo
    collect_interval: int = 30        # 采集批次/采样周期（秒）
    flush_interval: int = 5           # 落库周期（秒）
    reconcile_unclassified: bool = True   # 用系统总流量校准未分类流量
    auto_elevate: bool = True         # 启动时自动申请管理员权限（精确模式需要）
    excluded_apps: list[str] = field(default_factory=list)  # 不统计的进程名（小写）

    # —— 统计 ——
    default_range_days: int = 30      # 默认统计范围（最近 30 天）
    max_range_days: int = 31          # 统计周期上限
    retention_days: int = 62          # 历史数据保留天数
    auto_clean_temp: bool = True      # 启动时清理 %TEMP% 下残留的 ETW 采集目录

    # —— 界面 ——
    theme: str = "light"
    window_width: int = 1240
    window_height: int = 820
    restore_last_range: bool = True
    close_action: str = "ask"         # ask=每次询问 | quit=直接退出 | tray=留在后台
    last_start: str = ""
    last_end: str = ""

    # —— 运行时（不写入配置文件）——
    data_dir: str = ""

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, data_dir: Path) -> "AppConfig":
        data_dir = Path(data_dir).expanduser()
        try:
            data_dir = data_dir.resolve()
        except OSError:
            pass
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / CONFIG_FILENAME
        cfg = cls(data_dir=str(data_dir))
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            known = {f.name for f in fields(cls)}
            for key, value in raw.items():
                if key in known and key != "data_dir":
                    setattr(cfg, key, value)
        cfg.normalize()
        return cfg

    def normalize(self) -> None:
        """把配置收敛到合法范围，避免手改配置导致程序崩溃。"""
        if self.collector_mode not in COLLECTOR_MODES:
            self.collector_mode = "auto"
        if self.close_action not in CLOSE_ACTIONS:
            self.close_action = "ask"
        self.collect_interval = max(10, min(600, int(self.collect_interval or 30)))
        self.flush_interval = max(2, min(120, int(self.flush_interval or 5)))
        self.default_range_days = max(1, min(31, int(self.default_range_days or 30)))
        self.max_range_days = max(1, min(31, int(self.max_range_days or 31)))
        self.retention_days = max(31, min(730, int(self.retention_days or 62)))
        self.auto_elevate = bool(self.auto_elevate)
        self.auto_clean_temp = bool(self.auto_clean_temp)
        if self.default_range_days > self.max_range_days:
            self.default_range_days = self.max_range_days
        self.window_width = max(960, int(self.window_width or 1240))
        self.window_height = max(640, int(self.window_height or 820))
        self.excluded_apps = [str(x).lower() for x in (self.excluded_apps or []) if str(x).strip()]

    def save(self) -> None:
        self.normalize()
        payload = asdict(self)
        payload.pop("data_dir", None)
        path = Path(self.data_dir) / CONFIG_FILENAME
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return Path(self.data_dir) / CONFIG_FILENAME

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "traffic.db"

    @property
    def export_dir(self) -> Path:
        return Path(self.data_dir) / "exports"

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.collector_mode, self.collector_mode)
