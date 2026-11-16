"""界面模块 —— 主窗口。

结构：
    ┌ 侧边栏 ┬ 顶部（标题 / 周期选择 / 刷新 / 导出）
    │        ├ 提示条（仅在非精确模式时出现）
    │        ├ 页面栈（总览 / 排行 / 趋势 / 详情 / 设置）
    └────────┴ 状态栏（采集状态 / 最近更新 / 统计口径）
"""
from __future__ import annotations

import datetime as dt
import logging
import re

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core import winadmin
from ..core.config import resource_path
from ..core.daterange import DateRange, RangeError
from .context import UiContext
from .dialogs import CloseChoiceDialog, ConfirmDialog, RangeDialog
from .pages.detail import DetailPage
from .pages.overview import OverviewPage
from .pages.ranking import RankingPage
from .pages.settings import SettingsPage
from .pages.trend import TrendPage
from .theme import C
from .widgets import Badge, SegmentedControl

PAGES = [
    ("overview", "总览", "一眼看清这段时间的流量概况"),
    ("ranking", "应用排行", "按应用归类，支持搜索、排序与跳转详情"),
    ("trend", "趋势分析", "逐日流量变化与上一周期对比"),
    ("detail", "应用详情", "单个应用的逐日流量与占比"),
    ("settings", "设置", "采集引擎、统计口径与数据存储"),
]


_ICON_CACHE: QIcon | None = None


def _app_icon() -> QIcon:
    """程序图标：优先用打包进来的 assets/app.ico（窗口、托盘、任务栏共用一张）。

    ico 里已经带了 16/24/32/48/64/128/256 各尺寸，托盘会自动取合适的那档。
    """
    global _ICON_CACHE
    if _ICON_CACHE is None:
        path = resource_path("assets", "app.ico")
        if path.exists():
            _ICON_CACHE = QIcon(str(path))
            logging.getLogger("app").info(
                "界面图标: %s（%d 档尺寸）", path, len(_ICON_CACHE.availableSizes()))
        else:                                  # 兜底：资源缺失时手绘一枚
            _ICON_CACHE = QIcon(_drawn_icon())
            logging.getLogger("app").warning("图标资源缺失（%s），已用内置绘制图标", path)
    return _ICON_CACHE


def _drawn_icon() -> QPixmap:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["primary"]))
    p.drawRoundedRect(2, 2, 60, 60, 16, 16)
    p.setPen(QColor("#FFFFFF"))
    f = p.font()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, "N")
    p.end()
    return pix


class MainWindow(QMainWindow):
    def __init__(self, ctx: UiContext):
        super().__init__()
        self.ctx = ctx
        cfg = ctx.config
        self._range = self._initial_range()
        self._quitting = False
        self._shutdown_done = False
        self._tray_available = False
        self.setWindowTitle("FlowLens · 流量镜 · 本机网络流量统计")
        self.setWindowIcon(_app_icon())
        self.resize(cfg.window_width, cfg.window_height)
        self.setMinimumSize(1040, 680)
        self._build()
        self._build_tray()
        self._set_page(0, force=True)

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._refresh_all()
        QTimer.singleShot(900, self._tick)
        QTimer.singleShot(1800, self._tick)

    # ------------------------------------------------------------------ 初始周期
    def _initial_range(self) -> DateRange:
        cfg = self.ctx.config
        rng = DateRange.last_days(cfg.default_range_days)
        if cfg.restore_last_range and cfg.last_start and cfg.last_end:
            try:
                s = dt.datetime.strptime(cfg.last_start, "%Y-%m-%d").date()
                e = dt.datetime.strptime(cfg.last_end, "%Y-%m-%d").date()
                candidate = DateRange(s, e).clamp(max_days=cfg.max_range_days)
                if candidate.length >= 1:
                    rng = candidate
            except ValueError:
                pass
        return rng.clamp(max_days=cfg.max_range_days)

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_sidebar())

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_notice())
        self.stack = QStackedWidget()
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(22, 14, 22, 12)
        hl.addWidget(self.stack)
        lay.addWidget(holder, 1)
        lay.addWidget(self._build_statusbar())
        outer.addWidget(content, 1)

        self.overview = OverviewPage(self.ctx)
        self.ranking = RankingPage(self.ctx)
        self.trend = TrendPage(self.ctx)
        self.detail = DetailPage(self.ctx)
        self.settings = SettingsPage(self.ctx)
        for page in (self.overview, self.ranking, self.trend, self.detail, self.settings):
            self.stack.addWidget(page)

        self.overview.appSelected.connect(self._goto_detail)
        self.ranking.appSelected.connect(self._goto_detail)
        self.detail.exportRequested.connect(lambda app_id: self._export(app_id))
        self.settings.saved.connect(self._on_settings_saved)
        self.settings.dataCleared.connect(self._refresh_all)

    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(214)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(_app_icon().pixmap(QSize(32, 32)))
        brand.addWidget(logo)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("FlowLens")
        title.setObjectName("brand")
        sub = QLabel("本机流量统计")
        sub.setObjectName("brandSub")
        texts.addWidget(title)
        texts.addWidget(sub)
        brand.addLayout(texts)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(16)

        group = QLabel("统计视图")
        group.setObjectName("navGroup")
        lay.addWidget(group)

        self._nav_buttons: list[QPushButton] = []
        for index, (key, label, _sub) in enumerate(PAGES):
            btn = QPushButton("   " + label)
            btn.setObjectName("navBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(False)
            btn.setMinimumHeight(38)
            btn.clicked.connect(lambda _=False, i=index: self._set_page(i))
            lay.addWidget(btn)
            self._nav_buttons.append(btn)

        lay.addStretch(1)

        # 底部采集状态卡
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.side_dot = QLabel()
        self.side_dot.setFixedSize(8, 8)
        self.side_dot.setStyleSheet(
            f"background:{C['ok']}; border-radius:4px;")
        head.addWidget(self.side_dot)
        self.side_state = QLabel("初始化中")
        self.side_state.setStyleSheet(f"font-size:12px; font-weight:600; color:{C['text']};")
        head.addWidget(self.side_state)
        head.addStretch(1)
        cl.addLayout(head)
        self.side_time = QLabel("等待数据…")
        self.side_time.setStyleSheet(f"font-size:11px; color:{C['faint']};")
        self.side_time.setWordWrap(True)
        cl.addWidget(self.side_time)
        lay.addWidget(card)
        lay.addSpacing(6)

        about = QLabel("v1.0 · 本地运行 · 数据不上传")
        about.setStyleSheet(f"font-size:10px; color:{C['faint']};")
        about.setAlignment(Qt.AlignCenter)
        lay.addWidget(about)
        return bar

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(74)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(22, 16, 22, 8)
        lay.setSpacing(10)

        box = QVBoxLayout()
        box.setSpacing(2)
        self.page_title = QLabel("总览")
        self.page_title.setObjectName("h1")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("muted")
        self.page_subtitle.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        box.addWidget(self.page_title)
        box.addWidget(self.page_subtitle)
        lay.addLayout(box)
        lay.addStretch(1)

        self.seg = SegmentedControl([("1", "今日"), ("7", "近 7 天"),
                                     ("30", "近 30 天"), ("custom", "自定义")])
        self.seg.changed.connect(self._on_preset)
        self.seg_wrap = self.seg
        lay.addWidget(self.seg_wrap)

        self.range_label = QLabel("")
        self.range_label.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        self.range_label.setMinimumWidth(120)
        self.range_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.range_label)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._manual_refresh)
        lay.addWidget(self.refresh_btn)

        self.export_btn = QPushButton("导出报表")
        self.export_btn.setObjectName("primary")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(lambda: self._export(None))
        lay.addWidget(self.export_btn)
        return header

    def _build_notice(self) -> QWidget:
        self.notice = QFrame()
        self.notice.setVisible(False)
        lay = QHBoxLayout(self.notice)
        lay.setContentsMargins(22, 2, 22, 6)
        lay.setSpacing(10)
        inner = QFrame()
        inner.setStyleSheet(
            f"background:#FFF8EA; border:1px solid #F6E3BE; border-radius:8px;")
        il = QHBoxLayout(inner)
        il.setContentsMargins(12, 7, 12, 7)
        il.setSpacing(8)
        self.notice_text = QLabel("")
        self.notice_text.setWordWrap(True)
        self.notice_text.setStyleSheet("color:#8A6118; font-size:12px; border:none;")
        il.addWidget(self.notice_text, 1)
        self.notice_action = QPushButton("以管理员身份重启")
        self.notice_action.setCursor(Qt.PointingHandCursor)
        self.notice_action.setVisible(False)
        self.notice_action.setStyleSheet(
            "border:1px solid #E4C88A; border-radius:6px; background:#FFFDF7;"
            "color:#8A6118; font-weight:600; font-size:12px; padding:3px 9px;")
        self.notice_action.clicked.connect(self._restart_as_admin)
        il.addWidget(self.notice_action)
        self.notice_btn = QPushButton("去设置")
        self.notice_btn.setCursor(Qt.PointingHandCursor)
        self.notice_btn.setStyleSheet(
            "border:none; background:transparent; color:#8A6118; font-weight:600;"
            "font-size:12px; padding:2px 6px;")
        self.notice_btn.clicked.connect(lambda: self._set_page(4))
        il.addWidget(self.notice_btn)
        lay.addWidget(inner)
        return self.notice

    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(36)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(22, 0, 22, 0)
        lay.setSpacing(12)
        self.status_badge = Badge("初始化", "muted")
        lay.addWidget(self.status_badge)
        self.status_msg = QLabel("")
        self.status_msg.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        lay.addWidget(self.status_msg)
        lay.addStretch(1)
        self.status_updated = QLabel("")
        self.status_updated.setStyleSheet(f"color:{C['faint']}; font-size:12px;")
        lay.addWidget(self.status_updated)
        caliber = QLabel("统计口径：总流量 = 上传 + 下载　|　单位 1024 进制自动换算")
        caliber.setStyleSheet(f"color:{C['faint']}; font-size:12px;")
        lay.addWidget(caliber)
        return bar

    # ------------------------------------------------------------------ 页面切换
    def _set_page(self, index: int, force: bool = False):
        if index < 0 or index >= len(PAGES):
            return
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        key, title, subtitle = PAGES[index]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        is_settings = key == "settings"
        for widget in (self.seg_wrap, self.range_label, self.export_btn):
            widget.setVisible(not is_settings)
        self.refresh_btn.setVisible(True)
        self._refresh_page(index, force=force, full=True)

    def _goto_detail(self, app_id: int):
        self._set_page(3)
        self.detail.show_app(app_id, self._range)

    # ------------------------------------------------------------------ 周期
    def _on_preset(self, key: str):
        if key == "custom":
            dialog = RangeDialog(self._range, self.ctx.config.max_range_days, self)
            if dialog.exec():
                self._apply_range(dialog.value())
            else:
                self._sync_seg()
            return
        days = int(key) if key.isdigit() else self.ctx.config.default_range_days
        self._apply_range(DateRange.last_days(days))

    def _apply_range(self, rng: DateRange):
        cfg = self.ctx.config
        try:
            rng.validate(max_days=cfg.max_range_days)
        except RangeError as exc:
            QMessageBox.warning(self, "统计周期不合法", str(exc))
            self._sync_seg()
            return
        self._range = rng
        self._sync_seg()
        self._refresh_all()

    def _sync_seg(self):
        rng = self._range
        key = "custom"
        for days in (1, 7, 30):
            if rng.end == dt.date.today() and rng.length == days:
                key = str(days)
                break
        self.seg.select(key, emit=False)
        self.seg.set_text("custom", "自定义")
        self.range_label.setText(f"{rng.start:%Y-%m-%d} ~ {rng.end:%Y-%m-%d}（{rng.length} 天）")

    # ------------------------------------------------------------------ 刷新
    def _refresh_page(self, index: int, force: bool = False, full: bool = False):
        page = self.stack.widget(index)
        if page is None:
            return
        try:
            if isinstance(page, SettingsPage):
                # 只有用户主动切到设置页才重新装载整张表单；
                # 定时 tick / 切时间范围只刷新只读信息，否则会冲掉正在编辑
                # 的控件（表现就是「勾了开机自启动，过几秒又没了」）。
                if full:
                    page.load_values()
                else:
                    page.refresh_meta()
                return
            page.refresh(self._range)
        except Exception as exc:            # 界面永不因数据异常崩溃
            self.status_msg.setText(f"读取数据失败：{exc}")

    def _refresh_all(self):
        self._sync_seg()
        for i in range(self.stack.count()):
            if i == self.stack.currentIndex():
                self._refresh_page(i)
        self._update_status()

    def _tick(self):
        self._update_status()
        self._refresh_page(self.stack.currentIndex())

    def _manual_refresh(self):
        self.ctx.service.flush_now()
        self._refresh_page(self.stack.currentIndex())
        self._update_status()

    def _update_status(self):
        st = self.ctx.service.status
        tone = "ok" if st.mode == "etw" else ("warn" if st.mode in ("estimate", "demo") else "danger")
        if st.mode == "init":
            tone = "muted"
        self.status_badge.set_state(_short_label(st.mode, st.label), tone)
        msg = st.message or ""
        if len(msg) > 90:
            msg = msg[:88] + "…"
        self.status_msg.setText(msg)
        self.status_msg.setToolTip(st.message or "")
        if st.last_flush:
            self.status_updated.setText(f"最近写入 {st.last_flush:%H:%M:%S}")
        else:
            self.status_updated.setText("尚未写入数据")

        dot_color = {"ok": C["ok"], "warn": C["warn"], "danger": C["danger"],
                     "muted": C["faint"]}[tone]
        self.side_dot.setStyleSheet(f"background:{dot_color}; border-radius:4px;")
        self.side_state.setText(_short_label(st.mode, st.label))
        if st.last_flush:
            self.side_time.setText(f"{st.last_flush:%H:%M:%S} 更新\n"
                                   f"累计 {st.events:,} 条采集事件")
        else:
            self.side_time.setText("等待首批数据…")

        # 提示条
        self.notice_action.setVisible(False)
        if st.mode == "demo":
            self.notice.setVisible(True)
            self.notice_btn.setVisible(True)
            self.notice_text.setText(
                "演示模式：当前展示的是合成数据，不代表本机真实流量。可在设置中切换为真实采集。")
        elif st.mode == "estimate":
            self.notice.setVisible(True)
            self.notice_btn.setVisible(True)
            can_elevate = winadmin.can_elevate()
            self.notice_action.setVisible(can_elevate)
            if can_elevate:
                self.notice_text.setText(
                    "当前是估算模式：系统总流量准确，但各应用间的分配按活动连接数推算。"
                    "点右侧按钮可提权重启，拿到逐连接的精确数据。")
            else:
                self.notice_text.setText(
                    "估算模式：系统总流量准确，应用间的分配按活动连接数估算（已具备管理员权限，"
                    "精确模式不可用的原因见状态栏）。")
        elif st.mode == "none":
            self.notice.setVisible(True)
            self.notice_btn.setVisible(True)
            self.notice_text.setText(f"采集不可用：{st.message}")
        else:
            self.notice.setVisible(False)

    def _on_settings_saved(self):
        try:
            self.ctx.service.stop()
            self.ctx.service.start()
        except Exception:
            pass
        self._refresh_all()

    def _restart_as_admin(self):
        """以管理员身份重启自身（提示条右侧按钮）。

        顺序很关键：先停采集、存配置、**放掉单实例锁**，再拉起提权实例，
        否则新进程启动时会检测到「已有实例在运行」而退出。
        """
        from ..core.instance import (bind_activate_handler, claim_single_instance,
                                     release_single_instance)

        app = QApplication.instance()
        try:
            self.ctx.service.stop()
            # 手动选了「估算模式」的话，提权后要切回自动，否则新实例仍是估算
            if self.ctx.config.collector_mode == "estimate":
                self.ctx.config.collector_mode = "auto"
            self.ctx.config.save()
        except Exception:
            pass
        release_single_instance(app)

        err = winadmin.relaunch_elevated()
        if not err:
            app.quit()
            return

        # 提权没成功（多数是用户在 UAC 里点了「否」）：把锁拿回来继续跑
        claim_single_instance(app, str(self.ctx.config.db_path))
        bind_activate_handler(app, self.show_from_background)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("未能提权")
        box.setText(err)
        box.setInformativeText(
            "程序会继续以当前权限运行，统计为估算模式（系统总量准确，应用间分配为推算）。\n"
            "需要精确数据时，可右键 FlowLens.exe →「以管理员身份运行」。")
        box.exec()

    # ------------------------------------------------------------------ 导出
    def _export(self, app_id: int | None):
        rng = self._range
        cfg = self.ctx.config
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        name = f"流量报表_{rng.start:%Y%m%d}-{rng.end:%Y%m%d}"
        if app_id:
            app_name = self.ctx.repo.app_label(app_id)[1]
            safe = re.sub(r'[\\/:*?"<>|]', "_", app_name).strip() or "应用"
            name += f"_{safe}"
        default = cfg.export_dir / f"{name}.xlsx"
        path, selected = QFileDialog.getSaveFileName(
            self, "导出报表", str(default),
            "Excel 工作簿 (*.xlsx);;CSV 表格 (*.csv);;HTML 网页报表 (*.html)")
        if not path:
            return
        if "*.csv" in selected:
            fmt = "csv"
        elif "*.html" in selected:
            fmt = "html"
        else:
            fmt = "xlsx"
        if not path.lower().endswith((".csv", ".html", ".htm", ".xlsx")):
            path += "." + fmt
        try:
            out = self.ctx.exporter.export(
                path, rng, fmt=fmt, app_id=app_id,
                source_label=self.ctx.source_label(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"无法生成报表：{exc}")
            return
        dialog = ConfirmDialog(
            "导出完成",
            f"报表已保存：\n{out}\n\n包含总览、应用排行与每日趋势"
            + ("、该应用逐日明细" if app_id else "") + "。",
            ["打开文件", "打开所在文件夹", "完成"], self)
        dialog.exec()
        choice = dialog.choice()
        if choice == "打开文件":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        elif choice == "打开所在文件夹":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out.parent)))

    # ------------------------------------------------------------------ 托盘与关闭
    def _build_tray(self):
        """常驻托盘图标：窗口收起后靠它回到前台、刷新或退出。"""
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray = QSystemTrayIcon(_app_icon(), self)
        self.tray.setToolTip("FlowLens · 流量镜 · 后台统计中")
        menu = QMenu()
        menu.addAction("打开主界面", self.show_from_background)
        menu.addAction("立即刷新数据", self._manual_refresh)
        menu.addSeparator()
        menu.addAction("退出并停止统计", self._quit_from_tray)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(self._tray_available)

    def _on_tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_from_background()

    def show_from_background(self):
        """从托盘/后台恢复到前台（也供「再次双击 exe」时被唤醒调用）。"""
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_in_background(self) -> bool:
        """开机自启动：不显示主窗口，只在托盘常驻并提示一次。

        托盘不可用时返回 False，调用方应改为正常显示窗口——
        否则用户会看到一个「进程在跑但没有任何界面」的程序。
        """
        from PySide6.QtWidgets import QSystemTrayIcon

        if not self._tray_available:
            return False
        self._timer.stop()
        self.tray.showMessage(
            "FlowLens 已启动",
            "正在后台统计本机流量，双击托盘图标可查看详情。",
            QSystemTrayIcon.Information, 5000)
        return True

    def _hide_to_tray(self):
        from PySide6.QtWidgets import QSystemTrayIcon

        self.hide()
        self._timer.stop()                # 窗口不可见时不做界面刷新，采集线程照常
        if self._tray_available:
            self.tray.setVisible(True)    # 托盘此前若被系统重载，这里补一次
            self.tray.showMessage(
                "仍在后台统计",
                "窗口已收起，流量采集继续进行。双击托盘图标可重新打开。",
                QSystemTrayIcon.Information, 4000)

    def _quit_from_tray(self):
        self._quitting = True
        self._shutdown()
        self.tray.setVisible(False)
        QApplication.quit()

    def _confirm_close(self) -> str | None:
        """返回 "quit" / "tray" / None（取消）。"""
        cfg = self.ctx.config
        want = cfg.close_action if cfg.close_action in ("ask", "quit", "tray") else "ask"
        if want == "tray" and not self._tray_available:
            want = "quit"                 # 没有托盘就别把窗口藏了让用户找不到
        if want != "ask":
            return want

        dialog = CloseChoiceDialog(self)
        dialog.exec()
        if dialog.action is None:
            return None
        if dialog.remember:
            cfg.close_action = dialog.action
            try:
                cfg.save()
            except OSError:
                pass
        return dialog.action

    def _shutdown(self):
        """真正退出前的收尾（幂等）：存窗口状态 → 停采集 → 关数据库。"""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        cfg = self.ctx.config
        cfg.window_width = max(1040, self.width())
        cfg.window_height = max(680, self.height())
        if cfg.restore_last_range:
            cfg.last_start = f"{self._range.start:%Y-%m-%d}"
            cfg.last_end = f"{self._range.end:%Y-%m-%d}"
        try:
            cfg.save()
        except OSError:
            pass
        try:
            self.ctx.service.stop()
        except Exception:
            pass
        try:
            self.ctx.db.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ 关闭
    def closeEvent(self, event):  # noqa: N802
        if self._quitting:
            self._shutdown()
            super().closeEvent(event)
            return

        action = self._confirm_close()
        if action is None:
            event.ignore()
            return
        if action == "tray":
            self._hide_to_tray()
            event.ignore()
            return

        self._quitting = True
        self._shutdown()
        super().closeEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        timer = getattr(self, "_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()
            QTimer.singleShot(80, self._tick)


def _short_label(mode: str, label: str) -> str:
    return {
        "etw": "精确模式",
        "estimate": "估算模式",
        "demo": "演示模式",
        "none": "采集不可用",
        "init": "初始化",
    }.get(mode, label or "未知")
