"""统计周期（起止日期）模型与边界处理。

规则：
  * 起止日期均为「闭区间」，均按本机时区的自然日切分；
  * 单个统计周期最长 max_days 天（默认 31 天）；
  * 结束日期不允许晚于今天，超出部分自动收敛到今天；
  * 起始日期早于数据保留期时，允许查询但结果会如实反映空档。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MAX_RANGE_DAYS_DEFAULT = 31


class RangeError(ValueError):
    """统计周期非法（超长、倒置、完全在未来等）。"""


def today() -> dt.date:
    return dt.date.today()


def parse_day(text: str) -> dt.date:
    return dt.datetime.strptime(text.strip(), "%Y-%m-%d").date()


def day_str(value: dt.date) -> str:
    return value.strftime("%Y-%m-%d")


def days_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """闭区间内的全部日期。"""
    if end < start:
        return []
    total = (end - start).days
    return [start + dt.timedelta(days=i) for i in range(total + 1)]


@dataclass(frozen=True)
class DateRange:
    start: dt.date
    end: dt.date

    # ---- 构造 -------------------------------------------------------
    @classmethod
    def last_days(cls, days: int, *, end: dt.date | None = None) -> "DateRange":
        days = max(1, int(days))
        e = end or today()
        return cls(e - dt.timedelta(days=days - 1), e)

    @classmethod
    def for_month(cls, end: dt.date | None = None, days: int = 30) -> "DateRange":
        return cls.last_days(days, end=end)

    def clamp(self, *, max_days: int = MAX_RANGE_DAYS_DEFAULT,
              upper: dt.date | None = None) -> "DateRange":
        """把非法/越界的周期收敛为可计算的范围，而不是直接失败。"""
        upper = upper or today()
        start, end = self.start, self.end
        if end > upper:
            end = upper
        if start > end:
            start = end
        if (end - start).days + 1 > max_days:
            start = end - dt.timedelta(days=max_days - 1)
        return DateRange(start, end)

    # ---- 校验 -------------------------------------------------------
    def validate(self, *, max_days: int = MAX_RANGE_DAYS_DEFAULT,
                 upper: dt.date | None = None) -> None:
        upper = upper or today()
        if self.end < self.start:
            raise RangeError("结束日期不能早于起始日期")
        if self.start > upper or self.end > upper:
            raise RangeError("结束日期不能晚于今天，请选择今天或更早的日期")
        if self.length > max_days:
            raise RangeError(f"统计周期最长 {max_days} 天，当前为 {self.length} 天")

    # ---- 属性 -------------------------------------------------------
    @property
    def length(self) -> int:
        return (self.end - self.start).days + 1

    def days(self) -> list[dt.date]:
        return days_between(self.start, self.end)

    def contains(self, day: dt.date) -> bool:
        return self.start <= day <= self.end

    def previous(self) -> "DateRange":
        """紧邻的上一个等长周期，用于环比。"""
        span = dt.timedelta(days=self.length)
        return DateRange(self.start - span, self.start - dt.timedelta(days=1))

    def overlaps(self, other: "DateRange") -> bool:
        return not (self.end < other.start or other.end < self.start)

    def as_sql(self) -> tuple[str, str]:
        return day_str(self.start), day_str(self.end)

    def label(self) -> str:
        if self.start == self.end:
            return day_str(self.start)
        return f"{day_str(self.start)} ~ {day_str(self.end)}"

    def short_label(self) -> str:
        return f"{self.start.month:02d}/{self.start.day:02d} - {self.end.month:02d}/{self.end.day:02d}"

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return self.label()
