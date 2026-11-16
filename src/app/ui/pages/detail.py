"""界面模块 —— 单个应用详情页。

回答：这个应用在某一天用了多少流量、上传下载各占多少、占当天全网的多少。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ...core.daterange import DateRange, day_str
from ...core.models import AppDetail
from ...core.units import format_bytes, format_percent
from ..app_picker import AppPicker
from ..charts import DayChart
from ..context import UiContext
from ..theme import C
from ..widgets import (Card, CardHeader, EmptyState, KpiCard, ScrollHost,
                      ShareBarDelegate, UNCLASSIFIED_META, UNCLASSIFIED_TIP,
                      make_table, num_item)


class DetailPage(QWidget):
    exportRequested = Signal(int)      # 单应用导出

    def __init__(self, ctx: UiContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._range = DateRange.last_days(30)
        self._app_id: int | None = None
        self._known_ids: tuple[int, ...] = ()
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = ScrollHost(spacing=14)
        outer.addWidget(scroll)
        root = scroll.content_layout()

        top = Card(padding=16, spacing=12)
        root.addWidget(top)

        pick = QHBoxLayout()
        pick.setSpacing(8)
        label = QLabel("选择应用")
        label.setObjectName("muted")
        pick.addWidget(label)
        self.picker = AppPicker()
        self.picker.setMinimumWidth(300)
        self.picker.appPicked.connect(self._on_pick)
        pick.addWidget(self.picker)
        pick.addStretch(1)
        self.export_btn = QPushButton("导出该应用报表")
        self.export_btn.setObjectName("primary")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._on_export)
        pick.addWidget(self.export_btn)
        top.body().addLayout(pick)

        # 进程路径单独一行：路径很长，跟选择器挤在一行会把导出按钮顶出去
        self.app_meta = QLabel("")
        self.app_meta.setObjectName("faint")
        top.body().addWidget(self.app_meta)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)
        self.kpi_total = KpiCard("周期总流量", "text")
        self.kpi_down = KpiCard("下载流量", "down")
        self.kpi_up = KpiCard("上传流量", "up")
        self.kpi_share = KpiCard("占全网比例", "primary")
        for card in (self.kpi_total, self.kpi_down, self.kpi_up, self.kpi_share):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            kpi_row.addWidget(card)
        top.body().addLayout(kpi_row)

        chart_card = Card(padding=16, spacing=8)
        chart_card.body().addWidget(CardHeader("该应用每日流量", "蓝色面积＝下载，橙色折线＝上传"))
        self.chart = DayChart(mode="line", height=158)
        chart_card.body().addWidget(self.chart)
        self.chart_note = QLabel("")
        self.chart_note.setObjectName("faint")
        chart_card.body().addWidget(self.chart_note)
        root.addWidget(chart_card)

        table_card = Card(padding=16, spacing=10)
        table_card.body().addWidget(
            CardHeader("逐日明细", "包含周期内的每一天（无活动的日期按 0 展示）"))
        self.table = make_table(
            ["日期", "上传", "下载", "总流量", "占当日总流量", "占该应用总流量"],
            stretch_col=4, align_right=(1, 2, 3, 4, 5),
        )
        for col, width in ((0, 140), (1, 130), (2, 130), (3, 150), (5, 165)):
            self.table.setColumnWidth(col, width)
        self.table.setItemDelegateForColumn(4, ShareBarDelegate("primary", self.table))
        self.table.setMinimumHeight(300)
        table_card.body().addWidget(self.table, 1)
        self.empty = EmptyState("请选择一个应用", "从「应用排行」双击任意应用也可直接跳转到此页")
        table_card.body().addWidget(self.empty)
        root.addWidget(table_card, 1)

    # ------------------------------------------------------------------ 交互
    def _on_pick(self, app_id: int):
        if app_id is None:
            return
        self._app_id = int(app_id)
        self._reload()

    def _on_export(self):
        if self._app_id is None:
            return
        self.exportRequested.emit(self._app_id)

    def show_app(self, app_id: int, rng: DateRange | None = None):
        """从其它页面跳转过来时调用。"""
        if rng is not None:
            self._range = rng
        self._app_id = int(app_id)
        self._sync_picker()
        self.picker.set_current(self._app_id)
        self._reload()

    # ------------------------------------------------------------------ 刷新
    def refresh(self, rng: DateRange):
        self._range = rng
        self._sync_picker()
        self._reload()

    def _sync_picker(self):
        apps = self.ctx.stats.all_apps(self._range)
        ids = tuple(a.app_id for a in apps)
        self._known_ids = ids
        if self._app_id is None or self._app_id not in ids:
            self._app_id = apps[0].app_id if apps else None
        self.picker.set_apps(apps, self._app_id)

    def _reload(self):
        self.export_btn.setEnabled(self._app_id is not None)
        if self._app_id is None:
            self._show_empty("所选周期内没有可展示的应用", "换一个统计周期，或等采集引擎积累数据后再看")
            return
        detail = self.ctx.stats.app_detail(self._app_id, self._range)
        if detail is None:
            self._show_empty("该应用已无数据", "历史数据可能已超出保留周期")
            return
        self._render(detail)

    def _set_meta(self, text: str, tip: str = ""):
        """进程路径可能很长：按可用宽度做中间省略，完整内容放进气泡。"""
        self.app_meta.setToolTip(tip or text)
        fm = QFontMetrics(self.app_meta.font())
        budget = max(240, min(640, self.width() - 96))
        self.app_meta.setText(fm.elidedText(text, Qt.ElideMiddle, budget))

    def _show_empty(self, title: str, desc: str):
        self.table.setVisible(False)
        self.empty.setVisible(True)
        self.empty.set_text(title, desc)
        self.chart.set_points([])
        for card in (self.kpi_total, self.kpi_down, self.kpi_up, self.kpi_share):
            card.set("—", "")
        self.app_meta.setText("")
        self.app_meta.setToolTip("")
        self.chart_note.setText("")

    def _render(self, detail: AppDetail):
        app = detail.app
        self.table.setVisible(True)
        self.empty.setVisible(False)

        self.kpi_total.set(format_bytes(app.total),
                           f"活跃 {app.days_active} 天 · 日均 {format_bytes(detail.avg_per_active_day)}")
        self.kpi_down.set(format_bytes(app.download),
                          f"占本应用 {format_percent(app.download / app.total if app.total else 0)}")
        self.kpi_up.set(format_bytes(app.upload),
                        f"占本应用 {format_percent(app.upload / app.total if app.total else 0)}")
        self.kpi_share.set(format_percent(app.share),
                           f"全网 {format_bytes(detail.range_total)} · 排名第 {app.rank or '—'}")

        if app.kind == "unclassified":
            self._set_meta(UNCLASSIFIED_META, UNCLASSIFIED_TIP)
        else:
            self._set_meta(
                (app.exe_path or "进程路径未知") +
                (f"　·　首次出现 {day_str(detail.first_day)}" if detail.first_day else "")
            )

        self.chart.set_points(detail.rows)
        if app.total:
            peak = detail.peak
            self.chart_note.setText(
                f"统计周期 {self._range.label()}（{self._range.length} 天）　·　"
                f"总流量 {format_bytes(app.total)} = 下载 {format_bytes(app.download)} + "
                f"上传 {format_bytes(app.upload)}"
                + (f"　·　峰值 {day_str(peak.day)} {format_bytes(peak.total)}" if peak and peak.total else "")
            )
        else:
            self.chart_note.setText(
                f"统计周期 {self._range.label()}　·　该应用在此期间没有产生网络流量")

        rows = list(reversed(detail.rows))
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.table.setItem(i, 0, num_item(day_str(row.day), align=Qt.AlignLeft | Qt.AlignVCenter))
            self.table.setItem(i, 1, num_item(format_bytes(row.upload, empty_zero=True)))
            self.table.setItem(i, 2, num_item(format_bytes(row.download, empty_zero=True)))
            self.table.setItem(i, 3, num_item(format_bytes(row.total), bold=True))
            item = num_item(format_percent(row.app_share_of_day))
            item.setData(Qt.UserRole, row.app_share_of_day)
            self.table.setItem(i, 4, item)
            self.table.setItem(i, 5, num_item(format_percent(row.app_share)))
        self.table.setUpdatesEnabled(True)
