"""界面模块 —— 通用控件。

包括卡片、KPI、徽章、空状态、分段选择器、表格辅助与「占比条」委托，
所有页面复用这些零件以保证风格统一。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QScrollArea, QSizePolicy,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .theme import C, qcolor


# ---------------------------------------------------------------- 基础容器
class Card(QFrame):
    """圆角白卡。"""

    def __init__(self, parent=None, *, padding: int = 16, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(padding, padding, padding, padding)
        self._lay.setSpacing(spacing)

    def body(self) -> QVBoxLayout:
        return self._lay

    def add(self, widget: QWidget):
        self._lay.addWidget(widget)
        return widget


class CardHeader(QWidget):
    """卡片标题行：左侧标题 + 说明，右侧可放操作控件。"""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        # 标题行高度固定，避免卡片留白时被纵向拉伸
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        box.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("cardSub")
        self.subtitle.setVisible(bool(subtitle))
        box.addWidget(self.subtitle)
        lay.addLayout(box)
        lay.addStretch(1)
        self._lay = lay

    def add_right(self, widget: QWidget):
        self._lay.addWidget(widget)
        return widget


class KpiCard(Card):
    """数值卡：标签 / 主数值 / 辅助说明。"""

    def __init__(self, label: str, accent: str = "text", parent=None):
        super().__init__(parent, padding=16, spacing=6)
        self.setMinimumHeight(88)
        self.label = QLabel(label)
        self.label.setObjectName("kpiLabel")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.value.setStyleSheet(f"color: {C[accent]};")
        self.sub = QLabel("")
        self.sub.setObjectName("kpiSub")
        self.body().addWidget(self.label)
        self.body().addWidget(self.value)
        self.body().addWidget(self.sub)

    def set(self, value: str, sub: str = ""):
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))


class Badge(QLabel):
    """彩色小徽章（数据源、权限、状态）。"""

    def __init__(self, text: str = "", tone: str = "primary", parent=None):
        super().__init__(text, parent)
        self._tone = tone
        self.setAlignment(Qt.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str):
        self._tone = tone
        palette = {
            "primary": (C["primary_soft"], C["primary"]),
            "ok": ("#E7F7F3", C["ok"]),
            "warn": ("#FCF3E3", "#B9812B"),
            "danger": ("#FDEEEE", C["danger"]),
            "muted": ("#F1F3F8", C["muted"]),
        }
        bg, fg = palette.get(tone, palette["muted"])
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 9px;"
            f"font-size:11px; font-weight:600;"
        )

    def set_state(self, text: str, tone: str):
        self.setText(text)
        self.set_tone(tone)


class EmptyState(QWidget):
    """空状态占位：图形 + 标题 + 说明。"""

    def __init__(self, title: str = "暂无数据", desc: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 26, 16, 26)
        lay.setSpacing(8)
        lay.addStretch(1)
        self._glyph = _EmptyGlyph(self)
        lay.addWidget(self._glyph, 0, Qt.AlignHCenter)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"font-size:13px; font-weight:600; color:{C['muted']};")
        self.desc = QLabel(desc)
        self.desc.setAlignment(Qt.AlignCenter)
        self.desc.setWordWrap(True)
        self.desc.setMinimumWidth(280)
        self.desc.setStyleSheet(f"font-size:12px; color:{C['faint']};")
        self.desc.setVisible(bool(desc))
        lay.addWidget(self.title)
        lay.addWidget(self.desc)
        lay.addStretch(1)

    def set_text(self, title: str, desc: str = ""):
        self.title.setText(title)
        self.desc.setText(desc)
        self.desc.setVisible(bool(desc))


class _EmptyGlyph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 54)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#F0F3FA"))
        p.drawEllipse(QRectF(0, 0, 54, 54))
        pen = QPen(QColor(C["faint"]))
        pen.setWidth(3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for i, h in enumerate((10, 18, 7)):
            x = 18 + i * 8
            p.drawLine(x, 34, x, 34 - h)


class SearchBox(QLineEdit):
    """带占位提示的搜索框。"""

    def __init__(self, placeholder: str = "搜索应用名称…", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(230)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("divider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class ScrollHost(QScrollArea):
    """纵向滚动容器：窗口变小时页面整体滚动，而不是把卡片压扁。"""

    def __init__(self, parent=None, *, spacing: int = 14,
                 margins: tuple[int, int, int, int] = (0, 0, 8, 0)):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        holder = QWidget()
        holder.setObjectName("scrollBody")
        self._lay = QVBoxLayout(holder)
        self._lay.setContentsMargins(*margins)
        self._lay.setSpacing(spacing)
        self.setWidget(holder)

    def content_layout(self) -> QVBoxLayout:
        return self._lay


class SegmentedControl(QWidget):
    """分段选择器（今日 / 近7天 / 近30天 / 自定义）。"""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._buttons: dict[str, QWidget] = {}
        from PySide6.QtWidgets import QPushButton

        for key, text in options:
            btn = QPushButton(text)
            btn.setObjectName("seg")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.select(k))
            lay.addWidget(btn)
            self._buttons[key] = btn
        self._current = ""

    def select(self, key: str, *, emit: bool = True):
        if key not in self._buttons:
            return
        for k, btn in self._buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        changed = key != self._current
        self._current = key
        if emit and changed:
            self.changed.emit(key)

    def current(self) -> str:
        return self._current

    def set_text(self, key: str, text: str):
        if key in self._buttons:
            self._buttons[key].setText(text)


# ---------------------------------------------------------------- 表格辅助
def make_table(headers: list[str], *, stretch_col: int = 1,
               align_right: tuple[int, ...] = (),
               align_center: tuple[int, ...] = ()) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(Qt.NoFocus)
    table.setWordWrap(False)
    table.verticalHeader().setDefaultSectionSize(38)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.Fixed)
    header.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    header.setFixedHeight(36)
    # 表头与单元格内容对齐，数字列右对齐更易读
    for col in align_right:
        item = table.horizontalHeaderItem(col)
        if item is not None:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    for col in align_center:
        item = table.horizontalHeaderItem(col)
        if item is not None:
            item.setTextAlignment(Qt.AlignCenter)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return table


def num_item(text: str, *, bold: bool = False, color: str | None = None,
             align=Qt.AlignRight | Qt.AlignVCenter) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    if bold:
        f = item.font()
        f.setWeight(QFont.DemiBold)
        item.setFont(f)
    if color:
        item.setForeground(QColor(color))
    return item


class ShareBarDelegate(QStyledItemDelegate):
    """在单元格内绘制占比进度条（浅底 + 实色条），文字右对齐。"""

    def __init__(self, color: str = "primary", parent=None):
        super().__init__(parent)
        self._color = color

    def paint(self, painter: QPainter, option, index):
        ratio = index.data(Qt.UserRole)
        text = index.data(Qt.DisplayRole) or ""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(8, 11, -8, -11)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F2F5FB"))
        painter.drawRoundedRect(rect, 4, 4)
        if isinstance(ratio, (int, float)) and ratio > 0:
            w = max(3.0, rect.width() * min(1.0, float(ratio)))
            painter.setBrush(qcolor(self._color, 190))
            painter.drawRoundedRect(QRectF(rect.left(), rect.top(), w, rect.height()), 4, 4)
        painter.setPen(QColor(C["text"]))
        f = painter.font()
        f.setPointSizeF(max(8.0, f.pointSizeF() - 0.5))
        painter.setFont(f)
        painter.drawText(option.rect.adjusted(0, 0, -10, 0),
                         Qt.AlignRight | Qt.AlignVCenter, str(text))
        painter.restore()


def kind_label(kind: str) -> str:
    return {"system": "系统", "unclassified": "未分类"}.get(kind, "")


# 「未分类」不是某个软件，只是无法归属到进程的流量集合。界面里悬停即用这段说明解释来源。
# 纯文本 + 手工换行：Qt 的提示气泡对富文本会强制折行，纯文本能保持整齐的短行。
UNCLASSIFIED_TIP = (
    "「未分类」不是一个具体软件\n"
    "它是无法可靠归属到具体进程的流量集合\n"
    "常见来源：\n"
    "· 系统进程、驱动层或虚拟网卡的收发\n"
    "· 采样时进程已退出，查不到对应程序\n"
    "· 网卡总量与逐进程合计的差额（校准部分）\n"
    "占比通常很小，可忽略，不影响其它应用的统计口径。\n"
    "如需核对，可在「设置 → 未分类校准」里开关后对比。"
)

UNCLASSIFIED_NOTE = "「未分类」不是具体软件，悬停可看说明"
UNCLASSIFIED_META = "多来源汇总：无法归属到具体进程的流量（并非单一软件）"


def clear_layout(layout):
    """清空布局内的全部控件（用于列表/表格区重建）。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)


def elide(text: str, width: int = 220) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
