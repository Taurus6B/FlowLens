"""界面组件 —— 应用选择器。

详情页的「选择应用」需要两种取用方式并存：
· 直接输入关键字搜索（知道程序名的人，敲两个字母就要跳过去）
· 展开列表点选（不知道确切名字、想先看谁流量大的人）

所以做成「看起来像输入框的按钮」：点击展开浮层，浮层顶部是搜索框，
下面是带总流量的应用列表，支持 ↑↓ 选择、回车确认、Esc 关闭。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QVBoxLayout,
                               QWidget)

from ..core.units import format_bytes

ROW_H = 34          # 单行高度（浮层里）
LIST_MAX_ROWS = 9   # 浮层最多显示几行，超出滚动
NAME_ELIDE = 200    # 字段里应用名的最大像素宽度


def _tag_for(kind: str) -> str:
    """列表右侧的小标签：说明这不是普通程序。"""
    if kind == "system":
        return "系统"
    if kind == "unclassified":
        return "多来源汇总"
    return ""


class _AppRow(QWidget):
    """浮层里的一行：名称（+类型标签）……总流量。"""

    def __init__(self, agg, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)

        name = QLabel(agg.name)
        name.setObjectName("pickerRowName")
        if agg.kind != "app":
            name.setStyleSheet("color: #6B7688;")
        lay.addWidget(name)

        tag_text = _tag_for(agg.kind)
        if tag_text:
            tag = QLabel(tag_text)
            tag.setObjectName("pickerRowTag")
            lay.addWidget(tag)

        lay.addStretch(1)
        total = QLabel(format_bytes(agg.total))
        total.setObjectName("pickerRowTotal")
        lay.addWidget(total)


class AppPickerPopup(QFrame):
    """点击选择器后展开的浮层：搜索框 + 应用列表。"""

    picked = Signal(int)
    closed = Signal()

    def __init__(self, anchor: QWidget):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("pickerPopup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._anchor = anchor
        self._apps: list = []
        self._picked = False
        self._shown = 0        # 当前可见行数（浮层未展开时 isVisible() 不可靠，故自己记）

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setObjectName("pickerSearch")
        self.search.setPlaceholderText("搜索应用名称    ↑↓ 选择    Enter 确认")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)

        self.list = QListWidget()
        self.list.setObjectName("pickerList")
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.itemClicked.connect(self._choose)
        self.list.itemActivated.connect(self._choose)
        lay.addWidget(self.list, 1)

        self.hint = QLabel("没有匹配的应用")
        self.hint.setObjectName("pickerHint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.hide()
        lay.addWidget(self.hint)

    # ------------------------------------------------------------------ 数据
    def set_apps(self, apps, current_id: int | None = None):
        self._apps = list(apps)
        self._picked = False
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)

        self.list.clear()
        for agg in self._apps:
            item = QListWidgetItem(self.list)
            item.setData(Qt.UserRole, agg.app_id)
            item.setSizeHint(QSize(0, ROW_H))
            item.setToolTip(agg.exe_path or "")
            self.list.setItemWidget(item, _AppRow(agg, self.list))

        self.hint.setVisible(not self._apps)
        self.list.setVisible(bool(self._apps))
        self._shown = len(self._apps)

        # 定位到当前选中的应用
        row = 0
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == current_id:
                row = i
                break
        if self.list.count():
            self.list.setCurrentRow(row)

    def _visible_rows(self) -> list[int]:
        return [i for i in range(self.list.count()) if not self.list.item(i).isHidden()]

    # ------------------------------------------------------------------ 交互
    def _apply_filter(self, text: str):
        q = (text or "").strip().lower()
        shown = 0
        first = -1
        for i in range(self.list.count()):
            item = self.list.item(i)
            agg = self._apps[i] if i < len(self._apps) else None
            text_all = f"{agg.name} {agg.key}" if agg is not None else ""
            hit = (not q) or (q in text_all.lower())
            item.setHidden(not hit)
            if hit:
                shown += 1
                if first < 0:
                    first = i
        self.hint.setVisible(shown == 0)
        self.list.setVisible(shown > 0)
        self._shown = shown
        if shown:
            self.list.setCurrentRow(first)
        self._resize_to_content()

    def _move(self, down: bool):
        rows = self._visible_rows()
        if not rows:
            return
        cur = self.list.currentRow()
        if cur not in rows:
            self.list.setCurrentRow(rows[0] if down else rows[-1])
            return
        idx = rows.index(cur)
        nxt = idx + (1 if down else -1)
        nxt = max(0, min(len(rows) - 1, nxt))
        self.list.setCurrentRow(rows[nxt])

    def _choose(self, item):
        if self._picked or item is None or item.isHidden():
            return
        self._picked = True
        app_id = item.data(Qt.UserRole)
        if app_id is not None:
            self.picked.emit(int(app_id))
        self.close()

    def _choose_current(self):
        self._choose(self.list.currentItem())

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.search and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                self._move(key == Qt.Key_Down)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._choose_current()
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def hideEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().hideEvent(event)

    # ------------------------------------------------------------------ 几何
    def _resize_to_content(self):
        has_rows = self._shown > 0
        rows = max(1, min(LIST_MAX_ROWS, self._shown or 1))
        body = rows * ROW_H + 10 if has_rows else self.hint.sizeHint().height() + 10
        h = 10 + self.search.sizeHint().height() + 8 + body + 8
        w = max(360, self._anchor.width())
        screen = (QGuiApplication.screenAt(self._anchor.mapToGlobal(QPoint(0, 0)))
                  or QGuiApplication.primaryScreen())
        avail = screen.availableGeometry()
        w = min(w, avail.width() - 24)
        h = min(h, avail.height() - 40)
        self.resize(w, h)

    def popup(self, current_id: int | None = None):
        """在锚点下方展开（下方放不下就翻到上方）。"""
        self._resize_to_content()
        anchor_global = self._anchor.mapToGlobal(QPoint(0, self._anchor.height() + 6))
        screen = (QGuiApplication.screenAt(self._anchor.mapToGlobal(QPoint(0, 0)))
                  or QGuiApplication.primaryScreen())
        avail = screen.availableGeometry()
        x = min(max(anchor_global.x(), avail.left() + 8), avail.right() - self.width() - 8)
        y = anchor_global.y()
        if y + self.height() > avail.bottom():
            above = self._anchor.mapToGlobal(QPoint(0, -self.height() - 6))
            if above.y() >= avail.top():
                y = above.y()
        self.move(x, max(y, avail.top() + 8))
        self.show()
        self.search.setFocus()
        self.search.selectAll()


class AppPicker(QFrame):
    """像输入框的选择器：显示当前应用，点击展开可搜索的列表。"""

    appPicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("picker")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 32)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 8, 4)
        lay.setSpacing(8)

        self.name_label = QLabel("选择应用")
        self.name_label.setObjectName("pickerName")
        self.total_label = QLabel("")
        self.total_label.setObjectName("pickerTotal")
        self.chevron = QLabel("▾")
        self.chevron.setObjectName("pickerArrow")
        lay.addWidget(self.name_label, 1)
        lay.addWidget(self.total_label)
        lay.addWidget(self.chevron)

        self._apps: list = []
        self._app_id: int | None = None
        self._popup = AppPickerPopup(self)
        self._popup.picked.connect(self._on_picked)
        self._popup.closed.connect(self._on_popup_closed)

    # ------------------------------------------------------------------ 数据
    def set_apps(self, apps, current_id: int | None = None):
        self._apps = list(apps)
        if current_id is not None:
            self._app_id = int(current_id)
        if self._app_id is None and self._apps:
            self._app_id = self._apps[0].app_id
        if self._app_id is not None and all(a.app_id != self._app_id for a in self._apps):
            self._app_id = self._apps[0].app_id if self._apps else None
        self._refresh_field()

    def set_current(self, app_id: int | None):
        self._app_id = int(app_id) if app_id is not None else None
        self._refresh_field()

    def current_id(self) -> int | None:
        return self._app_id

    def _refresh_field(self):
        agg = next((a for a in self._apps if a.app_id == self._app_id), None)
        if agg is None:
            self.name_label.setText("选择应用")
            self.total_label.setText("")
            self.setToolTip("点击选择要查看的应用")
            return
        fm = QFontMetrics(self.name_label.font())
        self.name_label.setText(fm.elidedText(agg.name, Qt.ElideRight, NAME_ELIDE))
        self.total_label.setText(format_bytes(agg.total))
        tip = _tag_for(agg.kind)
        self.setToolTip(f"{agg.name}{'（' + tip + '）' if tip else ''}\n点击展开列表，或直接输入关键字搜索")

    # ------------------------------------------------------------------ 交互
    def _on_picked(self, app_id: int):
        if app_id == self._app_id:
            return
        self._app_id = int(app_id)
        self._refresh_field()
        self.appPicked.emit(int(app_id))

    def _open(self):
        if not self._apps:
            return
        self._popup.set_apps(self._apps, self._app_id)
        self.setProperty("open", True)
        self._repolish()
        self._popup.popup(self._app_id)

    def _on_popup_closed(self):
        self.setProperty("open", False)
        self._repolish()

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def hideEvent(self, event):  # noqa: N802
        self.setProperty("open", False)
        self._repolish()
        super().hideEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self._open()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Down):
            self._open()
            return
        # 焦点在字段上时直接敲字，也能当作搜索：展开并把首字带进搜索框
        text = event.text()
        if text and text.isprintable() and text.strip():
            if not self._apps:
                return
            self._open()
            if self._popup.isVisible():
                self._popup.search.setText(text)
            return
        super().keyPressEvent(event)
