"""界面模块 —— 设置页。

配置项与 config.json 一一对应；保存后写回磁盘并重启采集引擎。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                               QWidget)

from ...core import autostart, tempclean, winadmin
from ...core.config import (CLOSE_ACTIONS, CLOSE_LABELS, COLLECTOR_MODES, MODE_LABELS,
                            default_data_dir, program_dir)
from ...core.units import format_bytes
from ..context import UiContext
from ..exclude_dialog import ExcludeDialog
from ..theme import C
from ..widgets import Card, CardHeader


class SettingsPage(QWidget):
    saved = Signal()
    dataCleared = Signal()

    def __init__(self, ctx: UiContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._loading = False          # 装载/回写期间屏蔽复选框信号，避免自触发
        self._meta_ts = 0.0            # refresh_meta 节流时间戳
        self._build()
        self.load_values()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        root = QVBoxLayout(holder)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(14)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        # ---- 采集 ----
        card = Card(padding=18, spacing=12)
        card.body().addWidget(CardHeader("采集引擎", "决定流量数据的来源与精度"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)

        self.mode_box = QComboBox()
        for mode in COLLECTOR_MODES:
            self.mode_box.addItem(MODE_LABELS[mode], mode)
        self.mode_box.setMinimumWidth(320)
        form.addRow(self._label("数据来源"), self.mode_box)

        self.collect_spin = QSpinBox()
        self.collect_spin.setRange(10, 600)
        self.collect_spin.setSuffix(" 秒")
        self.collect_spin.setMinimumWidth(120)
        form.addRow(self._label("采集批次周期"), self.collect_spin)

        self.flush_spin = QSpinBox()
        self.flush_spin.setRange(2, 120)
        self.flush_spin.setSuffix(" 秒")
        self.flush_spin.setMinimumWidth(120)
        form.addRow(self._label("写入数据库周期"), self.flush_spin)

        self.reconcile_check = QCheckBox("把无法归属到应用的流量计入「未分类」，使总量与系统一致")
        form.addRow(self._label("未分类校准"), self.reconcile_check)

        self.elevate_check = QCheckBox(
            "启动时自动申请管理员权限（会弹出 UAC 确认框，拒绝后降级为估算模式）")
        form.addRow(self._label("自动提权"), self.elevate_check)

        self.admin_label = QLabel("")
        self.admin_label.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        form.addRow(self._label("当前权限"), self.admin_label)
        card.body().addLayout(form)

        self.mode_hint = QLabel("")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        card.body().addWidget(self.mode_hint)

        restart_row = QHBoxLayout()
        restart_row.addStretch(1)
        self.restart_btn = QPushButton("立即重启采集引擎")
        self.restart_btn.clicked.connect(self._apply_and_restart)
        restart_row.addWidget(self.restart_btn)
        card.body().addLayout(restart_row)
        root.addWidget(card)

        # ---- 统计与存储 ----
        card2 = Card(padding=18, spacing=12)
        card2.body().addWidget(CardHeader("统计与存储", "统计周期上限固定为 31 天；历史数据超期自动清理"))
        form2 = QFormLayout()
        form2.setLabelAlignment(Qt.AlignLeft)
        form2.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form2.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        form2.setHorizontalSpacing(24)
        form2.setVerticalSpacing(12)

        self.default_days_spin = QSpinBox()
        self.default_days_spin.setRange(1, 31)
        self.default_days_spin.setSuffix(" 天")
        self.default_days_spin.setMinimumWidth(120)
        form2.addRow(self._label("默认统计范围"), self.default_days_spin)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(31, 730)
        self.retention_spin.setSuffix(" 天")
        self.retention_spin.setMinimumWidth(120)
        form2.addRow(self._label("历史数据保留"), self.retention_spin)

        ex_row = QWidget()
        exl = QHBoxLayout(ex_row)
        exl.setContentsMargins(0, 0, 0, 0)
        exl.setSpacing(8)
        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText(
            "留空表示统计全部进程；也可点右侧按钮从已记录的应用中勾选")
        self.exclude_edit.setMinimumWidth(320)
        exl.addWidget(self.exclude_edit, 1)
        self.exclude_btn = QPushButton("选择应用…")
        self.exclude_btn.setCursor(Qt.PointingHandCursor)
        self.exclude_btn.clicked.connect(self._pick_excluded)
        exl.addWidget(self.exclude_btn)
        form2.addRow(self._label("排除的应用"), ex_row)

        dir_row = QWidget()
        dl = QHBoxLayout(dir_row)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)
        self.dir_label = QLabel("")
        self.dir_label.setObjectName("muted")
        self.dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dl.addWidget(self.dir_label)
        open_btn = QPushButton("打开数据目录")
        open_btn.clicked.connect(self._open_dir)
        dl.addWidget(open_btn)
        log_btn = QPushButton("打开日志目录")
        log_btn.clicked.connect(self._open_logs)
        dl.addWidget(log_btn)
        dl.addStretch(1)
        form2.addRow(self._label("数据目录"), dir_row)

        self.size_label = QLabel("")
        self.size_label.setObjectName("muted")
        form2.addRow(self._label("数据库大小"), self.size_label)

        self.clean_check = QCheckBox("启动时自动清理采集残留的临时文件")
        form2.addRow(self._label("临时文件"), self.clean_check)
        card2.body().addLayout(form2)

        clean_row = QHBoxLayout()
        clean_row.setSpacing(10)
        self.clean_state = QLabel("")
        self.clean_state.setWordWrap(True)
        self.clean_state.setStyleSheet(f"color:{C['faint']}; font-size:12px;")
        clean_row.addWidget(self.clean_state, 1)
        self.clean_btn = QPushButton("立即清理")
        self.clean_btn.clicked.connect(self._clean_temp)
        clean_row.addWidget(self.clean_btn)
        card2.body().addLayout(clean_row)
        root.addWidget(card2)

        # ---- 窗口与托盘 ----
        card_tray = Card(padding=18, spacing=12)
        card_tray.body().addWidget(CardHeader(
            "窗口与托盘", "关闭窗口时是退出程序，还是收起到托盘继续统计"))
        form_tray = QFormLayout()
        form_tray.setLabelAlignment(Qt.AlignLeft)
        form_tray.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form_tray.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        form_tray.setHorizontalSpacing(24)
        form_tray.setVerticalSpacing(12)

        self.close_box = QComboBox()
        for action in CLOSE_ACTIONS:
            self.close_box.addItem(CLOSE_LABELS[action], action)
        self.close_box.setMinimumWidth(220)
        form_tray.addRow(self._label("关闭窗口时"), self.close_box)

        self.autostart_check = QCheckBox("登录 Windows 后自动在后台开始统计（勾选即生效）")
        form_tray.addRow(self._label("开机自启动"), self.autostart_check)

        self.autostart_state = QLabel("")
        self.autostart_state.setWordWrap(True)
        self.autostart_state.setStyleSheet(f"color:{C['faint']}; font-size:12px;")
        form_tray.addRow("", self.autostart_state)
        card_tray.body().addLayout(form_tray)

        tray_tip = QLabel(
            "选择「留在后台继续统计」后，点关闭只会收起窗口，采集不中断；"
            "双击任务栏右下角的托盘图标可重新打开，右键图标可退出。")
        tray_tip.setWordWrap(True)
        tray_tip.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        card_tray.body().addWidget(tray_tip)
        root.addWidget(card_tray)

        # ---- 统计口径 ----
        card3 = Card(padding=18, spacing=8)
        card3.body().addWidget(CardHeader("统计口径说明", ""))
        for line in (
            "总流量 = 上传流量 + 下载流量，界面与导出报表中所有「总流量」均按此口径计算。",
            "按「应用 / 进程」归类：同一程序的多个进程实例（如浏览器的多个子进程）合并为一条记录。",
            "无法识别归属的流量（进程已退出、系统保留连接、驱动层流量等）统一计入「未分类」。",
            "统计粒度为「自然日」，时间以本机时区为准；跨零点的流量归入对应日期。",
            "单位自动换算：1 KB = 1024 B，依次为 B / KB / MB / GB / TB。",
            "历史数据持久化在本地 SQLite 数据库，程序重启不丢失；超出保留期的数据自动清理。",
        ):
            item = QLabel("·　" + line)
            item.setWordWrap(True)
            item.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
            card3.body().addWidget(item)
        root.addWidget(card3)

        # ---- 危险操作 ----
        card4 = Card(padding=18, spacing=10)
        card4.body().addWidget(CardHeader("数据维护", "删除后不可恢复"))
        row = QHBoxLayout()
        tip = QLabel("清空全部统计数据（包括所有应用的历史流量记录）")
        tip.setObjectName("muted")
        row.addWidget(tip)
        row.addStretch(1)
        clear_btn = QPushButton("清空统计数据")
        clear_btn.setObjectName("danger")
        clear_btn.clicked.connect(self._clear_data)
        row.addWidget(clear_btn)
        card4.body().addLayout(row)
        root.addWidget(card4)
        root.addStretch(1)

        # ---- 保存 ----
        bar = QHBoxLayout()
        bar.addStretch(1)
        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primary")
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(self._save)
        bar.addWidget(save_btn)
        bottom = QWidget()
        bottom.setLayout(bar)
        bottom.setFixedHeight(52)
        outer.addWidget(bottom)

        self.mode_box.currentIndexChanged.connect(self._update_mode_hint)
        self.autostart_check.toggled.connect(self._on_autostart_toggled)

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setMinimumWidth(96)
        label.setStyleSheet(f"color:{C['text']};")
        return label

    # ------------------------------------------------------------------ 数据
    def load_values(self):
        cfg = self.ctx.config
        index = self.mode_box.findData(cfg.collector_mode)
        self.mode_box.setCurrentIndex(index if index >= 0 else 0)
        self.collect_spin.setValue(cfg.collect_interval)
        self.flush_spin.setValue(cfg.flush_interval)
        self.reconcile_check.setChecked(cfg.reconcile_unclassified)
        self.elevate_check.setChecked(cfg.auto_elevate)
        self.admin_label.setText(
            f"{winadmin.describe()}　·　"
            + ("可读取逐连接数据" if winadmin.is_elevated() else "只能按连接数估算"))
        self.default_days_spin.setValue(cfg.default_range_days)
        self.retention_spin.setValue(cfg.retention_days)
        self.exclude_edit.setText(", ".join(cfg.excluded_apps))
        self._sync_exclude_hint()
        self.close_box.setCurrentIndex(max(0, self.close_box.findData(cfg.close_action)))
        self.dir_label.setText(str(cfg.data_dir))
        self.clean_check.setChecked(cfg.auto_clean_temp)
        self._update_mode_hint()
        self._update_size()
        self._refresh_clean_state()
        self._load_autostart()

    def _update_size(self):
        size = self.ctx.db.size_bytes()
        apps = self.ctx.db.app_count()
        self.size_label.setText(f"{format_bytes(size)}　·　已记录 {apps} 个应用")

    def _update_mode_hint(self):
        mode = self.mode_box.currentData()
        hints = {
            "auto": "自动：启动时若没有管理员权限会主动申请（可 UAC 中拒绝），"
                    "拿到权限走 ETW 精确模式，否则降级为估算模式。",
            "etw": "精确模式：订阅 Windows 内核网络事件，逐连接统计；"
                   "没有权限时启动会自动申请，拒绝则降级。",
            "estimate": "估算模式：系统总流量精确，应用间的分配按活动连接数估算，无需管理员权限。",
            "demo": "演示模式：生成合成数据用于体验全部功能，不代表本机真实流量。",
        }
        self.mode_hint.setText(hints.get(mode, ""))

    # ------------------------------------------------------------------ 开机自启动
    def _autostart_args(self) -> list[str]:
        """自启动命令附带的数据目录：非默认目录才写死，便于 exe 整体搬家。"""
        cfg = self.ctx.config
        try:
            is_default = Path(cfg.data_dir).resolve() == default_data_dir().resolve()
        except OSError:
            is_default = False
        return [] if is_default else ["--data-dir", str(cfg.data_dir)]

    def _load_autostart(self):
        if not autostart.can_install():
            self._loading = True
            try:
                self.autostart_check.setChecked(False)
            finally:
                self._loading = False
            self.autostart_check.setEnabled(False)
            self.autostart_state.setText(
                "当前以源码方式运行，未注册启动项；打包成 exe 后可通过这里开关。")
            return
        enabled = autostart.is_enabled()
        self.autostart_check.setEnabled(True)
        # 以注册表为准回填显示；期间屏蔽信号，避免把「外部被删掉」又自动写回去
        self._loading = True
        try:
            self.autostart_check.setChecked(enabled)
        finally:
            self._loading = False
        if enabled:
            cmd = autostart.current_command() or ""
            self.autostart_state.setText(
                "当前：已加入 Windows 启动项，登录后自动在后台开始统计")
            self.autostart_state.setToolTip(f"启动命令：\n{cmd}")
        else:
            self.autostart_state.setText("当前：未加入 Windows 启动项")
            self.autostart_state.setToolTip(
                "勾选后会写入当前用户的启动项（注册表 Run），不需要管理员权限；"
                "也可以在「任务管理器 → 启动应用」里看到并随时禁用。")

    def _write_autostart(self, want: bool) -> str:
        """按意愿写/删启动项，返回错误说明（空字符串表示成功）。"""
        try:
            if want:
                command = autostart.build_command(self._autostart_args())
                if not command:
                    return "无法确定程序路径，未能注册启动项"
                if autostart.current_command() != command:
                    autostart.enable(command)
            elif autostart.is_enabled():
                autostart.disable()
        except autostart.AutostartError as exc:
            return str(exc)
        return ""

    def _on_autostart_toggled(self, checked: bool):
        """勾选/取消即刻写注册表，不必等「保存设置」。"""
        if self._loading or not autostart.can_install():
            return
        error = self._write_autostart(checked)
        if error:
            QMessageBox.warning(self, "开机自启动设置失败", error)
        self._load_autostart()              # 失败时这里会回填成注册表的真实状态

    def _apply_autostart(self) -> bool:
        """保存设置时再对齐一次（数据目录变更后启动命令需要跟着改）。"""
        if not autostart.can_install():
            return True
        error = self._write_autostart(self.autostart_check.isChecked())
        if error:
            QMessageBox.warning(self, "开机自启动设置失败", error)
            self._load_autostart()
            return False
        self._load_autostart()
        return True

    def refresh_meta(self):
        """定时刷新用：只更新只读信息，绝不覆盖用户正在编辑的控件。

        主窗口每 5 秒 tick 一次。这里如果直接 load_values()，勾选了的复选框、
        填到一半的排除列表都会被配置文件/注册表里的旧值冲掉（「勾上又没了」）。
        """
        now = time.monotonic()
        if now - self._meta_ts < 8:
            return
        self._meta_ts = now
        self._update_size()
        self._refresh_clean_state()
        self._load_autostart()

    # ------------------------------------------------------------------ 动作
    def _collect(self) -> bool:
        cfg = self.ctx.config
        cfg.collector_mode = self.mode_box.currentData() or "auto"
        cfg.collect_interval = self.collect_spin.value()
        cfg.flush_interval = self.flush_spin.value()
        cfg.reconcile_unclassified = self.reconcile_check.isChecked()
        cfg.auto_elevate = self.elevate_check.isChecked()
        cfg.default_range_days = self.default_days_spin.value()
        cfg.retention_days = self.retention_spin.value()
        cfg.auto_clean_temp = self.clean_check.isChecked()
        cfg.close_action = self.close_box.currentData() or "ask"
        cfg.excluded_apps = self._parse_excluded(self.exclude_edit.text())
        cfg.normalize()
        try:
            cfg.save()
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", f"无法写入配置文件：{exc}")
            return False
        return self._apply_autostart()

    def _save(self):
        if not self._collect():
            return
        self.saved.emit()
        QMessageBox.information(self, "已保存", "设置已保存并生效。")

    def _apply_and_restart(self):
        if not self._collect():
            return
        self.saved.emit()

    def _open_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.config.data_dir)))

    # ------------------------------------------------------------------ 排除应用
    @staticmethod
    def _parse_excluded(text: str) -> list[str]:
        """把「a.exe, b.exe」或中文逗号分隔的文本解析成小写列表。"""
        raw = (text or "").replace("，", ",").replace(";", ",").replace("；", ",")
        return [x.strip().lower() for x in raw.split(",") if x.strip()]

    def _pick_excluded(self):
        """打开选择窗口，从已记录的应用里勾选要排除的进程。"""
        current = self._parse_excluded(self.exclude_edit.text())
        try:
            candidates = self.ctx.repo.exclude_candidates()
        except Exception as exc:                    # pragma: no cover
            candidates = []
            QMessageBox.warning(
                self, "无法读取应用列表",
                f"从数据库读取应用列表失败：{exc}\n\n仍可在输入框里手动填写进程名。")
        dialog = ExcludeDialog(candidates, current, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.exclude_edit.setText(", ".join(dialog.selected()))
        self._sync_exclude_hint()

    def _sync_exclude_hint(self):
        """输入框只能显示末尾一段，把完整排除列表放进气泡，并把光标移到开头。"""
        keys = self._parse_excluded(self.exclude_edit.text())
        if keys:
            self.exclude_edit.setToolTip(
                f"已排除 {len(keys)} 个进程（按进程名匹配）：\n" + "\n".join(keys))
        else:
            self.exclude_edit.setToolTip("未排除任何进程，统计全部应用")
        self.exclude_edit.setCursorPosition(0)

    def _open_logs(self):
        target = program_dir() / "logs"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            target = program_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ------------------------------------------------------------------ 临时文件
    def _refresh_clean_state(self):
        """显示 %TEMP% 下残留的采集目录数量与体积。"""
        try:
            count, size = tempclean.pending()
        except Exception:                      # pragma: no cover
            count, size = 0, 0
        if count:
            # 提权进程创建的目录在普通权限下读不到内部文件，此时体积会是 0，
            # 直接显示「0 B」会让人以为没占空间，所以换个说法。
            desc = f"共 {format_bytes(size)}" if size else "占用大小需管理员权限才能统计"
            self.clean_state.setText(
                f"当前残留 {count} 个临时目录，{desc}"
                f"　·　位于 %TEMP%\\{tempclean.TEMP_PREFIX}*")
            self.clean_state.setToolTip(f"{tempclean.temp_root()}\\{tempclean.TEMP_PREFIX}*")
            self.clean_btn.setEnabled(True)
        else:
            self.clean_state.setText("当前没有残留的临时目录")
            self.clean_state.setToolTip(tempclean.temp_root().as_posix())
            self.clean_btn.setEnabled(False)

    def _active_temp_dir(self) -> str:
        """采集器正在使用的临时目录（清理时要跳过，否则会删掉正在写的 .etl）。"""
        try:
            collector = getattr(self.ctx.service, "_collector", None)
            work_dir = getattr(collector, "work_dir", None)
            return str(work_dir) if work_dir else ""
        except Exception:                      # pragma: no cover
            return ""

    def _clean_temp(self):
        active = self._active_temp_dir()
        try:
            result = tempclean.clean(0, keep=[active] if active else [])
        except Exception as exc:               # pragma: no cover
            QMessageBox.warning(self, "清理失败", f"无法清理临时目录：{exc}")
            return
        self._refresh_clean_state()
        if result.skipped:
            QMessageBox.warning(
                self, "部分目录未能清理",
                f"{result.summary()}。\n\n"
                "未能删除的多半是管理员权限下创建的目录。可以重新以管理员身份运行程序后再清理，"
                "或在文件资源管理器中手动删除。")
        elif result.kept:
            QMessageBox.information(
                self, "清理完成",
                f"{result.summary()}。\n\n"
                "正在采集的目录不会删除，等采集停止时程序会自动清掉它。")
        else:
            QMessageBox.information(self, "清理完成", result.summary())

    def _clear_data(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("确认清空")
        box.setText("将删除所有应用的历史流量记录，此操作不可恢复。")
        box.setInformativeText("建议先导出报表留存。确定继续吗？")
        yes = box.addButton("清空数据", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        try:
            self.ctx.db.clear_all()
        except Exception as exc:      # pragma: no cover
            QMessageBox.critical(self, "清空失败", str(exc))
            return
        self._update_size()
        self.dataCleared.emit()
