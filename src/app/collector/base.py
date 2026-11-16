"""采集模块 —— 采集器抽象。

采集器只负责「把原始网络字节归属到应用」，不关心存储与展示：
  * TrafficEvent 表示一次归属于某应用的增量（上传/下载各多少字节）；
  * 子类实现 start() / run() / stop()，run() 在独立线程中循环，
    通过 emit 回调把事件交给服务层聚合。
"""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Callable

EmitFn = Callable[[list["TrafficEvent"]], None]


class CollectorUnavailable(RuntimeError):
    """采集器不可用（无权限、组件缺失、平台不支持等）。

    hint 会直接展示给用户，说明「为什么」以及「怎么办」。
    """

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass
class TrafficEvent:
    key: str
    name: str
    kind: str = "app"                 # app | system | unclassified
    exe_path: str | None = None
    upload: int = 0
    download: int = 0
    ts: dt.datetime = field(default_factory=dt.datetime.now)

    @property
    def total(self) -> int:
        return self.upload + self.download

    def day(self) -> str:
        return self.ts.strftime("%Y-%m-%d")


class BaseCollector:
    mode: str = "base"
    label: str = "未知采集器"
    precise: bool = False          # 是否为精确（逐连接）统计
    needs_admin: bool = False

    def __init__(self, config):
        self.config = config
        self._stopped = threading.Event()

    # ---- 生命周期 ----------------------------------------------------
    def start(self) -> None:
        """初始化资源，失败时抛 CollectorUnavailable。"""

    def run(self, emit: EmitFn, stop: threading.Event) -> None:
        """主循环，需自行处理 stop；返回即视为采集结束。"""
        raise NotImplementedError

    def stop(self) -> None:
        self._stopped.set()

    def describe(self) -> str:
        return self.label
