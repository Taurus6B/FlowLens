"""视图数据模型（供统计模块与界面共享）。

所有流量字段单位均为字节；total 恒等于 upload + download，
这是本工具的统计口径，界面与报表中都会显式说明。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class AppAggregate:
    """某应用在一个统计周期内的汇总。"""

    app_id: int
    key: str
    name: str                      # 展示名
    exe_path: str | None = None
    kind: str = "app"              # app | system | unclassified
    upload: int = 0
    download: int = 0
    days_active: int = 0
    share: float = 0.0             # 占总流量比例 0~1
    rank: int = 0

    @property
    def total(self) -> int:
        return self.upload + self.download

    @property
    def upload_share(self) -> float:
        return (self.upload / self.total) if self.total else 0.0


@dataclass
class AppCandidate:
    """「排除应用」选择器里的一行：数据库中记录过的应用。

    key 是进程名（小写），排除列表按它精确匹配，所以同一程序的所有进程实例
    会一起去掉；name 只是给人看的展示名。
    """

    key: str
    name: str
    kind: str = "app"              # app | system
    exe_path: str | None = None
    total: int = 0                 # 历史累计流量（含所有日期）
    last_day: str | None = None    # 最近出现的一天

    @property
    def is_system(self) -> bool:
        return self.kind == "system"


@dataclass
class DayPoint:
    """趋势曲线上的一个点。"""

    day: dt.date
    upload: int = 0
    download: int = 0

    @property
    def total(self) -> int:
        return self.upload + self.download


@dataclass
class DayDetail(DayPoint):
    """单应用详情中的单日数据。"""

    day_total: int = 0            # 当日全应用总流量
    app_share_of_day: float = 0.0  # 该应用当日流量 / 当日总流量
    app_share: float = 0.0        # 该应用当日流量 / 该应用周期总流量


@dataclass
class Overview:
    start: dt.date
    end: dt.date
    upload: int = 0
    download: int = 0
    active_apps: int = 0
    days_with_data: int = 0
    unclassified: int = 0
    series: list[DayPoint] = field(default_factory=list)
    top_apps: list[AppAggregate] = field(default_factory=list)
    prev_total: int = 0
    prev_days_with_data: int = 0

    @property
    def total(self) -> int:
        return self.upload + self.download

    @property
    def avg_per_day(self) -> float:
        active = sum(1 for p in self.series if p.total > 0)
        return self.total / active if active else 0.0

    @property
    def peak(self) -> DayPoint | None:
        return max(self.series, key=lambda p: p.total, default=None)


@dataclass
class AppDetail:
    app: AppAggregate
    start: dt.date
    end: dt.date
    rows: list[DayDetail] = field(default_factory=list)
    range_total: int = 0
    first_day: dt.date | None = None
    last_day: dt.date | None = None

    @property
    def avg_per_active_day(self) -> float:
        active = [r for r in self.rows if r.total > 0]
        return (sum(r.total for r in active) / len(active)) if active else 0.0

    @property
    def peak(self) -> DayDetail | None:
        return max(self.rows, key=lambda r: r.total, default=None)


@dataclass
class TrendResult:
    start: dt.date
    end: dt.date
    series: list[DayPoint] = field(default_factory=list)
    prev: list[DayPoint] = field(default_factory=list)
    granularity: str = "day"
    prev_days_with_data: int = 0

    @property
    def upload(self) -> int:
        return sum(p.upload for p in self.series)

    @property
    def download(self) -> int:
        return sum(p.download for p in self.series)

    @property
    def total(self) -> int:
        return self.upload + self.download

    @property
    def prev_total(self) -> int:
        return sum(p.total for p in self.prev)


@dataclass
class CollectorStatus:
    """采集器运行状态，界面据此展示「数据源 / 权限 / 最近更新」。"""

    mode: str = "init"             # etw | estimate | demo | stopped
    label: str = "初始化中"
    running: bool = False
    ok: bool = True
    message: str = ""
    last_flush: dt.datetime | None = None
    events: int = 0
    bytes_seen: int = 0
    privileged: bool = False
