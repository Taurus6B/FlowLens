"""界面模块 —— 总览页。

一屏回答三个问题：这段时间用了多少流量、谁用得最多、什么时候用得最多。
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from ...core.daterange import DateRange
from ...core.models import AppAggregate
from ...core.units import format_bytes, format_delta, format_percent
from ..charts import DayChart
from ..context import UiContext
from ..theme import C
from ..widgets import (Card, CardHeader, EmptyState, KpiCard, ScrollHost,
                       clear_layout)


class TopAppRow(QWidget):
    """TOP 应用行：名称 + 数值 + 占比条。"""

    clicked = Signal(int)

    def __init__(self, agg: AppAggregate, parent=None):
        super().__init__(parent)
        self.agg = agg
        self._hover = False
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{agg.name}：总流量 {format_bytes(agg.total)}，"
                        f"占 {format_percent(agg.share)}，活跃 {agg.days_active} 天")

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.agg.app_id)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F7F9FE"))
            p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QColor(C["faint"]))
        p.drawText(QRectF(4, 4, 20, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   str(self.agg.rank))
        p.setPen(QColor(C["text"]))
        f.setPointSize(10)
        p.setFont(f)
        name = self.agg.name
        p.drawText(QRectF(26, 4, w - 26 - 118, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
        p.setPen(QColor(C["text"]))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(w - 116, 4, 112, 18), Qt.AlignRight | Qt.AlignVCenter,
                   format_bytes(self.agg.total))

        # 占比条
        bar_x, bar_w = 26.0, max(10.0, w - 26 - 118)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#F1F4FB"))
        p.drawRoundedRect(QRectF(bar_x, h - 18, bar_w, 5), 2.5, 2.5)
        if self.agg.share > 0:
            p.setBrush(QColor(C["primary"]) if self.agg.kind == "app" else QColor(C["gray_bar"]))
            ratio = max(0.012, min(1.0, self.agg.share))
            p.drawRoundedRect(QRectF(bar_x, h - 18, bar_w * ratio, 5), 2.5, 2.5)
        p.setPen(QColor(C["faint"]))
        f.setWeight(QFont.Normal)
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(QRectF(w - 116, h - 26, 112, 16), Qt.AlignRight | Qt.AlignVCenter,
                   f"{format_percent(self.agg.share)} · {self.agg.days_active} 天")


class OverviewPage(QWidget):
    appSelected = Signal(int)

    def __init__(self, ctx: UiContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = ScrollHost(spacing=14)
        outer.addWidget(scroll)
        root = scroll.content_layout()

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)
        self.kpi_total = KpiCard("总流量", "text")
        self.kpi_down = KpiCard("下载流量", "down")
        self.kpi_up = KpiCard("上传流量", "up")
        self.kpi_apps = KpiCard("活跃应用", "text")
        for card in (self.kpi_total, self.kpi_down, self.kpi_up, self.kpi_apps):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # 趋势图
        self.chart_card = Card(padding=16, spacing=8)
        head = CardHeader("每日流量趋势", "悬停查看当日明细，点击可跳转到当日占比")
        self.chart_card.body().addWidget(head)
        self.chart = DayChart(mode="stacked", height=176)
        self.chart_card.body().addWidget(self.chart)
        self.chart_note = QLabel("")
        self.chart_note.setObjectName("faint")
        self.chart_card.body().addWidget(self.chart_note)
        root.addWidget(self.chart_card)

        # 底部两栏
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        self.rank_card = Card(padding=16, spacing=6)
        rank_head = CardHeader("应用流量 TOP 5", "按总流量排序，点击查看详情")
        self.rank_card.body().addWidget(rank_head)
        self.rank_box = QWidget()
        self.rank_lay = QVBoxLayout(self.rank_box)
        self.rank_lay.setContentsMargins(0, 2, 0, 0)
        self.rank_lay.setSpacing(0)
        self.rank_card.body().addWidget(self.rank_box)
        self.rank_empty = EmptyState("暂无应用数据", "所选周期内没有采集到任何网络流量")
        self.rank_card.body().addWidget(self.rank_empty)
        bottom.addWidget(self.rank_card, 3)

        self.note_card = Card(padding=16, spacing=9)
        self.note_card.body().addWidget(CardHeader("统计说明", "口径与数据说明"))
        self.note_body = QWidget()
        self.note_lay = QVBoxLayout(self.note_body)
        self.note_lay.setContentsMargins(0, 0, 0, 0)
        self.note_lay.setSpacing(9)
        self.note_card.body().addWidget(self.note_body)
        self.note_card.body().addStretch(1)
        bottom.addWidget(self.note_card, 2)
        root.addLayout(bottom)

    # ------------------------------------------------------------------ 刷新
    def refresh(self, rng: DateRange):
        ov = self.ctx.stats.overview(rng)
        delta_text, direction = format_delta(ov.total, ov.prev_total)

        self.kpi_total.set(
            format_bytes(ov.total),
            f"{rng.length} 天 · 日均 {format_bytes(ov.avg_per_day)}",
        )
        self.kpi_down.set(format_bytes(ov.download),
                          f"占总量 {format_percent(ov.download / ov.total if ov.total else 0)}")
        self.kpi_up.set(format_bytes(ov.upload),
                        f"占总量 {format_percent(ov.upload / ov.total if ov.total else 0)}")
        self.kpi_apps.set(f"{ov.active_apps}",
                          f"有数据 {ov.days_with_data} 天 · 未分类 {format_bytes(ov.unclassified)}")

        self.chart.set_points(ov.series)
        peak = ov.peak
        parts = [
            f"统计口径：总流量 = 上传 + 下载（{format_bytes(ov.upload)} + {format_bytes(ov.download)}）",
        ]
        if peak and peak.total > 0:
            parts.append(f"峰值 {peak.day.strftime('%m-%d')} {format_bytes(peak.total)}")
        if rng.contains(dt.date.today()):
            parts.append("今日数据仍在实时累计")
        self.chart_note.setText("　·　".join(parts))

        # TOP 应用
        clear_layout(self.rank_lay)
        if ov.top_apps:
            self.rank_empty.hide()
            self.rank_box.show()
            for agg in ov.top_apps:
                row = TopAppRow(agg, self.rank_box)
                row.clicked.connect(self.appSelected.emit)
                self.rank_lay.addWidget(row)
            self.rank_lay.addStretch(1)
        else:
            self.rank_box.hide()
            self.rank_empty.show()

        self._rebuild_notes(ov, rng, delta_text, direction)

    def _rebuild_notes(self, ov, rng: DateRange, delta_text: str, direction: str):
        clear_layout(self.note_lay)
        delta_color = {"up": C["danger"], "down": C["ok"]}.get(direction, C["muted"])
        need = max(1, int(rng.length * 0.6))
        if ov.prev_days_with_data == 0:
            cmp_text = "上一周期没有采集到数据，暂不计算环比。"
        elif ov.prev_days_with_data < need:
            cmp_text = (f"上一周期仅 {ov.prev_days_with_data} 天有数据（本期 {rng.length} 天），"
                        f"环比参考意义有限；上一周期总量 {format_bytes(ov.prev_total)}。")
        else:
            cmp_text = (f"上一等长周期总流量 {format_bytes(ov.prev_total)}，本期变化 "
                        f"<span style='color:{delta_color}'>{delta_text}</span>。")
        rows = [
            ("总流量口径", "总流量 = 上传流量 + 下载流量，两者均按 1024 进制换算单位。"),
            ("未分类流量",
             f"{format_bytes(ov.unclassified)}（{format_percent(ov.unclassified / ov.total if ov.total else 0)}）"
             "为无法归属到具体应用的流量，例如采集时进程已退出、系统保留连接等，"
             "单列后可与系统总流量对齐。"),
            ("环比", cmp_text),
            ("数据来源", self.ctx.source_label()),
        ]
        for title, text in rows:
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            t = QLabel(title)
            t.setStyleSheet(f"color:{C['text']}; font-size:12px; font-weight:600;")
            d = QLabel(text)
            d.setWordWrap(True)
            d.setStyleSheet(f"color:{C['muted']}; font-size:12px; line-height:150%;")
            box.addWidget(t)
            box.addWidget(d)
            holder = QWidget()
            holder.setLayout(box)
            self.note_lay.addWidget(holder)
