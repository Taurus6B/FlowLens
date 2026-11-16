"""采集服务 —— 采集器生命周期、缓冲聚合与定时落库。

结构：
    采集线程  ──emit──▶  内存缓冲（应用 × 日期）  ──flush──▶  SQLite
                                                          ▲
                                            UI 只读数据库（每 5 秒刷新）

这样界面永远不会被采集阻塞，进程异常退出时数据库里也只损失
最后一个未刷新的批次（默认 5 秒），重启后历史数据完整保留。
"""
from __future__ import annotations

import datetime as dt
import threading
import time

from .base import BaseCollector, CollectorUnavailable, TrafficEvent
from .estimate import EstimateCollector
from .etw import EtwCollector, is_admin
from ..core import appnames
from ..core.config import AppConfig
from ..core.models import CollectorStatus

MODE_TEXT = {
    "etw": "精确模式运行中",
    "estimate": "估算模式运行中",
    "demo": "演示模式（合成数据）",
}


class CollectorService:
    def __init__(self, db, config: AppConfig):
        self._db = db
        self._config = config
        self._lock = threading.RLock()
        self._buf: dict[tuple[str, str], list[int]] = {}
        self._idents: dict[str, appnames.AppIdentity] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._collector: BaseCollector | None = None
        self._status = CollectorStatus()
        self._last_prune = 0.0
        self._seeded = False

    # ------------------------------------------------------------------ 状态
    @property
    def status(self) -> CollectorStatus:
        with self._lock:
            return self._status

    def update_status(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self._status, k, v)

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._status.running)

    # ------------------------------------------------------------------ 启动/停止
    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        self.update_status(mode="init", label="初始化中", running=False, ok=True,
                           message="正在启动采集引擎…")
        t = threading.Thread(target=self._worker, name="collector", daemon=True)
        t.start()
        self._threads.append(t)
        f = threading.Thread(target=self._flusher, name="flusher", daemon=True)
        f.start()
        self._threads.append(f)

    def stop(self) -> None:
        self._stop.set()
        coll = self._collector
        if coll is not None:
            try:
                coll.stop()
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()
        self._flush(force=True)
        self.update_status(running=False, label="已停止")

    # ------------------------------------------------------------------ 采集线程
    def _candidates(self) -> list[tuple[str, str]]:
        """返回按优先级排列的候选采集模式（mode, 降级说明）。"""
        mode = self._config.collector_mode
        if mode == "demo":
            return [("demo", "")]
        if mode == "estimate":
            return [("estimate", "")]
        if mode == "etw":
            return [("etw", ""),
                    ("estimate", "精确模式不可用，已自动降级为估算模式")]
        # auto：优先精确模式，失败自动降级
        return [("etw", ""),
                ("estimate", "未获得管理员权限，已自动降级为估算模式")]

    def _worker(self) -> None:
        reasons: list[str] = []
        for idx, (mode, fallback_note) in enumerate(self._candidates()):
            collector = self._build(mode)
            if collector is None:
                reasons.append(f"{mode}: 未知模式")
                continue
            try:
                collector.start()
            except CollectorUnavailable as exc:
                reasons.append(str(exc) + (f"（{exc.hint}）" if exc.hint else ""))
                continue
            except Exception as exc:                       # 兜底：任何异常不失联
                reasons.append(f"{mode}: {exc}")
                continue

            self._collector = collector
            if mode == "demo" and not self._seeded:
                self._seed_demo()
            note = fallback_note if (fallback_note and reasons) else ""
            detail = collector.describe() if hasattr(collector, "describe") else ""
            self.update_status(
                mode=collector.mode,
                label=MODE_TEXT[mode],
                running=True, ok=True, privileged=is_admin(),
                message=note or detail or MODE_TEXT[mode],
            )
            try:
                collector.run(self._on_events, self._stop)
                return
            except CollectorUnavailable as exc:
                reasons.append(f"{exc}。{exc.hint}".strip())
                self.update_status(ok=False, label="采集中断", message=str(exc))
                continue
            except Exception as exc:                        # pragma: no cover
                reasons.append(f"采集线程异常：{exc}")
                continue

        # 全部采集器都不可用
        self.update_status(mode="none", label="采集不可用", running=False, ok=False,
                           message="；".join(reasons) or "没有可用的采集方式")

    def _build(self, mode: str) -> BaseCollector | None:
        if mode == "etw":
            return EtwCollector(self._config)
        if mode == "estimate":
            return EstimateCollector(self._config)
        if mode == "demo":
            from .simulator import SimulatorCollector
            return SimulatorCollector(self._config)
        return None

    def _seed_demo(self) -> None:
        self._seeded = True
        try:
            from .simulator import SimulatorCollector
            if self._db.app_count() == 0:
                SimulatorCollector(self._config).seed_history(
                    self._db, days=self._config.max_range_days + 2
                )
        except Exception:
            pass

    # ------------------------------------------------------------------ 缓冲
    def _on_events(self, events: list[TrafficEvent]) -> None:
        if not events:
            return
        total = 0
        with self._lock:
            for ev in events:
                if not ev.key:
                    continue
                self._idents[ev.key] = appnames.AppIdentity(
                    ev.key, ev.name, ev.kind, ev.exe_path
                )
                slot_key = (ev.key, ev.day())
                slot = self._buf.get(slot_key)
                if slot is None:
                    self._buf[slot_key] = [int(ev.upload), int(ev.download)]
                else:
                    slot[0] += int(ev.upload)
                    slot[1] += int(ev.download)
                total += ev.upload + ev.download
            self._status.events += len(events)
            self._status.bytes_seen += total

    # ------------------------------------------------------------------ 落库
    def _flusher(self) -> None:
        interval = max(2, int(self._config.flush_interval))
        while not self._stop.wait(interval):
            self._flush()
            if time.time() - self._last_prune > 3600:
                self._prune()

    def _flush(self, force: bool = False) -> None:
        with self._lock:
            if not self._buf:
                if force:
                    self._status.last_flush = dt.datetime.now()
                return
            batch = self._buf
            self._buf = {}
            idents = self._idents
        excluded = set(self._config.excluded_apps)
        rows: list[tuple[int, str, int, int]] = []
        try:
            for (key, day), (up, down) in batch.items():
                if key in excluded:
                    continue
                ident = idents.get(key) or appnames.AppIdentity(key, key)
                app_id = self._db.app_id(key, ident.name, ident.kind, ident.exe_path)
                rows.append((app_id, day, up, down))
            self._db.add_traffic_batch(rows)
            self._db.set_meta("last_flush", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as exc:                            # pragma: no cover
            self.update_status(ok=False, message=f"写入数据库失败：{exc}")
            return
        self.update_status(last_flush=dt.datetime.now())

    def _prune(self) -> None:
        self._last_prune = time.time()
        try:
            cutoff = dt.date.today() - dt.timedelta(days=self._config.retention_days)
            # 至少保留最近一个完整统计周期，避免用户选了 31 天却查不到数据
            self._db.prune(cutoff.strftime("%Y-%m-%d"))
        except Exception:
            pass

    def flush_now(self) -> None:
        self._flush(force=True)
