"""临时文件清理：收拾 %TEMP% 下残留的 ETW 采集目录。

ETW 精确采集期间，logman/tracerpt 会在 `%TEMP%\\netusage_etw_xxxxxxxx` 里中转
`.etl` 与 `.xml`；正常停止时采集器会自己删掉整个目录。但下面几种情况会留下残壳：

* 程序被任务管理器强制结束（`stop()` 里的清理没机会执行）；
* 采集线程初始化到一半抛异常；
* 提权进程创建的目录，之后以普通权限运行的程序删不动它（Windows ACL 所致）。

所以启动时（以及设置页手动触发时）扫一遍这些目录。为安全起见只处理：

1. 名字严格以 `netusage_etw_` 开头的 **目录**；
2. 修改时间早于 min_age_hours 的（默认 1 小时——正在采集的目录每 30 秒就有新写入，
   mtime 一定是新的，所以 1 小时没动过的必然不是活跃采集）；
3. `%TEMP%` 下的其它任何东西一律不碰。
"""
from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# 与 collector/etw.py 中 mkdtemp 的前缀保持一致
TEMP_PREFIX = "netusage_etw_"
# 正在采集的目录每 30 秒就会写入新的 .etl，mtime 一直是新的；
# 因此超过 1 小时没动过的目录一定不是活跃采集，可以安全删除。
DEFAULT_MIN_AGE_HOURS = 1.0


@dataclass
class CleanResult:
    """一次清理的结果统计。"""

    scanned: int = 0                 # 扫描到的候选目录数
    removed: int = 0                 # 成功删除数
    skipped: int = 0                 # 无法删除（多为权限不足）
    kept: int = 0                    # 因为正在被采集器使用而主动跳过
    freed: int = 0                   # 释放的字节数
    skipped_names: list[str] = field(default_factory=list)
    kept_names: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.skipped == 0 and self.kept == 0

    def summary(self) -> str:
        """给日志/界面用的一行中文说明。"""
        from .units import format_bytes

        if self.scanned == 0:
            return "没有发现残留的临时目录"
        if self.removed == 0 and self.skipped == 0:
            return f"{self.kept} 个临时目录正在使用中，已跳过"
        parts = [f"清理 {self.removed} 个残留目录，释放 {format_bytes(self.freed)}"]
        if self.kept:
            parts.append(f"{self.kept} 个正在使用已跳过")
        if self.skipped:
            parts.append(f"{self.skipped} 个因权限不足未能删除")
        return "，".join(parts)


def temp_root() -> Path:
    """系统的临时目录（通常 %LOCALAPPDATA%\\Temp）。"""
    return Path(tempfile.gettempdir())


def _dir_size(path: Path) -> int:
    """目录内所有文件的字节合计；读不到的部分按 0 计。"""
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def find_stale(min_age_hours: float = DEFAULT_MIN_AGE_HOURS,
               prefix: str = TEMP_PREFIX,
               root: Path | str | None = None) -> list[Path]:
    """列出可清理的残留目录（只返回名字带前缀、且够旧的目录）。"""
    base = Path(root) if root is not None else temp_root()
    try:
        if not base.is_dir():
            return []
        entries = list(base.iterdir())
    except OSError:
        return []

    deadline = time.time() - max(0.0, float(min_age_hours)) * 3600.0
    stale: list[Path] = []
    for item in entries:
        if not item.name.startswith(prefix):
            continue
        try:
            if not item.is_dir():          # 同名的文件不归我们管
                continue
            if item.stat().st_mtime > deadline:   # 可能是别的实例正在用
                continue
        except OSError:
            continue
        stale.append(item)
    return stale


def clean(min_age_hours: float = DEFAULT_MIN_AGE_HOURS,
          prefix: str = TEMP_PREFIX,
          root: Path | str | None = None,
          keep: tuple[str, ...] | list[str] = ()) -> CleanResult:
    """删除残留目录；`keep` 里的路径即使是候选也跳过。"""
    keep_set = {str(Path(p)) for p in keep}
    result = CleanResult()
    for path in find_stale(min_age_hours, prefix, root):
        result.scanned += 1
        if str(path) in keep_set:
            result.kept += 1
            result.kept_names.append(path.name)
            continue
        size = _dir_size(path)
        try:
            shutil.rmtree(path)
        except OSError:
            # 典型原因：目录由提权进程创建，当前是普通权限；或者里面还有文件被占用
            result.skipped += 1
            result.skipped_names.append(path.name)
            continue
        result.removed += 1
        result.freed += size
    return result


def pending(prefix: str = TEMP_PREFIX,
            root: Path | str | None = None) -> tuple[int, int]:
    """返回 (残留目录数, 占用字节数)，供界面展示当前状态。"""
    items = find_stale(0, prefix, root)
    return len(items), sum(_dir_size(p) for p in items)
