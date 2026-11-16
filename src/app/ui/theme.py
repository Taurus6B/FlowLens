"""界面模块 —— 视觉主题（浅色）。

统一色板与字号，所有控件通过 objectName / 属性选择器取样式，
保证 5 个页面视觉一致。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont

C = {
    "bg": "#F4F6FA",
    "card": "#FFFFFF",
    "border": "#E6EAF2",
    "border_strong": "#D6DCEC",
    "text": "#1A2130",
    "muted": "#6B7688",
    "faint": "#9AA4B8",
    "primary": "#3B6BF5",
    "primary_dark": "#2C55CC",
    "primary_soft": "#EDF2FF",
    "up": "#FFA53B",
    "down": "#3B6BF5",
    "ok": "#12A594",
    "warn": "#E8A33D",
    "danger": "#E5484D",
    "gray_bar": "#C7CEDD",
    "grid": "#EFF2F8",
}


def qcolor(name: str, alpha: int | None = None) -> QColor:
    """按色板键或十六进制色值取颜色，可附加透明度。"""
    value = C.get(name, name) if isinstance(name, str) else C["text"]
    c = QColor(value)
    if not c.isValid():
        c = QColor(C["text"])
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def app_font(size: int = 10, weight: int = 400) -> QFont:
    f = QFont("Microsoft YaHei UI", size)
    if not f.exactMatch():
        f = QFont("Microsoft YaHei", size)
    f.setWeight(QFont.Weight.Normal if weight < 500 else QFont.Weight.DemiBold)
    return f


STYLESHEET = f"""
* {{ outline: none; }}
QWidget {{
    color: {C['text']};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, #root {{ background: {C['bg']}; }}

/* ---------- 侧边栏 ---------- */
#sidebar {{ background: {C['card']}; border-right: 1px solid {C['border']}; }}
#brand {{ font-size: 15px; font-weight: 600; color: {C['text']}; }}
#brandSub {{ font-size: 11px; color: {C['faint']}; }}
#navBtn {{
    text-align: left;
    padding: 9px 14px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: {C['muted']};
    font-size: 13px;
}}
#navBtn:hover {{ background: {C['primary_soft']}; color: {C['primary']}; }}
#navBtn[active="true"] {{
    background: {C['primary_soft']};
    color: {C['primary']};
    font-weight: 600;
}}
#navGroup {{ color: {C['faint']}; font-size: 11px; padding-left: 14px; }}

/* ---------- 卡片 ---------- */
#card {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}
#cardTitle {{ font-size: 14px; font-weight: 600; }}
#cardSub {{ font-size: 12px; color: {C['muted']}; }}
#kpiLabel {{ font-size: 12px; color: {C['muted']}; }}
#kpiValue {{ font-size: 22px; font-weight: 600; }}
#kpiSub {{ font-size: 11px; color: {C['faint']}; }}
#muted {{ color: {C['muted']}; }}
#faint {{ color: {C['faint']}; font-size: 12px; }}
#h1 {{ font-size: 19px; font-weight: 600; }}
#h2 {{ font-size: 15px; font-weight: 600; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {C['card']};
    border: 1px solid {C['border_strong']};
    border-radius: 8px;
    padding: 6px 14px;
    color: {C['text']};
}}
QPushButton:hover {{ border-color: {C['primary']}; color: {C['primary']}; }}
QPushButton:pressed {{ background: {C['primary_soft']}; }}
QPushButton#primary {{
    background: {C['primary']};
    border: 1px solid {C['primary']};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {C['primary_dark']}; border-color: {C['primary_dark']}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {C['muted']}; }}
QPushButton#ghost:hover {{ background: {C['primary_soft']}; color: {C['primary']}; }}
QPushButton#seg {{
    border: 1px solid {C['border_strong']};
    border-radius: 8px;
    padding: 5px 13px;
    background: {C['card']};
    color: {C['muted']};
}}
QPushButton#seg[active="true"] {{
    background: {C['primary']};
    border-color: {C['primary']};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#danger {{ color: {C['danger']}; border-color: #F3C9CA; }}
QPushButton#danger:hover {{ background: #FDF1F1; border-color: {C['danger']}; }}

/* ---------- 输入 ---------- */
QLineEdit, QComboBox, QDateEdit, QSpinBox {{
    background: {C['card']};
    border: 1px solid {C['border_strong']};
    border-radius: 8px;
    padding: 5px 9px;
    min-height: 20px;
    selection-background-color: {C['primary']};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{
    border-color: {C['primary']};
}}
QLineEdit::placeholder {{ color: {C['faint']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {C['card']};
    border: 1px solid {C['border_strong']};
    border-radius: 8px;
    selection-background-color: {C['primary_soft']};
    selection-color: {C['primary']};
    padding: 4px;
    outline: none;
}}
QCheckBox {{ spacing: 7px; color: {C['text']}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
}}

/* ---------- 应用选择器（详情页） ---------- */
QFrame#picker {{
    background: {C['card']};
    border: 1px solid {C['border_strong']};
    border-radius: 8px;
}}
QFrame#picker:hover {{ border-color: #C4CEE6; }}
QFrame#picker[open="true"] {{ border-color: {C['primary']}; }}
#pickerName {{ font-size: 13px; }}
#pickerTotal {{ font-size: 12px; color: {C['muted']}; }}
#pickerArrow {{ font-size: 10px; color: {C['faint']}; }}
QFrame#pickerPopup {{
    background: {C['card']};
    border: 1px solid {C['border_strong']};
    border-radius: 10px;
}}
QLineEdit#pickerSearch {{ padding: 5px 9px; font-size: 12px; }}
QListWidget#pickerList {{ background: transparent; border: none; outline: none; }}
QListWidget#pickerList::item {{ border-radius: 6px; }}
QListWidget#pickerList::item:hover {{ background: #F3F6FD; }}
QListWidget#pickerList::item:selected {{ background: {C['primary_soft']}; }}
#pickerRowName {{ font-size: 13px; }}
#pickerRowTag {{ font-size: 11px; color: {C['faint']}; }}
#pickerRowTotal {{ font-size: 12px; color: {C['muted']}; }}
#pickerHint {{ color: {C['faint']}; font-size: 12px; padding: 14px 0; }}

/* ---------- 排除应用选择窗口 ---------- */
QListWidget#exclList {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget#exclList::item {{ border-radius: 6px; }}
QListWidget#exclList::item:hover {{ background: #F3F6FD; }}
QListWidget#exclList::item:selected {{ background: {C['primary_soft']}; }}
#exclName {{ font-size: 13px; color: {C['text']}; }}
#exclKey {{ font-size: 11px; color: {C['faint']}; }}
#exclTotal {{ font-size: 12px; color: {C['muted']}; }}
#exclTag {{
    font-size: 11px;
    color: {C['faint']};
    background: #F1F3F8;
    border-radius: 4px;
    padding: 1px 5px;
}}
#exclHint {{ color: {C['faint']}; font-size: 12px; padding: 12px 0; }}

/* ---------- 表格 ---------- */
QTableWidget {{
    background: transparent;
    border: none;
    gridline-color: transparent;
    selection-background-color: {C['primary_soft']};
    selection-color: {C['text']};
}}
QTableWidget::item {{ padding: 0px 8px; border-bottom: 1px solid {C['grid']}; }}
QTableWidget::item:selected {{ background: {C['primary_soft']}; }}
QHeaderView::section {{
    background: {C['card']};
    color: {C['muted']};
    border: none;
    border-bottom: 1px solid {C['border']};
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {C['card']}; border: none; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {C['gray_bar']}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {C['gray_bar']}; border-radius: 4px; min-width: 30px; }}

/* ---------- 其它 ---------- */
QScrollArea {{ background: transparent; border: none; }}
QToolTip {{
    background: #1F2735;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
}}
#statusBar {{ background: {C['card']}; border-top: 1px solid {C['border']}; }}
#divider {{ background: {C['border']}; }}
QDialog {{ background: {C['bg']}; }}
"""
