"""采集器 —— 估算模式（无需管理员权限的降级方案）。

在无法取得 ETW 权限时，程序仍要给出「有参考价值」的统计，而不是空白：
  1. 用 psutil 读取全网卡累计收发字节，得到精确的「系统总流量」增量；
  2. 读取当前所有 TCP/UDP 连接，按 PID 统计每个应用持有的活动连接数；
  3. 以活动连接数作为权重，把系统总流量分摊给各应用。

该模式下「总流量」是准确的，应用间的分配比例是估算值，
界面会用醒目的「估算」标识提示，并建议以管理员身份重启以启用精确模式。
"""
from __future__ import annotations

import datetime as dt
import threading
import time

from .base import BaseCollector, CollectorUnavailable, EmitFn, TrafficEvent
from ..core import appnames


class EstimateCollector(BaseCollector):
    mode = "estimate"
    label = "估算模式"
    precise = False
    needs_admin = False

    def __init__(self, config):
        super().__init__(config)
        self._name_cache: dict[int, appnames.AppIdentity] = {}

    def start(self) -> None:
        try:
            import psutil  # noqa: F401
        except ImportError as exc:      # pragma: no cover
            raise CollectorUnavailable(
                "缺少依赖 psutil，无法读取系统网络计数",
                "请执行：python -m pip install psutil",
            ) from exc
        try:
            import psutil
            psutil.net_io_counters()
        except Exception as exc:        # pragma: no cover
            raise CollectorUnavailable(f"无法读取系统网络计数：{exc}", "请检查系统网络组件状态") from exc

    def run(self, emit: EmitFn, stop: threading.Event) -> None:
        import psutil
        interval = max(3, min(60, int(self.config.flush_interval) * 2))
        prev = psutil.net_io_counters()
        while not stop.wait(interval):
            try:
                cur = psutil.net_io_counters()
            except Exception:
                continue
            delta_up = max(0, cur.bytes_sent - prev.bytes_sent)
            delta_down = max(0, cur.bytes_recv - prev.bytes_recv)
            prev = cur
            if delta_up + delta_down <= 0:
                continue      # 无网络活动：不产生任何记录
            events = self._split(delta_up, delta_down)
            if events:
                emit(events)

    # ------------------------------------------------------------------
    def _split(self, delta_up: int, delta_down: int) -> list[TrafficEvent]:
        weights = self._connection_weights()
        total_weight = sum(w for _, w in weights)
        now = dt.datetime.now()
        if total_weight <= 0:
            # 完全无法识别归属 → 全部计入未分类（诚实反映能力边界）
            ident = appnames.unclassified()
            return [TrafficEvent(ident.key, ident.name, ident.kind, None,
                                 delta_up, delta_down, now)]

        events: list[TrafficEvent] = []
        used_up = used_down = 0
        for idx, (ident, weight) in enumerate(weights):
            ratio = weight / total_weight
            if idx == len(weights) - 1:       # 余数给最后一个，保证总量守恒
                up = delta_up - used_up
                down = delta_down - used_down
            else:
                up = int(delta_up * ratio)
                down = int(delta_down * ratio)
            used_up += up
            used_down += down
            if up + down <= 0:
                continue
            events.append(TrafficEvent(ident.key, ident.name, ident.kind,
                                       ident.exe_path, up, down, now))
        return events

    def _connection_weights(self) -> list[tuple[appnames.AppIdentity, float]]:
        """按 PID 统计活动连接数作为分摊权重。"""
        try:
            import psutil
        except ImportError:      # pragma: no cover
            return []
        counts: dict[int, int] = {}
        try:
            conns = psutil.net_connections(kind="inet")
        except Exception:
            return []
        for conn in conns:
            pid = conn.pid or 0
            if pid <= 0:
                continue
            counts[pid] = counts.get(pid, 0) + (2 if conn.status == "ESTABLISHED" else 1)

        # 同一应用（exe）的多个进程实例合并
        merged: dict[str, list] = {}
        for pid, weight in counts.items():
            ident = self._identify(pid)
            slot = merged.get(ident.key)
            if slot is None:
                merged[ident.key] = [ident, float(weight)]
            else:
                slot[1] += weight
        return [(item[0], item[1]) for item in merged.values()]

    def _identify(self, pid: int) -> appnames.AppIdentity:
        cached = self._name_cache.get(pid)
        if cached is not None:
            return cached
        try:
            import psutil
            proc = psutil.Process(pid)
            raw = proc.name()
            try:
                path = proc.exe()
            except (psutil.AccessDenied, OSError):
                path = None
            ident = appnames.identify(raw, path)
        except Exception:
            ident = appnames.unclassified()
        self._name_cache[pid] = ident
        if len(self._name_cache) > 4000:
            self._name_cache.clear()
        return ident

    def describe(self) -> str:
        return "估算模式（系统总流量精确，按活动连接分摊到应用）"
