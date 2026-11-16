"""重新生成 docs/ 下的界面截图（演示数据，便于一次看清所有功能）。

用法：
    python tools/shots.py            # 生成总览/排行/趋势/详情/设置 五张
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize                                   # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

from app.collector.service import CollectorService                 # noqa: E402
from app.core.config import AppConfig                              # noqa: E402
from app.stats.aggregator import StatsService                      # noqa: E402
from app.stats.exporter import ReportExporter                      # noqa: E402
from app.storage.database import Database                          # noqa: E402
from app.storage.repository import TrafficRepository               # noqa: E402
from app.ui.context import UiContext                              # noqa: E402
from app.ui.main_window import MainWindow, _app_icon               # noqa: E402
from app.ui.theme import STYLESHEET, app_font                      # noqa: E402

DOCS = ROOT / "docs"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="flshots_"))
    cfg = AppConfig.load(tmp)
    cfg.collector_mode = "demo"
    db = Database(cfg.db_path)
    repo = TrafficRepository(db)
    stats = StatsService(repo)
    svc = CollectorService(db, cfg)

    app = QApplication([])
    app.setWindowIcon(_app_icon())
    app.setFont(app_font(10))
    app.setStyleSheet(STYLESHEET)

    ctx = UiContext(config=cfg, db=db, repo=repo, stats=stats,
                    exporter=ReportExporter(stats), service=svc,
                    source_label=lambda: "演示数据（合成）")

    # 让采集器把 31 天合成历史灌进库，状态栏才会显示「演示模式」
    svc.start()
    for _ in range(40):
        app.processEvents()
    svc.flush_now()
    for _ in range(20):
        app.processEvents()

    win = MainWindow(ctx)
    win.resize(1240, 820)
    win.show()
    for _ in range(30):
        app.processEvents()

    def shot(name: str, page: int, app_id: int | None = None):
        win._set_page(page, force=True)
        if app_id is not None:
            win.detail.show_app(app_id, win._range)
        for _ in range(25):
            app.processEvents()
        path = DOCS / f"preview-{name}.png"
        win.grab().save(str(path))
        print("saved", path.name, QSize(win.width(), win.height()).toTuple())

    rows = repo.app_rows(win._range.start, win._range.end, limit=1)
    top_id = getattr(rows[0], "app_id", None) if rows else None

    shot("overview", 0)
    shot("ranking", 1)
    shot("trend", 2)
    if top_id is not None:
        shot("detail", 3, top_id)
    shot("settings", 4)

    svc.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
