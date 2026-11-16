"""采集器 —— Windows ETW 精确模式（Microsoft-Windows-Kernel-Network）。

原理
----
Windows 内核通过 ETW 提供程序 `Microsoft-Windows-Kernel-Network`
（GUID 7dd42a49-5329-4832-8dfd-43d979153a88）逐包上报 TCP/UDP 收发事件，
每条事件包含「发起进程 PID」与「字节数」，这是系统层面唯一权威的
按进程流量来源（资源监视器、任务管理器「应用历史记录」同源）。

本模块用系统自带的 logman + tracerpt 完成「抓取 → 导出 → 解析」：
  1. logman start  -ets -p <GUID>   启动一个文件型 ETW 会话
  2. 等待一个采集周期（默认 30s）
  3. logman stop  -ets              收尾并落盘 .etl
  4. tracerpt  -of XML              把 .etl 转成带字段名的 XML
  5. 解析事件 → 按 PID 归属应用 → 汇总成 TrafficEvent

相比直接调用 ETW API，此方案零原生依赖、无需编译，且能拿到官方字段名。
限制：启动 ETW 会话需要管理员权限，否则会得到 ACCESS_DENIED。
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import BaseCollector, CollectorUnavailable, EmitFn, TrafficEvent
from ..core import appnames, winadmin

PROVIDER_GUID = "{7dd42a49-5329-4832-8dfd-43d979153a88}"
# ETW 会话名沿用旧标识：改名会让升级前后两个版本各自开一个会话，
# 残留会话更难清理，而这个名字用户看不到，故保持不动。
SESSION_NAME = "NetUsageMonitorTrace"

# 事件 ID → 方向（依据 Microsoft-Windows-Kernel-Network 清单文件的事件定义）：
#   IPv4: 10 TCP_SEND 11 TCP_RECV 12 CONNECT 13 DISCONNECT 14 RETRANSMIT 15 COPY
#         16 UDP_SEND 17 UDP_RECV ...
#   IPv6: 26 TCP_SEND 27 TCP_RECV 28 CONNECT 29 DISCONNECT 30 RETRANSMIT 31 COPY
#         32 UDP_SEND 33 UDP_RECV ...
# 仅统计「数据收发」事件；重传/RETRANSMIT/COPY 不计入，避免同一份字节被重复累计。
EVENT_DIRECTION: dict[int, str] = {
    10: "up",     # IPv4 TCP 数据发送
    11: "down",   # IPv4 TCP 数据接收
    16: "up",     # IPv4 UDP 发送
    17: "down",   # IPv4 UDP 接收
    26: "up",     # IPv6 TCP 数据发送
    27: "down",   # IPv6 TCP 数据接收
    32: "up",     # IPv6 UDP 发送
    33: "down",   # IPv6 UDP 接收
}

_CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    """是否具备管理员权限（启动 ETW 会话的硬性前提）。"""
    return winadmin.is_elevated()


def _run(cmd: list[str], timeout: float = 120.0) -> tuple[int, str]:
    """执行系统命令，统一编码为本地 ANSI（中文系统为 GBK）。"""
    flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, creationflags=flags,
            encoding="mbcs", errors="replace",
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out
    except FileNotFoundError:
        return -1, "命令不存在"
    except subprocess.TimeoutExpired:
        return -2, "命令执行超时"


class EtwCollector(BaseCollector):
    mode = "etw"
    label = "ETW 精确模式"
    precise = True
    needs_admin = True

    def __init__(self, config):
        super().__init__(config)
        self._tmpdir: Path | None = None
        self._name_cache: dict[int, appnames.AppIdentity] = {}
        self._admin = is_admin()

    @property
    def work_dir(self) -> Path | None:
        """当前正在使用的临时目录；设置页清理残留时据此排除，避免删掉在写的文件。"""
        return self._tmpdir

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if sys.platform != "win32":
            raise CollectorUnavailable("当前系统不支持 ETW 采集", "精确模式仅在 Windows 上可用")
        if not self._admin:
            raise CollectorUnavailable(
                "需要管理员权限才能订阅内核网络事件",
                "程序启动时会自动申请管理员权限；若被拒绝，请重启程序并在 UAC 中点「是」",
            )
        self._tmpdir = Path(tempfile.mkdtemp(prefix="netusage_etw_"))
        self._stop_session()          # 清理上次异常退出残留的会话
        # 试探性启动，尽早暴露权限/组件问题（失败会抛 CollectorUnavailable）
        self._start_session(self._tmpdir / "probe.etl")
        self._stop_session()

    def stop(self) -> None:
        self._stopped.set()
        self._stop_session()
        if self._tmpdir and self._tmpdir.exists():
            for f in self._tmpdir.glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            try:
                self._tmpdir.rmdir()
            except OSError:
                pass

    # ------------------------------------------------------------------ 主循环
    def run(self, emit: EmitFn, stop) -> None:
        assert self._tmpdir is not None
        interval = max(15, int(self.config.collect_interval))
        reconcile = bool(getattr(self.config, "reconcile_unclassified", True))
        seq = 0
        while not stop.is_set():
            etl = self._tmpdir / f"trace_{seq}.etl"
            seq = (seq + 1) % 2
            try:
                self._start_session(etl)
            except CollectorUnavailable:
                raise
            baseline = self._system_counters() if reconcile else None
            # 采集窗口：分片等待，保证停止指令能及时响应
            waited = 0.0
            while waited < interval and not stop.is_set():
                time.sleep(0.5)
                waited += 0.5
            tail = self._system_counters() if reconcile else None
            self._stop_session()
            try:
                events = self._harvest(etl, emit)
                if reconcile and baseline and tail:
                    events.extend(self._surplus_as_unclassified(baseline, tail, events))
                if events:
                    emit(events)
            finally:
                self._cleanup(etl)

    # ------------------------------------------------------------------ 校准
    @staticmethod
    def _system_counters():
        try:
            import psutil
            c = psutil.net_io_counters()
            return int(c.bytes_sent), int(c.bytes_recv)
        except Exception:
            return None

    @staticmethod
    def _surplus_as_unclassified(baseline, tail, events: list[TrafficEvent]) -> list[TrafficEvent]:
        """把「系统总收发」与「已归属到应用的字节」之间的差额计入未分类。

        差额来自：进程已退出、系统保留 PID、驱动/回环等无法归属的流量。
        这样即使用户把所有应用流量相加，也能与系统总量对齐，口径自洽。
        """
        sys_up = max(0, tail[0] - baseline[0])
        sys_down = max(0, tail[1] - baseline[1])
        if sys_up + sys_down <= 0:
            return []
        got_up = sum(e.upload for e in events)
        got_down = sum(e.download for e in events)
        gap_up = sys_up - got_up
        gap_down = sys_down - got_down
        threshold = max(256 * 1024, int((sys_up + sys_down) * 0.03))
        if gap_up + gap_down < threshold:
            return []
        ident = appnames.unclassified()
        return [TrafficEvent(ident.key, ident.name, ident.kind, None,
                             max(0, gap_up), max(0, gap_down), dt.datetime.now())]

    # ------------------------------------------------------------------ ETW 会话
    def _start_session(self, etl: Path) -> None:
        code, out = _run([
            "logman", "start", SESSION_NAME,
            "-p", PROVIDER_GUID, "0xFFFFFFFFFFFFFFFF", "5",
            "-o", str(etl), "-f", "bin", "-ets",
        ], timeout=30)
        ok = code == 0 and self._session_exists()
        if not ok:
            self._stop_session()
            text = (out or "").strip()
            low = text.lower()
            if "denied" in low or "拒绝" in text or code == 5:
                raise CollectorUnavailable(
                    "启动 ETW 会话失败：访问被拒绝",
                    "请重启程序并在 UAC 弹窗中点「是」；或改用估算模式",
                )
            raise CollectorUnavailable(
                f"启动 ETW 会话失败（logman 返回 {code}）",
                text[:300] or "请确认系统未禁用 ETW 服务（Event Trace Sessions）",
            )

    def _session_exists(self) -> bool:
        code, out = _run(["logman", "query", "-ets"], timeout=30)
        return code == 0 and SESSION_NAME.lower() in (out or "").lower()

    def _stop_session(self) -> None:
        _run(["logman", "stop", SESSION_NAME, "-ets"], timeout=30)

    def _cleanup(self, etl: Path) -> None:
        for suffix in (".etl", ".xml"):
            p = etl.with_suffix(suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ 解析
    def _harvest(self, etl: Path, emit: EmitFn) -> list[TrafficEvent]:
        """把 .etl 转 XML 并解析成应用级增量。"""
        if not etl.exists() or etl.stat().st_size == 0:
            return []
        xml_path = etl.with_suffix(".xml")
        code, out = _run(["tracerpt", str(etl), "-of", "XML", "-o", str(xml_path), "-y"], timeout=300)
        if code != 0 or not xml_path.exists():
            raise CollectorUnavailable(
                f"解析 ETW 日志失败（tracerpt 返回 {code}）",
                (out or "").strip()[:300] or "请确认 tracerpt.exe 可用",
            )
        return self._parse_xml(xml_path, emit)

    def _parse_xml(self, xml_path: Path, emit: EmitFn) -> list[TrafficEvent]:
        agg: dict[int, list[int]] = {}          # pid -> [up, down]
        ts_map: dict[int, dt.datetime] = {}     # pid -> 最近一次事件时间
        count = 0
        try:
            for _, elem in ET.iterparse(str(xml_path), events=("end",)):
                if not elem.tag.endswith("Event"):
                    continue
                sys_node = data_node = None
                for child in elem:
                    tag = child.tag.rsplit("}", 1)[-1]
                    if tag == "System":
                        sys_node = child
                    elif tag == "EventData":
                        data_node = child
                if sys_node is None or data_node is None:
                    elem.clear()
                    continue
                event_id = when = None
                for child in sys_node:
                    tag = child.tag.rsplit("}", 1)[-1]
                    if tag == "EventID":
                        try:
                            event_id = int(child.text or "0")
                        except ValueError:
                            event_id = None
                    elif tag == "TimeCreated":
                        when = child.get("SystemTime")
                direction = EVENT_DIRECTION.get(event_id or -1)
                if direction is None:
                    elem.clear()
                    continue
                pid = size = None
                for item in data_node:
                    name = (item.get("Name") or "").lower()
                    value = (item.text or "").strip()
                    if name == "pid" or (name == "" and pid is None):
                        try:
                            pid = int(value, 0)
                        except ValueError:
                            pid = None
                    elif name == "size" or (name == "" and pid is not None and size is None):
                        try:
                            size = int(value, 0)
                        except ValueError:
                            size = None
                elem.clear()
                if not pid or not size or size <= 0:
                    continue
                slot = agg.setdefault(pid, [0, 0])
                slot[0 if direction == "up" else 1] += size
                if when:
                    try:
                        ts_map[pid] = dt.datetime.strptime(when[:19], "%Y-%m-%dT%H:%M:%S")
                    except ValueError:
                        pass
                count += 1
                if count > 2_000_000:      # 防御性上限，避免异常日志拖死界面
                    break
        except ET.ParseError as exc:
            raise CollectorUnavailable(f"ETW 日志格式异常：{exc}", "已跳过本批次数据") from exc
        finally:
            try:
                xml_path.unlink()
            except OSError:
                pass

        now = dt.datetime.now()
        events: list[TrafficEvent] = []
        for pid, (up, down) in agg.items():
            ident = self._identify_pid(pid)
            events.append(TrafficEvent(
                key=ident.key, name=ident.name, kind=ident.kind,
                exe_path=ident.exe_path,
                upload=up, download=down, ts=ts_map.get(pid, now),
            ))
        return events

    def _identify_pid(self, pid: int):
        """PID → 应用身份；进程已退出或无权读取时归入未分类。"""
        cached = self._name_cache.get(pid)
        if cached is not None:
            return cached
        ident = appnames.unclassified()
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
            self._name_cache[pid] = ident
        return ident

    def describe(self) -> str:
        return "ETW 精确模式（逐连接统计，管理员权限已获取）"
