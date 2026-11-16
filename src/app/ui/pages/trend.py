"""界面模块 —— 趋势分析页。

展示周期内每日流量的变化，并与上一个等长周期对比。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...core.daterange import DateRange, day_str
from ...core.units import format_bytes, format_delta, format_percent
from ..charts import DayChart
from ..context import UiContext
from ..theme import C
from ..widgets import (Card, CardHeader, EmptyState, KpiCard, ScrollHost,
                      ShareBarDelegate, make_table, num_item)


class TrendPage(QWidget):
    def __init__(self, ctx: UiContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = ScrollHost(spacing=14)
        outer.addWidget(scroll)
        root = scroll.content_layout()

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)
        self.kpi_total = KpiCard("本周期总流量", "text")
        self.kpi_prev = KpiCard("上一周期", "text")
        self.kpi_avg = KpiCard("日均流量", "down")
        self.kpi_peak = KpiCard("峰值日期", "up")
        for card in (self.kpi_total, self.kpi_prev, self.kpi_avg, self.kpi_peak):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        chart_card = Card(padding=16, spacing=8)
        chart_card.body().addWidget(
            CardHeader("流量趋势", "上图为每日上传/下载堆叠，下表为逐日明细"))
        self.chart = DayChart(mode="stacked", height=196)
        chart_card.body().addWidget(self.chart)
        self.chart_note = QLabel("")
        self.chart_note.setObjectName("faint")
        chart_card.body().addWidget(self.chart_note)
        root.addWidget(chart_card)

        table_card = Card(padding=16, spacing=10)
        table_card.body().addWidget(CardHeader("每日明细", "按日期从新到旧排列，占比按本周期总流量计算"))
        self.table = make_table(
            ["日期", "下载", "上传", "总流量", "占周期比例", "较前一日"],
            stretch_col=4, align_right=(1, 2, 3, 4, 5),
        )
        for col, width in ((0, 150), (1, 150), (2, 150), (3, 160), (5, 130)):
            self.table.setColumnWidth(col, width)
        self.table.setItemDelegateForColumn(4, ShareBarDelegate("down", self.table))
        self.table.setMinimumHeight(300)
        table_card.body().addWidget(self.table, 1)
        self.empty = EmptyState("所选周期内没有网络活动",
                                "换一个起止日期，或确认采集引擎正在运行")
        table_card.body().addWidget(self.empty)
        root.addWidget(table_card, 1)

    # ------------------------------------------------------------------
    def refresh(self, rng: DateRange):
        res = self.ctx.stats.trend(rng)
        delta_text, direction = format_delta(res.total, res.prev_total)
        delta_color = {"up": C["danger"], "down": C["ok"]}.get(direction, C["muted"])

        self.kpi_total.set(format_bytes(res.total), f"{rng.length} 天合计")
        prev_span = (f"{res.prev[0].day:%m-%d}~{res.prev[-1].day:%m-%d}"
                     if res.prev else "")
        need = max(1, int(rng.length * 0.6))
        if res.prev_days_with_data == 0:
            self.kpi_prev.set(format_bytes(res.prev_total), "上一周期无数据")
            delta_color = C["muted"]
        elif res.prev_days_with_data < need:
            self.kpi_prev.set(format_bytes(res.prev_total),
                              f"上周期仅 {res.prev_days_with_data} 天有数据，环比不可比")
            delta_color = C["muted"]
        else:
            self.kpi_prev.set(format_bytes(res.prev_total), f"环比 {delta_text}　·　{prev_span}")
        self.kpi_prev.sub.setStyleSheet(f"color:{delta_color};")
        active_days = sum(1 for p in res.series if p.total > 0)
        self.kpi_avg.set(format_bytes(res.total / active_days if active_days else 0),
                         f"按 {active_days} 个有数据日计算")
        peak = max(res.series, key=lambda p: p.total, default=None)
        if peak and peak.total > 0:
            self.kpi_peak.set(peak.day.strftime("%m-%d"), f"当日 {format_bytes(peak.total)}")
        else:
            self.kpi_peak.set("—", "无数据")

        self.chart.set_points(res.series)
        self.chart_note.setText(
            f"统计周期 {rng.label()}（{rng.length} 天）　·　"
            f"下载 {format_bytes(res.download)}　·　上传 {format_bytes(res.upload)}　·　"
            f"总流量 {format_bytes(res.total)}（= 下载 + 上传）"
        )

        # 表格：新 → 旧
        ordered = list(reversed(res.series))
        total = res.total
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(ordered))
        for i, point in enumerate(ordered):
            prev_point = ordered[i + 1] if i + 1 < len(ordered) else None
            self.table.setItem(i, 0, num_item(day_str(point.day), align=Qt.AlignLeft | Qt.AlignVCenter))
            self.table.setItem(i, 1, num_item(format_bytes(point.download)))
            self.table.setItem(i, 2, num_item(format_bytes(point.upload)))
            self.table.setItem(i, 3, num_item(format_bytes(point.total), bold=True))
            ratio = (point.total / total) if total else 0.0
            item = num_item(format_percent(ratio), align=Qt.AlignRight | Qt.AlignVCenter)
            item.setData(Qt.UserRole, ratio)
            self.table.setItem(i, 4, item)
            if prev_point is None:
                self.table.setItem(i, 5, num_item("—", align=Qt.AlignRight | Qt.AlignVCenter))
            else:
                text, direction2 = format_delta(point.total, prev_point.total)
                color = {"up": C["danger"], "down": C["ok"]}.get(direction2, C["muted"])
                self.table.setItem(i, 5, num_item(text, color=color))
        self.table.setUpdatesEnabled(True)

        has_data = total > 0
        self.table.setVisible(has_data)
        self.empty.setVisible(not has_data)
