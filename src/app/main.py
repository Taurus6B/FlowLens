"""主程序与运行入口（GUI 引导）。

职责：解析启动参数 → 组装配置/存储/采集/统计 → 打开主窗口 → 进入事件循环。
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import logging.handlers
import sqlite3
import sys
import traceback
from pathlib import Path

# 允许以 `python app/main.py` 或 `python run.py` 直接运行
if __package__ in (None, ""):                     # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "app"

from . import __app_name__, __version__          # noqa: E402
from .collector.service import CollectorService  # noqa: E402
from .core import winadmin                        # noqa: E402
from .core.config import AppConfig, default_data_dir, program_dir  # noqa: E402
from .core.instance import bind_activate_handler, claim_single_instance  # noqa: E402
from .stats.aggregator import StatsService       # noqa: E402
from .stats.exporter import ReportExporter       # noqa: E402
from .storage.database import Database           # noqa: E402
from .storage.repository import TrafficRepository  # noqa: E402

SOURCE_LABELS = {
    "etw": "ETW 精确采集（逐连接）",
    "estimate": "系统总量 + 连接分摊（估算）",
    "demo": "演示数据（合成）",
    "none": "未采集",
    "init": "初始化中",
}

PROGRAM_DIR = program_dir()
LOG_DIR = PROGRAM_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"
logger = logging.getLogger("app")


def safe_print(text: str) -> None:
    """无控制台启动（pythonw）时 stdout/stderr 为 None，这里静默跳过。"""
    stream = sys.stderr or sys.stdout
    if stream is None:
        return
    try:
        print(text, file=stream)
    except Exception:
        pass


def setup_logging() -> Path:
    """把启动过程与异常写入 logs/app.log。

    无控制台启动（pythonw / 双击）时，这里是唯一能看到失败原因的通道。
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:                       # 目录只读等极端情况：退化为不落盘
        return LOG_FILE
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logger.info("=" * 56)
    logger.info("启动 %s %s | python %s", __app_name__, __version__, sys.version.replace("\n", " "))
    logger.info("解释器: %s", sys.executable)
    logger.info("程序目录: %s", PROGRAM_DIR)
    return LOG_FILE


def report_fatal(exc: BaseException) -> None:
    """记录致命错误，并尽力弹窗告知（避免静默退出）。"""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error("启动失败:\n%s", detail)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv[:1])
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(f"{__app_name__} 启动失败")
        box.setText(f"程序无法启动：{type(exc).__name__}: {exc}")
        box.setInformativeText(f"详细信息已写入：\n{LOG_FILE}")
        box.setDetailedText(detail[-4000:])
        box.exec()
        del app
    except Exception:                     # Qt 本身不可用时只能落到控制台
        safe_print(f"启动失败：{type(exc).__name__}: {exc}\n详情见 {LOG_FILE}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="FlowLens",
        description=f"{__app_name__} · 本机网络流量按应用统计（最近 30 天，可自定义 31 天内任意区间）",
    )
    parser.add_argument("--data-dir", default="", help="数据目录（默认程序目录下的 data/）")
    parser.add_argument("--demo", action="store_true", help="以演示模式启动（合成数据）")
    parser.add_argument("--mode", default="", choices=["", "auto", "etw", "estimate", "demo"],
                        help="采集模式，留空则沿用配置文件")
    parser.add_argument("--no-elevate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--tray", action="store_true",
                        help="启动后不显示主窗口，直接驻留托盘（开机自启动时使用）")
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    return parser.parse_args(argv)


def needs_elevation(args: argparse.Namespace, cfg: AppConfig) -> bool:
    """判断是否需要提权重启。

    只在「要拿精确数据」时才打扰用户：演示模式、显式选择估算模式、
    已关闭自动提权、或者已经是管理员，都直接跳过。
    """
    if args.no_elevate or not cfg.auto_elevate:
        return False
    if cfg.collector_mode in ("demo", "estimate"):
        return False
    return winadmin.can_elevate()


def try_elevate(argv: list[str] | None) -> bool:
    """提权成功返回 True（调用方应立即退出），失败返回 False（继续当前进程）。"""
    err = winadmin.relaunch_elevated(None if argv is None else list(argv))
    if not err:
        logger.info("已以管理员权限拉起新实例，本进程退出")
        return True
    logger.info("提权未完成：%s（继续以当前权限运行，界面会提示精度差异）", err)
    return False


def _autostart_args(cfg: AppConfig) -> list[str]:
    """开机自启动命令里要带的数据目录。

    默认目录（exe 旁边的 data/）省略，这样 exe 整体搬家后仍指向新位置；
    用户显式指定过数据目录才写死路径。
    """
    try:
        is_default = Path(cfg.data_dir).resolve() == default_data_dir().resolve()
    except OSError:
        is_default = False
    return [] if is_default else ["--data-dir", str(cfg.data_dir)]


def build_context(cfg: AppConfig):
    """组装各层依赖，返回 UiContext。"""
    from .ui.context import UiContext

    try:
        db = Database(cfg.db_path)
    except sqlite3.DatabaseError:
        # 数据库损坏：备份后重建，保证程序还能用
        broken = cfg.db_path.with_name(
            f"traffic.corrupt-{dt.datetime.now():%Y%m%d%H%M%S}.db")
        try:
            cfg.db_path.replace(broken)
        except OSError:
            pass
        db = Database(cfg.db_path)

    repo = TrafficRepository(db)
    stats = StatsService(repo)
    exporter = ReportExporter(stats)
    service = CollectorService(db, cfg)
    return UiContext(
        config=cfg,
        db=db,
        repo=repo,
        stats=stats,
        exporter=exporter,
        service=service,
        source_label=lambda: SOURCE_LABELS.get(service.status.mode, "未知"),
    )


def main(argv: list[str] | None = None) -> int:
    """对外入口：记录日志并兜住所有启动期异常。"""
    setup_logging()
    try:
        return _main(argv)
    except SystemExit:
        raise
    except BaseException as exc:                  # noqa: BLE001 - 必须兜底
        report_fatal(exc)
        return 1
    finally:
        logger.info("进程退出")


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        logger.error("缺少图形界面依赖 PySide6")
        safe_print("缺少图形界面依赖 PySide6，请先执行：\n    python -m pip install PySide6")
        return 2

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else default_data_dir()
    cfg = AppConfig.load(data_dir)
    if args.demo:
        cfg.collector_mode = "demo"
    if args.mode:
        cfg.collector_mode = args.mode
    cfg.normalize()
    try:
        cfg.save()
    except OSError:
        pass
    logger.info("数据目录: %s | 采集模式: %s", data_dir, cfg.collector_mode)

    # 提权要在申请单实例锁之前：此时本进程还没占锁，新实例才能顺利接管。
    if needs_elevation(args, cfg):
        logger.info("当前为普通用户权限，尝试以管理员身份重新启动…")
        if try_elevate(argv):
            return 0
    logger.info("运行权限: %s", winadmin.describe())

    # 开机自启动项：exe 换位置后旧路径会失效，这里顺手校正一次
    try:
        from .core.autostart import drop_legacy as drop_legacy_autostart
        from .core.autostart import sync as sync_autostart

        stale = drop_legacy_autostart()
        if stale:
            logger.info("已清理旧名称的启动项: %s", ", ".join(stale))
        if sync_autostart(_autostart_args(cfg)):
            logger.info("开机自启动路径已校正")
    except Exception:
        logger.info("开机自启动校正失败（不影响本次运行）", exc_info=True)

    # 临时文件：强杀进程会在 %TEMP% 留下 netusage_etw_* 残壳，启动时顺手收拾
    if cfg.auto_clean_temp:
        try:
            from .core.tempclean import clean as clean_temp

            cleaned = clean_temp()
            if cleaned.scanned:
                logger.info("临时文件清理: %s", cleaned.summary())
                if cleaned.skipped:
                    logger.info("未删除的目录（多为提权进程创建，普通权限删不掉）: %s",
                                ", ".join(cleaned.skipped_names[:5]))
        except Exception:
            logger.info("临时文件清理失败（不影响本次运行）", exc_info=True)

    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("FlowLens")

    from .ui.main_window import MainWindow, _app_icon
    from .ui.theme import STYLESHEET, app_font

    app.setWindowIcon(_app_icon())
    app.setFont(app_font(10))
    app.setStyleSheet(STYLESHEET)

    instance_state = claim_single_instance(app, str(cfg.db_path))
    logger.info("单实例检测: %s | %s",
                {True: "本进程独占", False: "已有实例在运行", None: "无法判定，放行"}[instance_state],
                cfg.db_path)
    if instance_state is False:
        # 已经在跑：先试着把它的窗口叫出来（窗口可能被「关闭到托盘」收起了）
        from .core.instance import notify_running_instance

        if notify_running_instance(str(cfg.db_path)):
            logger.info("已唤醒运行中的实例，本次启动退出")
            return 0
        logger.info("窗口唤醒失败，提示用户已在运行")
        QMessageBox.information(
            None, __app_name__,
            "程序已经在运行了。\n\n"
            "窗口可能被收起在任务栏右下角的托盘里：双击托盘图标即可打开"
            "（图标可能藏在 ^ 展开区）。\n"
            "如果找不到图标，可在任务管理器中结束 FlowLens.exe 后重试。")
        return 0

    try:
        ctx = build_context(cfg)
    except Exception as exc:                        # pragma: no cover
        QMessageBox.critical(None, "启动失败", f"初始化数据存储失败：{exc}")
        return 1

    window = MainWindow(ctx)
    # 允许「再次双击 exe」把已经收起到托盘的窗口唤回来
    if bind_activate_handler(app, window.show_from_background):
        logger.info("窗口唤醒通道已就绪")
    else:
        logger.info("窗口唤醒通道不可用（重复启动时只能提示已在运行）")
    screen = QGuiApplication.primaryScreen()
    if args.tray and window.start_in_background():
        logger.info("以托盘模式启动（不显示主窗口）")
    else:
        if screen is not None:
            geo = screen.availableGeometry()
            window.move(geo.center().x() - window.width() // 2,
                        max(geo.top() + 20, geo.center().y() - window.height() // 2))
        window.show()
        logger.info("主窗口已显示 %dx%d | 数据库: %s", window.width(), window.height(),
                    cfg.db_path)
    ctx.service.start()

    exit_code = app.exec()
    try:
        ctx.service.stop()
        cfg.save()
    except Exception:
        pass
    return exit_code


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
