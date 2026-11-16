"""界面模块 —— 页面共享的上下文对象。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..collector.service import CollectorService
from ..core.config import AppConfig
from ..stats.aggregator import StatsService
from ..stats.exporter import ReportExporter
from ..storage.database import Database
from ..storage.repository import TrafficRepository


@dataclass
class UiContext:
    config: AppConfig
    db: Database
    repo: TrafficRepository
    stats: StatsService
    exporter: ReportExporter
    service: CollectorService
    source_label: Callable[[], str]
