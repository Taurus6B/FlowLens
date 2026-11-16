"""界面模块 —— 自绘图表（无第三方图表依赖）。

DayChart 支持两种形态：
  * stacked —— 每日上传/下载堆叠柱状图（总览、趋势页）
  * line    —— 双折线（应用详情页）
两者都带坐标轴、网格、悬停提示与空数据占位。
"""
from __future__ import annotations

import datetime as dt
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..core.models import DayPoint
from ..core.units import format_bytes, format_bytes_compact
from .theme import C, qcolor


def nice_max(value: float) -> float:
    if value <= 0:
        return 1024.0
    exp = math.floor(math.log10(value))
    base = 10.0 ** exp
    for mult in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= base * mult:
            return base * mult
    return base * 10


class DayChart(QWidget):
    pointClicked = Signal(int)     # 点击某一天（返回日期索引）

    def __init__(self, parent=None, *, mode: str = "stacked", height: int = 230):
        super().__init__(parent)
        self._points: list[DayPoint] = []
        self._mode = mode
        self._hover = -1
        self._margin = (58, 16, 16, 30)   # left, top, right, bottom
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------------ 数据
    def set_points(self, points: list[DayPoint]):
        self._points = points or []
        self._hover = -1
        self.update()

    def has_data(self) -> bool:
        return any(p.total > 0 for p in self._points)

    # ------------------------------------------------------------------ 布局
    def _plot_rect(self) -> QRectF:
        left, top, right, bottom = self._margin
        return QRectF(left, top, max(1.0, self.width() - left - right),
                      max(1.0, self.height() - top - bottom))

    def _slot(self) -> float:
        return self._plot_rect().width() / max(1, len(self._points))

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        plot = self._plot_rect()

        if not self._points:
            self._draw_placeholder(p, plot, "暂无统计数据")
            return
        data_max = max((p_.total for p_ in self._points), default=0)
        if data_max <= 0:
            self._draw_placeholder(p, plot, "所选周期内没有网络活动")
            self._draw_x_labels(p, plot)
            return

        top_value = nice_max(data_max * 1.08)
        # 网格 + Y 轴刻度
        grid_pen = QPen(QColor(C["grid"]))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for i in range(5):
            y = plot.bottom() - plot.height() * i / 4.0
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        p.setPen(QColor(C["faint"]))
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        for i in range(5):
            y = plot.bottom() - plot.height() * i / 4.0
            p.drawText(QRectF(0, y - 8, self._margin[0] - 9, 16),
                       Qt.AlignRight | Qt.AlignVCenter,
                       format_bytes_compact(top_value * i / 4.0))

        if self._hover >= 0:
            self._draw_hover_bg(p, plot)

        if self._mode == "line":
            self._draw_lines(p, plot, top_value)
        else:
            self._draw_bars(p, plot, top_value)

        self._draw_x_labels(p, plot)
        self._draw_legend(p)

    # ---- 柱状 ----
    def _draw_bars(self, p: QPainter, plot: QRectF, top_value: float):
        slot = self._slot()
        bar_w = max(3.0, min(30.0, slot * 0.62))
        for i, point in enumerate(self._points):
            if point.total <= 0:
                continue
            cx = plot.left() + slot * (i + 0.5)
            h_total = plot.height() * (point.total / top_value)
            h_down = h_total * (point.download / point.total) if point.total else 0
            rect = QRectF(cx - bar_w / 2, plot.bottom() - h_total, bar_w, max(1.0, h_total))
            path = QPainterPath()
            path.addRoundedRect(rect, min(3.0, bar_w / 2), min(3.0, bar_w / 2))
            p.save()
            p.setClipPath(path)
            p.setPen(Qt.NoPen)
            # 下载（底部）
            p.setBrush(QBrush(qcolor("down")))
            p.drawRect(QRectF(rect.left(), rect.bottom() - h_down, rect.width(), h_down))
            # 上传（顶部）
            p.setBrush(QBrush(qcolor("up")))
            p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() - h_down))
            p.restore()

    # ---- 折线 ----
    def _draw_lines(self, p: QPainter, plot: QRectF, top_value: float):
        slot = self._slot()
        n = len(self._points)
        for series, color, fill in (("download", C["down"], True), ("upload", C["up"], False)):
            pts = []
            for i, point in enumerate(self._points):
                v = getattr(point, series)
                x = plot.left() + slot * (i + 0.5)
                y = plot.bottom() - plot.height() * (v / top_value)
                pts.append(QPointF(x, y))
            if not pts:
                continue
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            if fill and n > 1:
                area = QPainterPath(path)
                area.lineTo(pts[-1].x(), plot.bottom())
                area.lineTo(pts[0].x(), plot.bottom())
                area.closeSubpath()
                grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
                grad.setColorAt(0.0, qcolor(color, 46))
                grad.setColorAt(1.0, qcolor(color, 6))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(grad))
                p.drawPath(area)
            pen = QPen(QColor(color))
            pen.setWidth(2)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            # 数据点
            p.setBrush(QBrush(QColor("#FFFFFF")))
            for i, pt in enumerate(pts):
                if self._points[i].total <= 0:
                    continue
                r = 3.4 if i == self._hover else 2.6
                p.setPen(QPen(QColor(color), 1.8))
                p.drawEllipse(pt, r, r)

    # ---- 辅助绘制 ----
    def _draw_x_labels(self, p: QPainter, plot: QRectF):
        n = len(self._points)
        if not n:
            return
        step = max(1, math.ceil(n / 10))
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QColor(C["faint"]))
        slot = plot.width() / n
        for i, point in enumerate(self._points):
            if i % step and i != n - 1:
                continue
            label = f"{point.day.month:02d}-{point.day.day:02d}"
            p.drawText(QRectF(plot.left() + slot * i, plot.bottom() + 6, slot, 16),
                       Qt.AlignHCenter | Qt.AlignVCenter, label)

    def _draw_hover_bg(self, p: QPainter, plot: QRectF):
        slot = self._slot()
        x = plot.left() + slot * self._hover
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(59, 107, 245, 12))
        p.drawRoundedRect(QRectF(x, plot.top(), slot, plot.height()), 4, 4)

    def _draw_legend(self, p: QPainter):
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        items = [("下载", C["down"]), ("上传", C["up"])]
        x = self._margin[0] + 2
        y = 2
        for text, color in items:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, y + 4, 8, 8), 2, 2)
            p.setPen(QColor(C["muted"]))
            p.drawText(QRectF(x + 12, y - 1, 42, 18), Qt.AlignLeft | Qt.AlignVCenter, text)
            x += 54

    def _draw_placeholder(self, p: QPainter, plot: QRectF, text: str):
        p.setPen(QColor(C["faint"]))
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(plot, Qt.AlignCenter, text)

    # ------------------------------------------------------------------ 交互
    def mouseMoveEvent(self, event):  # noqa: N802
        if not self._points:
            return
        plot = self._plot_rect()
        slot = self._slot()
        idx = int((event.position().x() - plot.left()) // slot)
        idx = max(0, min(len(self._points) - 1, idx))
        if idx != self._hover:
            self._hover = idx
            self.update()
        point = self._points[idx]
        tip = (f"<b>{point.day.strftime('%Y-%m-%d')}</b><br>"
               f"下载　{format_bytes(point.download)}<br>"
               f"上传　{format_bytes(point.upload)}<br>"
               f"<b>总计　{format_bytes(point.total)}</b>")
        QToolTip.showText(event.globalPosition().toPoint(), tip, self)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if self._points and event.button() == Qt.LeftButton:
            plot = self._plot_rect()
            slot = self._slot()
            idx = int((event.position().x() - plot.left()) // slot)
            if 0 <= idx < len(self._points):
                self.pointClicked.emit(idx)


class Sparkline(QWidget):
    """迷你走势线（KPI 卡片内使用）。"""

    def __init__(self, parent=None, color: str = "primary", height: int = 34):
        super().__init__(parent)
        self._values: list[float] = []
        self._color = color
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, values: list[float]):
        self._values = values or []
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if len(self._values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        vmax = max(self._values) or 1
        w = self.width() - 2
        h = self.height() - 4
        step = w / (len(self._values) - 1)
        path = QPainterPath()
        for i, v in enumerate(self._values):
            pt = QPointF(1 + i * step, 2 + h - h * (v / vmax))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        pen = QPen(QColor(C[self._color]))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
