"""统计与报表模块 —— 聚合计算。

所有「派生指标」（占比、日均、环比、排名）都在这里统一计算，
保证总览、排行、趋势、详情与导出的数字完全一致。

统一口径：总流量 = 上传流量 + 下载流量（界面与报表均显式标注）。
"""
from __future__ import annotations

import datetime as dt

from ..core.daterange import DateRange, day_str
from ..core.models import (AppAggregate, AppDetail, DayDetail, DayPoint, Overview,
                           TrendResult)
from ..storage.repository import Row, TrafficRepository


def _to_agg(row: Row, total_all: int, rank: int = 0) -> AppAggregate:
    agg = AppAggregate(
        app_id=row.app_id, key=row.key, name=row.name, exe_path=row.exe_path,
        kind=row.kind or "app", upload=row.upload, download=row.download,
        days_active=row.days_active, rank=rank,
    )
    agg.share = (agg.total / total_all) if total_all else 0.0
    return agg


class StatsService:
    def __init__(self, repo: TrafficRepository):
        self.repo = repo

    # ------------------------------------------------------------------ 总览
    def overview(self, rng: DateRange) -> Overview:
        up, down = self.repo.range_totals(rng.start, rng.end)
        rows = self.repo.app_rows(rng.start, rng.end, sort_by="total", descending=True)
        total = up + down
        top = [_to_agg(r, total, i + 1) for i, r in enumerate(rows[:5])]
        series = self._series(rng)
        prev = rng.previous()
        prev_series = self._series(prev)
        p_up, p_down = self.repo.range_totals(prev.start, prev.end)
        return Overview(
            start=rng.start, end=rng.end, upload=up, download=down,
            active_apps=self.repo.active_app_count(rng.start, rng.end),
            days_with_data=sum(1 for p in series if p.total > 0),
            unclassified=self.repo.unclassified_total(rng.start, rng.end),
            series=series, top_apps=top, prev_total=p_up + p_down,
            prev_days_with_data=sum(1 for p in prev_series if p.total > 0),
        )

    # ------------------------------------------------------------------ 排行
    def ranking(self, rng: DateRange, *, search: str = "", sort_by: str = "total",
                descending: bool = True) -> list[AppAggregate]:
        rows = self.repo.app_rows(rng.start, rng.end, search=search,
                                  sort_by=sort_by, descending=descending)
        up, down = self.repo.range_totals(rng.start, rng.end)
        total = up + down
        # 名次始终按总流量排名，与当前排序方式无关，避免误导
        by_total = sorted(rows, key=lambda r: r.total, reverse=True)
        rank_map = {r.app_id: i + 1 for i, r in enumerate(by_total)}
        return [_to_agg(r, total, rank_map.get(r.app_id, 0)) for r in rows]

    def all_apps(self, rng: DateRange) -> list[AppAggregate]:
        return self.ranking(rng, sort_by="total", descending=True)

    # ------------------------------------------------------------------ 趋势
    def trend(self, rng: DateRange) -> TrendResult:
        prev = rng.previous()
        prev_series = self._series(prev)
        return TrendResult(start=rng.start, end=rng.end,
                           series=self._series(rng), prev=prev_series,
                           prev_days_with_data=sum(1 for p in prev_series if p.total > 0))

    def _series(self, rng: DateRange) -> list[DayPoint]:
        """按日序列，缺失日期补 0（保证趋势曲线连续、可比较）。"""
        raw = self.repo.daily_totals(rng.start, rng.end)
        out: list[DayPoint] = []
        for day in rng.days():
            u, d = raw.get(day_str(day), (0, 0))
            out.append(DayPoint(day=day, upload=u, download=d))
        return out

    # ------------------------------------------------------------------ 单应用详情
    def app_detail(self, app_id: int, rng: DateRange) -> AppDetail | None:
        row = self.repo.app_row(app_id, rng.start, rng.end)
        if row is None:
            return None
        up, down = self.repo.range_totals(rng.start, rng.end)
        total_all = up + down
        # 与「应用排行」同一口径的全局名次（含未分类），详情页 KPI 据此显示「排名第 N」
        by_total = self.repo.app_rows(rng.start, rng.end)
        rank_map = {r.app_id: i + 1 for i, r in enumerate(by_total)}
        agg = _to_agg(row, total_all, rank=rank_map.get(app_id, 0))
        daily = self.repo.app_daily(app_id, rng.start, rng.end)
        day_totals = self.repo.daily_totals(rng.start, rng.end)
        rows: list[DayDetail] = []
        for day in rng.days():
            key = day_str(day)
            u, d = daily.get(key, (0, 0))
            du, dd = day_totals.get(key, (0, 0))
            point = DayDetail(day=day, upload=u, download=d, day_total=du + dd)
            point.app_share_of_day = (point.total / point.day_total) if point.day_total else 0.0
            point.app_share = (point.total / agg.total) if agg.total else 0.0
            rows.append(point)
        active = [r for r in rows if r.total > 0]
        return AppDetail(
            app=agg, start=rng.start, end=rng.end, rows=rows, range_total=total_all,
            first_day=active[0].day if active else None,
            last_day=active[-1].day if active else None,
        )

    # ------------------------------------------------------------------ 概览辅助
    def data_bounds(self) -> tuple[dt.date | None, dt.date | None]:
        a, b = self.repo._db.day_bounds()   # noqa: SLF001 - 同模块内受控访问
        def parse(x):
            try:
                return dt.datetime.strptime(x, "%Y-%m-%d").date() if x else None
            except ValueError:
                return None
        return parse(a), parse(b)

    def has_data(self, rng: DateRange) -> bool:
        up, down = self.repo.range_totals(rng.start, rng.end)
        return (up + down) > 0
