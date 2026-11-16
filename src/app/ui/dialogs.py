"""界面模块 —— 日期范围选择对话框。"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.daterange import DateRange, RangeError
from .theme import C

PRESETS = ((1, "今天"), (7, "最近 7 天"), (14, "最近 14 天"), (30, "最近 30 天"))


class RangeDialog(QDialog):
    """选择任意起止日期（最长 31 天，且不晚于今天）。"""

    def __init__(self, current: DateRange, max_days: int = 31, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择统计周期")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._max_days = max_days
        self._value = current

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        tip = QLabel(f"起止日期均包含在内，最长 {max_days} 天，结束日期不晚于今天。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        root.addWidget(tip)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.start_edit = QDateEdit()
        self.end_edit = QDateEdit()
        for edit, value in ((self.start_edit, current.start), (self.end_edit, current.end)):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setDate(QDate(value.year, value.month, value.day))
            edit.setMaximumDate(QDate.currentDate())
            edit.setMinimumWidth(132)
            edit.dateChanged.connect(self._validate)
        row.addWidget(QLabel("起始"))
        row.addWidget(self.start_edit)
        row.addWidget(QLabel("结束"))
        row.addWidget(self.end_edit)
        row.addStretch(1)
        root.addLayout(row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        for days, text in PRESETS:
            btn = QPushButton(text)
            btn.setObjectName("seg")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, d=days: self._apply_preset(d))
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        root.addLayout(preset_row)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{C['danger']}; font-size:12px;")
        self.error.setVisible(False)
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

        self._validate()

    # ------------------------------------------------------------------
    def _apply_preset(self, days: int):
        end = dt.date.today()
        start = end - dt.timedelta(days=days - 1)
        self.start_edit.setDate(QDate(start.year, start.month, start.day))
        self.end_edit.setDate(QDate(end.year, end.month, end.day))

    def _current(self) -> DateRange:
        s = self.start_edit.date().toPython()
        e = self.end_edit.date().toPython()
        return DateRange(s, e)

    def _validate(self) -> bool:
        rng = self._current()
        try:
            rng.validate(max_days=self._max_days)
        except RangeError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return False
        self.error.setVisible(False)
        return True

    def _accept(self):
        if not self._validate():
            return
        self._value = self._current()
        self.accept()

    def value(self) -> DateRange:
        return self._value


class CloseChoiceDialog(QDialog):
    """点关闭按钮时的二选一：留在后台继续统计 / 直接关闭退出。

    action:  "tray" | "quit" | None（None 表示取消，什么都不做）
    remember: 是否记住本次选择
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关闭 FlowLens")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.action: str | None = None
        self.remember = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("要退出程序，还是留在后台继续统计？")
        title.setStyleSheet(f"font-size:14px; font-weight:600; color:{C['text']};")
        root.addWidget(title)

        desc = QLabel(
            "留在后台：窗口收起，采集照常进行，流量数据不会中断；"
            "双击任务栏右下角的托盘图标即可重新打开（图标可能在 ^ 展开区里）。\n"
            "直接关闭：结束进程、停止统计，已经记录的数据不会丢失。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        root.addWidget(desc)

        self.remember_check = QCheckBox("记住我的选择，下次不再询问（可在设置中修改）")
        self.remember_check.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        root.addWidget(self.remember_check)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        quit_btn = QPushButton("直接关闭")
        quit_btn.clicked.connect(lambda: self._pick("quit"))
        tray_btn = QPushButton("留在后台继续统计")
        tray_btn.setObjectName("primary")
        tray_btn.setDefault(True)
        tray_btn.setMinimumWidth(140)
        tray_btn.clicked.connect(lambda: self._pick("tray"))
        row.addWidget(quit_btn)
        row.addWidget(tray_btn)
        root.addLayout(row)

    def _pick(self, action: str):
        self.action = action
        self.remember = self.remember_check.isChecked()
        self.accept()


class ConfirmDialog(QDialog):
    """通用确认框（供导出完成等场景使用）。"""

    def __init__(self, title: str, text: str, buttons: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)
        label = QLabel(text)
        label.setWordWrap(True)
        root.addWidget(label)
        row = QHBoxLayout()
        row.addStretch(1)
        self._choice = None
        for name in reversed(buttons):
            btn = QPushButton(name)
            if name == buttons[0]:          # 第一个按钮为主操作
                btn.setObjectName("primary")
            btn.clicked.connect(lambda _=False, n=name: self._pick(n))
            row.addWidget(btn)
        root.addLayout(row)

    def _pick(self, name: str):
        self._choice = name
        self.accept()

    def choice(self) -> str | None:
        return self._choice
