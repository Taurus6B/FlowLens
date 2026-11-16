"""打包成 Windows 可执行文件（单文件 exe）。

用法：
    python build_exe.py              # 打包（默认单文件、无控制台）
    python build_exe.py --onedir     # 目录模式，启动更快（exe 在同名文件夹内）

产物：
    ../FlowLens.exe                 （单文件，放在源码目录的上一层，即程序主目录）
    ../FlowLens/…                   （--onedir 时的目录版）

目录约定：
    FlowLens/            ← 程序主目录：FlowLens.exe、data/、logs/
    └── src/             ← 源码目录：本脚本所在位置

说明：
    - 单文件模式下每次启动都要把运行时解压到临时目录，首次启动会慢几秒；
      目录模式不复制、直接加载，启动快但需要连同整个文件夹一起分发。
    - 打包用 pythonw 语义（--windowed），没有黑窗口；出错信息写入 exe 同目录的 logs/app.log。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent      # 源码目录（FlowLens/src）
ROOT = SRC.parent                          # 程序主目录（exe 与 data/logs 所在）
NAME = "FlowLens"
ICON = SRC / "assets" / "app.ico"
ENTRY = SRC / "run.py"
# 先打包到临时目录，再取其中 exe，避免 PyInstaller 在 --onedir 时
# 清理 distpath/NAME 而误删主目录里的同名文件夹。中间产物都留在 src/ 里，
# 这样打包过程不会在主目录里堆 build/ dist/ 之类的文件夹。
STAGING = SRC / ".build_dist"
WORK = SRC / "build"


def version_tuple() -> tuple[int, int, int, int]:
    sys.path.insert(0, str(SRC))
    from app import __version__
    parts = [int(p) for p in __version__.split(".") if p.isdigit()]
    parts += [0] * (4 - len(parts))
    return tuple(parts[:4])  # type: ignore[return-value]


def write_version_file(path: Path) -> Path:
    """生成 exe 的版本信息，右键属性里能看到名称/版本/说明。"""
    v = version_tuple()
    sys.path.insert(0, str(SRC))
    from app import __app_name__
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v}, prodvers={v},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [StringStruct('CompanyName', 'FlowLens'),
         StringStruct('FileDescription', '{__app_name__} · 流量镜 · 本机网络流量按应用统计'),
         StringStruct('FileVersion', '{'.'.join(map(str, v))}'),
         StringStruct('InternalName', '{NAME}'),
         StringStruct('LegalCopyright', ''),
         StringStruct('OriginalFilename', '{NAME}.exe'),
         StringStruct('ProductName', '{NAME}'),
         StringStruct('ProductVersion', '{'.'.join(map(str, v))}'),
         StringStruct('Comments', '统计口径：总流量 = 上传 + 下载')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        print("未安装 PyInstaller，正在安装...")
        mirrors = [
            "https://mirrors.aliyun.com/pypi/simple/",
            "https://pypi.tuna.tsinghua.edu.cn/simple",
            None,
        ]
        for m in mirrors:
            cmd = [sys.executable, "-m", "pip", "install", "pyinstaller"]
            if m:
                cmd += ["-i", m]
            if subprocess.call(cmd) == 0:
                return True
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="打包 FlowLens 为 exe")
    ap.add_argument("--onedir", action="store_true",
                    help="目录模式（启动更快，需分发整个文件夹）")
    ap.add_argument("--debug", action="store_true", help="保留控制台窗口，便于看报错")
    ap.add_argument("--keep", action="store_true", help="保留 build/ 中间文件")
    args = ap.parse_args()

    if os.name != "nt":
        print("提示：当前不是 Windows，产物将不是 .exe")

    if not ensure_pyinstaller():
        print("PyInstaller 安装失败，请手动执行：\n    pip install pyinstaller")
        return 2

    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(STAGING, ignore_errors=True)

    vfile = write_version_file(WORK / "version_info.txt")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir" if args.onedir else "--onefile",
        "--console" if args.debug else "--windowed",
        "--name", NAME,
        "--icon", str(ICON),
        # 界面里的窗口/托盘图标直接用这一份 ico（多尺寸），
        # 打包进 _MEIPASS/assets/，运行时由 resource_path 读取。
        "--add-data", f"{ICON}{os.pathsep}assets",
        "--version-file", str(vfile),
        "--distpath", str(STAGING),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        # 用不到的大模块，剔掉可以显著减小体积
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQuickWidgets",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "PySide6.QtDataVisualization",
        str(ENTRY),
    ]
    print("执行:", " ".join(cmd[:2]), "...", " ".join(cmd[-1:]))
    rc = subprocess.call(cmd, cwd=str(SRC))
    if rc != 0:
        print(f"\n打包失败，退出码 {rc}")
        return rc

    staged = (STAGING / NAME / f"{NAME}.exe") if args.onedir else (STAGING / f"{NAME}.exe")
    if not staged.exists():
        print("未找到产物:", staged)
        return 1

    # 搬到主目录：单文件就是 ./FlowLens.exe，目录版是 ./FlowLens/
    try:
        if args.onedir:
            final_dir = ROOT / NAME
            shutil.rmtree(final_dir, ignore_errors=True)
            shutil.move(str(STAGING / NAME), str(final_dir))
            target = final_dir / f"{NAME}.exe"
        else:
            target = ROOT / f"{NAME}.exe"
            # 用 os.replace 直接原子覆盖，不先 unlink：
            # 某些安全软件会拦截「删除后再写」的删除动作，导致打包明明成功却搬不出产物。
            os.replace(str(staged), str(target))
    except OSError as exc:
        print(f"\n无法写入 {ROOT}（文件被占用？请先关闭正在运行的程序）：{exc}")
        return 1

    shutil.rmtree(STAGING, ignore_errors=True)
    size = target.stat().st_size / 1024 / 1024
    print(f"\n完成：{target}\n体积：{size:.1f} MB")
    if not args.keep:
        shutil.rmtree(WORK, ignore_errors=True)
    print("提示：exe 已放到源码目录的上一层（程序主目录），与 data/、logs/ 同级；"
          "启动时会自动申请管理员权限，无需右键「以管理员身份运行」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
