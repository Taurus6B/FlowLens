"""采集器 —— 演示模式（合成数据）。

用途：
  * 在无法获取真实流量（无权限 / 无网络 / 评审演示）时，让全部界面、
    报表与持久化链路可以完整走通；
  * 数据带有真实的「日间波动 + 周末回落 + 个别应用整日无活动」特征，
    便于验证空数据、缺失日期、占比等边界逻辑。

演示模式写入的是同一个数据库，界面会常驻「演示数据」标识；
在设置中可一键回到真实采集或清空数据。
"""
from __future__ import annotations

import datetime as dt
import random
import threading
import time

from .base import BaseCollector, EmitFn, TrafficEvent

# (key, 展示名, 类型, 权重, 上传占比, 工作日系数)
PROFILES: list[tuple[str, str, str, float, float, float]] = [
    ("chrome.exe", "Google Chrome", "app", 1.00, 0.09, 1.00),
    ("msedge.exe", "Microsoft Edge", "app", 0.62, 0.07, 1.00),
    ("wechat.exe", "微信", "app", 0.34, 0.22, 1.00),
    ("code.exe", "Visual Studio Code", "app", 0.30, 0.18, 1.15),
    ("steam.exe", "Steam", "app", 0.48, 0.04, 0.55),
    ("onedrive.exe", "OneDrive", "app", 0.26, 0.35, 1.00),
    ("thunder.exe", "迅雷", "app", 0.22, 0.05, 0.90),
    ("cloudmusic.exe", "网易云音乐", "app", 0.12, 0.06, 1.00),
    ("wemeetapp.exe", "腾讯会议", "app", 0.16, 0.42, 1.30),
    ("python.exe", "Python", "app", 0.10, 0.30, 1.10),
    ("__system__", "系统进程", "system", 0.18, 0.45, 1.00),
    ("__unclassified__", "未分类", "unclassified", 0.07, 0.40, 1.00),
]

BASE_DAY_BYTES = 2_400 * 1024 * 1024      # 全网单日基准流量（约 2.4 GB）


def _hour_factor(hour: int) -> float:
    """日间活跃度曲线（0~1），用于让「今天」的数据随时间增长。"""
    curve = [0.10, 0.05, 0.03, 0.02, 0.03, 0.05, 0.10, 0.22,
             0.45, 0.70, 0.85, 0.92, 0.88, 0.80, 0.86, 0.90,
             0.82, 0.74, 0.80, 0.88, 0.78, 0.55, 0.35, 0.20]
    return curve[max(0, min(23, hour))]


class SimulatorCollector(BaseCollector):
    mode = "demo"
    label = "演示模式"
    precise = False
    needs_admin = False

    def __init__(self, config, seed: int | None = 20261113):
        super().__init__(config)
        self._rng = random.Random(seed)

    def start(self) -> None:
        self._rng = random.Random(20261113)

    def run(self, emit: EmitFn, stop: threading.Event) -> None:
        interval = max(3, min(30, int(self.config.flush_interval) * 2))
        while not stop.wait(interval):
            now = dt.datetime.now()
            # 每 tick 视为 interval 秒内的流量，按小时曲线缩放
            share = _hour_factor(now.hour) * (interval / 3600.0)
            events: list[TrafficEvent] = []
            for key, name, kind, weight, up_ratio, _ in PROFILES:
                if kind != "app" and self._rng.random() < 0.35:
                    continue
                total = BASE_DAY_BYTES * weight * share * self._rng.uniform(0.55, 1.45)
                if total < 1024:
                    continue
                up = int(total * up_ratio * self._rng.uniform(0.85, 1.15))
                down = max(0, int(total) - up)
                events.append(TrafficEvent(key, name, kind, None, up, down, now))
            if events:
                emit(events)

    # ------------------------------------------------------------------ 历史回填
    def seed_history(self, db, days: int = 31) -> int:
        """回填最近 days 天的合成历史（仅演示模式使用），返回写入行数。"""
        from ..core import appnames

        rng = random.Random(20260101)
        end = dt.date.today()
        written = 0
        for offset in range(days):
            day = end - dt.timedelta(days=offset)
            weekend = day.weekday() >= 5
            season = 1.0 + 0.18 * ((offset % 9) - 4) / 4.0     # 周期性起伏
            rows: list[tuple[int, str, int, int]] = []
            for key, name, kind, weight, up_ratio, weekday_factor in PROFILES:
                if key == appnames.UNCLASSIFIED_KEY:
                    ident_kind = "unclassified"
                elif key == appnames.SYSTEM_KEY:
                    ident_kind = "system"
                else:
                    ident_kind = "app"
                factor = weekday_factor
                if weekend:
                    factor *= 0.55 if key in ("code.exe", "wemeetapp.exe") else 1.25
                # 10% 概率整日无活动（模拟未开机/未联网），制造数据空档
                if rng.random() < 0.10:
                    continue
                total = BASE_DAY_BYTES * weight * factor * season * rng.uniform(0.6, 1.5)
                if total <= 0:
                    continue
                up = int(total * up_ratio * rng.uniform(0.85, 1.15))
                down = max(0, int(total) - up)
                app_id = db.app_id(key, name, ident_kind, None)
                rows.append((app_id, day.strftime("%Y-%m-%d"), up, down))
            if rows:
                db.add_traffic_batch(rows)
                written += len(rows)
        return written
