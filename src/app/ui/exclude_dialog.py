"""界面模块 —— 排除应用选择对话框。

设置页里「排除的应用」原来是纯文本框，要用户自己敲进程名。这里提供一个
可点选的窗口：列出数据库里出现过的应用，勾选即排除，支持搜索和手动补充。

排除按**进程名（key，小写）**精确匹配，同一程序的所有进程实例会一起被排除；
界面显示的是展示名，因此每行同时标注进程名，避免重名混淆。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.models import AppCandidate
from ..core.units import format_bytes
from .theme import C

KEY_ROLE = Qt.UserRole              # 进程名（小写）
SEARCH_ROLE = Qt.UserRole + 1       # 「名称 + 进程名」小写串，供搜索
NAME_WIDTH = 208
KEY_WIDTH = 168
ROW_HEIGHT = 38


def _elide(text: str, width: int, widget: QWidget) -> str:
    return QFontMetrics(widget.font()).elidedText(text, Qt.ElideRight, width)


class _CandidateRow(QWidget):
    """列表某一行：勾选框 + 应用名 +（系统标签）+ 进程名 + 累计流量。

    整行不接收鼠标事件，点击落到 QListWidget 的 item 上，
    由对话框统一切换勾选状态，这样点行的任意位置都能勾上。
    """

    def __init__(self, cand: AppCandidate, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(9)

        self.check = QCheckBox()
        self.check.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.check, 0, Qt.AlignVCenter)

        name = QLabel(_elide(cand.name, NAME_WIDTH, self))
        name.setObjectName("exclName")
        name.setToolTip(cand.name)
        lay.addWidget(name)

        if cand.is_system:
            tag = QLabel("系统进程")
            tag.setObjectName("exclTag")
            lay.addWidget(tag)

        key = QLabel(_elide(cand.key, KEY_WIDTH, self))
        key.setObjectName("exclKey")
        key.setToolTip(cand.key)
        lay.addWidget(key)

        lay.addStretch(1)

        total = QLabel(format_bytes(cand.total) if cand.total else "—")
        total.setObjectName("exclTotal")
        total.setToolTip("该应用的历史累计流量（含所有日期）")
        lay.addWidget(total)

    def set_checked(self, checked: bool) -> None:
        self.check.setChecked(checked)


class ExcludeDialog(QDialog):
    """勾选要从统计中排除的应用。"""

    def __init__(self, candidates: list[AppCandidate], excluded_keys=(),
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择要排除的应用")
        self.setModal(True)
        self.resize(640, 568)
        self._cands = list(candidates)
        self._excluded = {str(k).strip().lower() for k in excluded_keys if str(k).strip()}
        self._build()
        self._populate()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(11)

        tip = QLabel(
            "勾选的应用不计入流量统计（上传、下载都不再记录）。排除按「进程名」匹配，"
            "同一程序的所有进程会一起被排除；已记录的历史数据不会删除。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        root.addWidget(tip)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索应用名或进程名…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search, 1)

        all_btn = QPushButton("全选")
        all_btn.clicked.connect(lambda: self._set_visible(True))
        search_row.addWidget(all_btn)

        none_btn = QPushButton("清空")
        none_btn.clicked.connect(lambda: self._set_visible(False))
        search_row.addWidget(none_btn)
        root.addLayout(search_row)

        self.list = QListWidget()
        self.list.setObjectName("exclList")
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.list, 1)

        self.empty = QLabel("数据库里还没有记录到任何应用，可以在下方手动输入进程名。")
        self.empty.setObjectName("exclHint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setVisible(False)
        root.addWidget(self.empty)

        # 手动补充：库里没出现过的进程也能排除
        manual_row = QHBoxLayout()
        manual_row.setSpacing(8)
        manual_label = QLabel("手动添加")
        manual_label.setStyleSheet(f"color:{C['text']};")
        manual_row.addWidget(manual_label)
        self.manual_edit = QLineEdit()
        self.manual_edit.setPlaceholderText(
            "进程名，例如 thunder.exe（需与任务管理器「详细信息」里的名称一致）")
        self.manual_edit.returnPressed.connect(self._add_manual)
        manual_row.addWidget(self.manual_edit, 1)
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_manual)
        manual_row.addWidget(add_btn)
        root.addLayout(manual_row)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{C['warn']}; font-size:12px;")
        self.hint.setVisible(False)
        root.addWidget(self.hint)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        bottom.addWidget(self.count_label)
        bottom.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        ok.setMinimumWidth(96)
        ok.clicked.connect(self.accept)
        bottom.addWidget(ok)
        root.addLayout(bottom)

    # ------------------------------------------------------------------ 数据
    def _populate(self):
        self.list.blockSignals(True)
        self.list.clear()
        for cand in self._cands:
            self._add_item(cand)
        self.list.blockSignals(False)
        self._apply_filter(self.search.text())
        self._update_count()

    def _add_item(self, cand: AppCandidate, at_top: bool = False) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(KEY_ROLE, cand.key)
        item.setData(SEARCH_ROLE, f"{cand.name} {cand.key}".lower())
        item.setFlags(Qt.ItemIsEnabled)      # 不用 item 自带勾选，避免与行内勾选框重复
        item.setSizeHint(QSize(0, ROW_HEIGHT))

        row = _CandidateRow(cand)
        row.check.setChecked(cand.key.lower() in self._excluded)
        if at_top:
            self.list.insertItem(0, item)
        else:
            self.list.addItem(item)
        self.list.setItemWidget(item, row)
        return item

    def _row_of(self, item: QListWidgetItem) -> _CandidateRow | None:
        """取行 widget（QListWidgetItem 不可哈希，所以不另建 map）。"""
        row = self.list.itemWidget(item)
        return row if isinstance(row, _CandidateRow) else None

    def _is_checked(self, item: QListWidgetItem) -> bool:
        row = self._row_of(item)
        return bool(row and row.check.isChecked())

    def _on_item_clicked(self, item: QListWidgetItem):
        row = self._row_of(item)
        if row is not None:
            row.check.setChecked(not row.check.isChecked())
            self._update_count()

    def _set_visible(self, checked: bool):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                row = self._row_of(item)
                if row is not None:
                    row.check.setChecked(checked)
        self._update_count()

    def _apply_filter(self, text: str):
        q = (text or "").strip().lower()
        shown = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            hay = str(item.data(SEARCH_ROLE) or "")
            ok = (not q) or (q in hay)
            item.setHidden(not ok)
            if ok:
                shown += 1
        if q and shown == 0:
            self.hint.setText(f"没有匹配「{text.strip()}」的应用，可以在下方手动添加进程名。")
            self.hint.setVisible(True)
        else:
            self.hint.setVisible(False)
        self._update_count()

    def _add_manual(self):
        text = self.manual_edit.text().strip().lower()
        if not text:
            return
        if " " in text:
            self.hint.setText("进程名不能包含空格，请填写任务管理器「详细信息」里的名称。")
            self.hint.setVisible(True)
            return
        if "." not in text:
            text += ".exe"
        # 已在列表里：直接勾上并滚过去
        for i in range(self.list.count()):
            item = self.list.item(i)
            if str(item.data(KEY_ROLE)).lower() == text:
                row = self._row_of(item)
                if row is not None:
                    row.check.setChecked(True)
                self.search.clear()
                self.list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                self.manual_edit.clear()
                self.hint.setVisible(False)
                self._update_count()
                return
        cand = AppCandidate(key=text, name=text, kind="app", total=0)
        self._cands.insert(0, cand)
        item = self._add_item(cand, at_top=True)
        row = self._row_of(item)
        if row is not None:
            row.check.setChecked(True)
        self.search.clear()
        self.list.scrollToItem(item, QAbstractItemView.PositionAtTop)
        self.manual_edit.clear()
        self.hint.setVisible(False)
        self._update_count()

    def _update_count(self):
        total = self.list.count()
        picked = sum(1 for i in range(total) if self._is_checked(self.list.item(i)))
        self.count_label.setText(f"已勾选 {picked} 个　·　共 {total} 个应用")
        self.empty.setVisible(total == 0)

    # ------------------------------------------------------------------ 结果
    def selected(self) -> list[str]:
        """返回勾选的进程名（小写、去重、按字母序）。"""
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if self._is_checked(item):
                out.append(str(item.data(KEY_ROLE)).lower())
        return sorted({x for x in out if x})
