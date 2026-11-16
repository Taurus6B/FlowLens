"""自检：勾选开机自启动后，定时刷新不能把勾选冲掉。

用测试专用的注册表值名（FlowLens__selftest），跑完即删，不会污染真实启动项。
"""
import os
import sys
import tempfile
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 伪装成打包后的 exe，使 autostart.can_install() 为 True
sys.frozen = True
sys.executable = str(ROOT / "FlowLens.exe")

from app.collector.service import CollectorService          # noqa: E402
from app.core import autostart                              # noqa: E402
from app.core.config import AppConfig                       # noqa: E402
from app.stats.aggregator import StatsService               # noqa: E402
from app.stats.exporter import ReportExporter               # noqa: E402
from app.storage.database import Database                   # noqa: E402
from app.storage.repository import TrafficRepository        # noqa: E402
from app.ui.context import UiContext                        # noqa: E402

TEST_VALUE = "FlowLens__selftest"
autostart.VALUE_NAME = TEST_VALUE

from PySide6.QtWidgets import QApplication                  # noqa: E402

ok, fail = [], []


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra else ""))


def raw_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as k:
            return winreg.QueryValueEx(k, TEST_VALUE)[0]
    except FileNotFoundError:
        return None
    except OSError:
        return None


def main():
    tmp = Path(tempfile.mkdtemp(prefix="nutest_"))
    cfg = AppConfig.load(tmp)
    db = Database(cfg.db_path)
    repo = TrafficRepository(db)
    stats = StatsService(repo)
    ctx = UiContext(config=cfg, db=db, repo=repo, stats=stats,
                    exporter=ReportExporter(stats), service=CollectorService(db, cfg),
                    source_label=lambda: "test")

    app = QApplication([])
    from app.ui.pages.settings import SettingsPage
    page = SettingsPage(ctx)

    print("[1] 初始状态")
    check("初始未勾选", not page.autostart_check.isChecked())
    check("初始注册表为空", raw_value() is None, str(raw_value()))

    print("[2] 勾选即写注册表（不需点保存）")
    page.autostart_check.setChecked(True)
    val = raw_value() or ""
    check("勾选后注册表已写入", bool(val), val)
    check("命令带 --tray", "--tray" in val, val)
    check("命令指向 exe", "FlowLens.exe" in val, val)
    check("状态文案已更新", "已加入" in page.autostart_state.text(),
          page.autostart_state.text())

    print("[3] 定时刷新不能冲掉勾选（原来的 bug）")
    for _ in range(5):
        page._meta_ts = 0.0          # 绕过节流，模拟每 5 秒一次的 tick
        page.refresh_meta()
        app.processEvents()
    check("多次 refresh_meta 后仍勾选", page.autostart_check.isChecked())
    check("注册表仍在", bool(raw_value()), str(raw_value()))

    print("[4] 定时刷新不能冲掉正在编辑的其它控件")
    page.exclude_edit.setText("qq.exe, thunder.exe")
    page.collect_spin.setValue(45)
    for _ in range(3):
        page._meta_ts = 0.0
        page.refresh_meta()
    check("排除列表内容保留", page.exclude_edit.text() == "qq.exe, thunder.exe",
          page.exclude_edit.text())
    check("采集周期保留", page.collect_spin.value() == 45, str(page.collect_spin.value()))

    print("[5] 主窗口 tick 路径")
    from app.ui.main_window import MainWindow
    win = MainWindow(ctx)
    win._set_page(4)                 # 设置页
    before = win.settings.autostart_check.isChecked()
    for _ in range(4):
        win.settings._meta_ts = 0.0
        win._tick()
        app.processEvents()
    check("切到设置页时为勾选", before)
    check("tick 4 次后仍勾选", win.settings.autostart_check.isChecked())
    win._quitting = True            # 跳过关闭确认对话框
    win.hide()
    win.deleteLater()
    app.processEvents()

    print("[6] 取消勾选即删除启动项")
    page.autostart_check.setChecked(False)
    check("取消后注册表已清空", raw_value() is None, str(raw_value()))
    check("状态文案已更新", "未加入" in page.autostart_state.text(),
          page.autostart_state.text())

    print("[7] 外部删除后如实显示（不自动写回）")
    page.autostart_check.setChecked(True)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, TEST_VALUE)
    page._meta_ts = 0.0
    page.refresh_meta()
    check("注册表被外部删除后复选框跟随", not page.autostart_check.isChecked())
    check("没有自动重建", raw_value() is None, str(raw_value()))

    print()
    print(f"通过 {len(ok)} 项，失败 {len(fail)} 项")
    for name in fail:
        print("  未通过：" + name)
    return 0 if not fail else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, TEST_VALUE)
        except OSError:
            pass
    raise SystemExit(code)
