"""界面模块 —— 应用排行页。

支持按应用名称搜索、按流量/名称排序、升/降序切换，双击进入应用详情。
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from ...core.daterange import DateRange
from ...core.units import format_bytes, format_percent
from ..context import UiContext
from ..theme import C
from ..widgets import (Card, CardHeader, EmptyState, SearchBox, ShareBarDelegate,
                      UNCLASSIFIED_NOTE, UNCLASSIFIED_TIP, make_table, num_item)

SORT_OPTIONS = [
    ("total", "按总流量"),
    ("upload", "按上传流量"),
    ("download", "按下载流量"),
    ("avg", "按日均流量"),
    ("name", "按应用名称"),
]


class RankingPage(QWidget):
    appSelected = Signal(int)

    def __init__(self, ctx: UiContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._range = DateRange.last_days(30)
        self._search = ""
        self._sort = "total"
        self._desc = True
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        card = Card(padding=16, spacing=12)
        root.addWidget(card, 1)

        head = CardHeader("应用流量排行", "按应用/进程归类，同一程序的多进程已合并统计")
        self.count_label = QLabel("")
        self.count_label.setObjectName("faint")
        head.add_right(self.count_label)

        self.filter_card = card
        card.body().addWidget(head)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = SearchBox("搜索应用名称，例如 chrome")
        self.search.textChanged.connect(self._on_search)
        toolbar.addWidget(self.search)

        self.sort_box = QComboBox()
        for key, text in SORT_OPTIONS:
            self.sort_box.addItem(text, key)
        self.sort_box.currentIndexChanged.connect(self._on_sort)
        self.sort_box.setMinimumWidth(132)
        toolbar.addWidget(self.sort_box)

        self.order_btn = QPushButton("降序")
        self.order_btn.setObjectName("seg")
        self.order_btn.setCursor(Qt.PointingHandCursor)
        self.order_btn.clicked.connect(self._toggle_order)
        toolbar.addWidget(self.order_btn)

        toolbar.addStretch(1)
        card.body().addLayout(toolbar)

        self.stack = QStackedWidget()
        self.table = make_table(
            ["名次", "应用", "上传", "下载", "总流量", "占比", "活跃天数"],
            stretch_col=1, align_right=(2, 3, 4, 5), align_center=(0, 6),
        )
        widths = [62, 0, 118, 118, 132, 168, 92]
        for i, w in enumerate(widths):
            if w:
                self.table.setColumnWidth(i, w)
        self.table.setItemDelegateForColumn(5, ShareBarDelegate("primary", self.table))
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.stack.addWidget(self.table)

        self.empty = EmptyState("没有匹配的应用",
                                "试试调整搜索关键词，或把统计周期改到有网络活动的日期")
        empty_wrap = QWidget()
        el = QVBoxLayout(empty_wrap)
        el.setContentsMargins(0, 40, 0, 40)
        el.addWidget(self.empty)
        self.stack.addWidget(empty_wrap)
        card.body().addWidget(self.stack, 1)

        self.foot = QLabel("")
        self.foot.setObjectName("faint")
        card.body().addWidget(self.foot)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._reload)

    # ------------------------------------------------------------------ 交互
    def _on_search(self, text: str):
        self._search = text.strip()
        self._timer.start()

    def _on_sort(self, _index: int):
        self._sort = self.sort_box.currentData() or "total"
        self._reload()

    def _toggle_order(self):
        self._desc = not self._desc
        self.order_btn.setText("降序" if self._desc else "升序")
        self._reload()

    def _on_double_click(self, row: int, _col: int):
        item = self.table.item(row, 1)
        if item is None:
            return
        app_id = item.data(Qt.UserRole)
        if app_id:
            self.appSelected.emit(int(app_id))

    # ------------------------------------------------------------------ 刷新
    def refresh(self, rng: DateRange):
        self._range = rng
        self._reload()

    def _reload(self):
        rng = self._range
        current = self.table.currentRow()
        selected_id = None
        if current >= 0:
            item = self.table.item(current, 1)
            if item is not None:
                selected_id = item.data(Qt.UserRole)
        scroll = self.table.verticalScrollBar().value()

        rows = self.ctx.stats.ranking(rng, search=self._search, sort_by=self._sort,
                                      descending=self._desc)

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for r, agg in enumerate(rows):
            self.table.setItem(r, 0, num_item(str(agg.rank), align=Qt.AlignCenter))
            name_item = num_item(agg.name, align=Qt.AlignLeft | Qt.AlignVCenter)
            name_item.setData(Qt.UserRole, agg.app_id)
            if agg.kind == "system":
                name_item.setText(f"{agg.name}　·　系统")
                name_item.setForeground(QColor(C["muted"]))
            elif agg.kind == "unclassified":
                name_item.setForeground(QColor(C["muted"]))
            if agg.exe_path:
                name_item.setToolTip(agg.exe_path)
            self.table.setItem(r, 1, name_item)
            self.table.setItem(r, 2, num_item(format_bytes(agg.upload)))
            self.table.setItem(r, 3, num_item(format_bytes(agg.download)))
            self.table.setItem(r, 4, num_item(format_bytes(agg.total), bold=True))
            share_item = num_item(format_percent(agg.share), align=Qt.AlignRight | Qt.AlignVCenter)
            share_item.setData(Qt.UserRole, agg.share)
            self.table.setItem(r, 5, share_item)
            self.table.setItem(r, 6, num_item(f"{agg.days_active} 天", align=Qt.AlignCenter))
            if agg.kind == "unclassified":
                # 整行都可悬停，鼠标落在任意单元格都能看到说明气泡
                for col in range(self.table.columnCount()):
                    cell = self.table.item(r, col)
                    if cell is not None:
                        cell.setToolTip(UNCLASSIFIED_TIP)
        self.table.setUpdatesEnabled(True)

        has_rows = bool(rows)
        self.stack.setCurrentIndex(0 if has_rows else 1)
        if not has_rows:
            if self._search:
                self.empty.set_text("没有匹配的应用",
                                    "试试调整搜索关键词，或把统计周期改到有网络活动的日期")
            else:
                self.empty.set_text("暂无统计数据",
                                    "采集引擎正在积累数据；刚启动时通常需要几十秒才会出现第一批记录")
        self.count_label.setText(f"共 {len(rows)} 个应用" if has_rows else "")

        if has_rows:
            note = f"统计周期 {rng.label()}（{rng.length} 天）　·　"
            if self._search:
                note += f"筛选条件：名称包含「{self._search}」　·　"
            note += "占比按该周期全网总流量计算　·　双击任意行查看应用详情"
            if any(agg.kind == "unclassified" for agg in rows):
                note += f"　·　{UNCLASSIFIED_NOTE}"
            self.foot.setText(note)
            # 尽量保持刷新前的选中行与滚动位置
            if selected_id:
                for r in range(self.table.rowCount()):
                    item = self.table.item(r, 1)
                    if item and item.data(Qt.UserRole) == selected_id:
                        self.table.selectRow(r)
                        break
            self.table.verticalScrollBar().setValue(scroll)
        else:
            self.foot.setText(f"统计周期 {rng.label()}（{rng.length} 天）")
