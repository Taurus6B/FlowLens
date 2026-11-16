"""数值单位换算与展示格式化。

统计口径中所有原始数据均以「字节」为单位存储，展示时自动换算为
B / KB / MB / GB / TB，采用 1024 进制（与 Windows 资源监视器一致）。
"""
from __future__ import annotations

UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
_STEPS = (1, 1024, 1024 ** 2, 1024 ** 3, 1024 ** 4, 1024 ** 5)


def split_bytes(value: float) -> tuple[float, str]:
    """把字节数拆成 (数值, 单位)，便于图表坐标轴单独排版。"""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    negative = v < 0
    v = abs(v)
    idx = 0
    while idx < len(UNITS) - 1 and v >= 1024:
        v /= 1024.0
        idx += 1
    if negative:
        v = -v
    return v, UNITS[idx]


def format_bytes(value: float, *, empty_zero: bool = False) -> str:
    """自动换算单位的可读字符串，例如 1536 -> '1.50 KB'。"""
    if empty_zero and not value:
        return "—"
    v, unit = split_bytes(value)
    if unit == "B":
        return f"{int(round(v))} B"
    if abs(v) < 10:
        return f"{v:.2f} {unit}"
    if abs(v) < 100:
        return f"{v:.1f} {unit}"
    return f"{v:.0f} {unit}"


def format_bytes_compact(value: float) -> str:
    """坐标轴用紧凑写法：1.5K / 320M / 2.1G，同一坐标轴上小数位保持一致。"""
    v, unit = split_bytes(value)
    short = {"B": "B", "KB": "K", "MB": "M", "GB": "G", "TB": "T", "PB": "P"}[unit]
    if short == "B":
        return f"{int(round(v))}B"
    if abs(v) >= 100:
        return f"{v:.0f}{short}"
    text = f"{v:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}{short}"


def format_percent(ratio: float, digits: int = 1) -> str:
    """0.1234 -> '12.3%'；分母为 0 时返回 '0.0%'。"""
    try:
        r = float(ratio or 0) * 100.0
    except (TypeError, ValueError):
        r = 0.0
    if r != 0 and abs(r) < 0.1:
        return "<0.1%"
    return f"{r:.{digits}f}%"


def format_delta(current: float, previous: float) -> tuple[str, str]:
    """返回 (展示文本, 语义方向 up/down/flat)，用于环比展示。"""
    if not previous:
        return "—", "flat"
    change = (current - previous) / previous * 100.0
    if abs(change) < 0.05:
        return "0.0%", "flat"
    arrow = "▲" if change > 0 else "▼"
    return f"{arrow} {abs(change):.1f}%", ("up" if change > 0 else "down")


def format_count(value: int) -> str:
    return f"{int(value):,}"
