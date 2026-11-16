"""数据存储模块 —— 只读查询仓库。

把 SQL 聚合与业务查询集中在这里，统计模块只消费查询结果，
界面层完全不感知 SQL，便于替换存储实现。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from ..storage.database import Database
from ..core.daterange import day_str
from ..core.models import AppCandidate


@dataclass
class Row:
    app_id: int
    key: str
    name: str
    exe_path: str | None
    kind: str
    upload: int
    download: int
    days_active: int

    @property
    def total(self) -> int:
        return self.upload + self.download


SORT_FIELDS = {
    "total": "total",
    "upload": "upload",
    "download": "download",
    "name": "name",
    "avg": "avg",
}


class TrafficRepository:
    def __init__(self, db: Database):
        self._db = db
        self._lock = db._lock
        self._conn: sqlite3.Connection = db._conn

    # ------------------------------------------------------------------ 应用维度
    def app_rows(self, start: dt.date, end: dt.date, *,
                 search: str = "", sort_by: str = "total", descending: bool = True,
                 limit: int | None = None) -> list[Row]:
        s, e = day_str(start), day_str(end)
        sql = [
            "SELECT a.id AS app_id, a.key AS key, a.display_name AS name, a.exe_path AS exe_path,",
            "       a.kind AS kind,",
            "       COALESCE(SUM(t.upload_bytes),0) AS upload,",
            "       COALESCE(SUM(t.download_bytes),0) AS download,",
            "       COUNT(t.day) AS days_active",
            "FROM traffic_daily t JOIN app a ON a.id = t.app_id",
            "WHERE t.day BETWEEN ? AND ?",
        ]
        params: list[object] = [s, e]
        q = (search or "").strip().lower()
        if q:
            sql.append("AND (lower(a.display_name) LIKE ? OR lower(a.key) LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        sql.append("GROUP BY a.id")
        order = {
            "total": "(SUM(t.upload_bytes)+SUM(t.download_bytes))",
            "upload": "SUM(t.upload_bytes)",
            "download": "SUM(t.download_bytes)",
            "name": "a.display_name COLLATE NOCASE",
            "avg": "((SUM(t.upload_bytes)+SUM(t.download_bytes))*1.0/COUNT(t.day))",
        }.get(sort_by, "(SUM(t.upload_bytes)+SUM(t.download_bytes))")
        sql.append(f"ORDER BY {order} {'DESC' if descending else 'ASC'}, a.display_name ASC")
        if limit:
            sql.append(f"LIMIT {int(limit)}")
        with self._lock:
            cur = self._conn.execute("\n".join(sql), params)
            out = [
                Row(int(r["app_id"]), r["key"], r["name"], r["exe_path"], r["kind"],
                    int(r["upload"]), int(r["download"]), int(r["days_active"]))
                for r in cur.fetchall()
            ]
        return out

    def app_row(self, app_id: int, start: dt.date, end: dt.date) -> Row | None:
        s, e = day_str(start), day_str(end)
        with self._lock:
            r = self._conn.execute(
                "SELECT a.id AS app_id, a.key AS key, a.display_name AS name, a.exe_path AS exe_path,"
                "       a.kind AS kind,"
                "       COALESCE(SUM(t.upload_bytes),0) AS upload,"
                "       COALESCE(SUM(t.download_bytes),0) AS download,"
                "       COUNT(t.day) AS days_active"
                "  FROM app a LEFT JOIN traffic_daily t ON t.app_id = a.id"
                "   AND t.day BETWEEN ? AND ?"
                " WHERE a.id = ? GROUP BY a.id",
                (s, e, app_id),
            ).fetchone()
        if not r:
            return None
        return Row(int(r["app_id"]), r["key"], r["name"], r["exe_path"], r["kind"],
                   int(r["upload"]), int(r["download"]), int(r["days_active"]))

    def find_app_id(self, key: str) -> int | None:
        with self._lock:
            r = self._conn.execute("SELECT id FROM app WHERE key=?", (key,)).fetchone()
        return int(r["id"]) if r else None

    def exclude_candidates(self) -> list[AppCandidate]:
        """「排除应用」选择器的候选列表：库里出现过的全部应用。

        与 `app_rows` 不同，这里**不限定统计周期**——用户可能想排除一个最近
        没跑过、但历史上留下过记录的程序。按累计流量降序，方便一眼看到大头。
        """
        sql = """
SELECT a.key AS key, a.display_name AS name, a.kind AS kind, a.exe_path AS exe_path,
       COALESCE(SUM(t.upload_bytes + t.download_bytes), 0) AS total,
       MAX(t.day) AS last_day
  FROM app a
  LEFT JOIN traffic_daily t ON t.app_id = a.id
 WHERE a.kind IN ('app', 'system')
 GROUP BY a.id
 ORDER BY total DESC, a.display_name COLLATE NOCASE ASC
"""
        with self._lock:
            cur = self._conn.execute(sql)
            return [
                AppCandidate(
                    key=str(r["key"]),
                    name=str(r["name"]),
                    kind=str(r["kind"]),
                    exe_path=r["exe_path"],
                    total=int(r["total"] or 0),
                    last_day=r["last_day"],
                )
                for r in cur.fetchall()
            ]

    def app_label(self, app_id: int) -> tuple[str, str, str | None]:
        with self._lock:
            r = self._conn.execute(
                "SELECT key, display_name, exe_path FROM app WHERE id=?", (app_id,)
            ).fetchone()
        return (r["key"], r["display_name"], r["exe_path"]) if r else ("", "未知应用", None)

    # ------------------------------------------------------------------ 日期维度
    def daily_totals(self, start: dt.date, end: dt.date) -> dict[str, tuple[int, int]]:
        s, e = day_str(start), day_str(end)
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, SUM(upload_bytes) AS u, SUM(download_bytes) AS d"
                "  FROM traffic_daily WHERE day BETWEEN ? AND ? GROUP BY day",
                (s, e),
            ).fetchall()
        return {r["day"]: (int(r["u"]), int(r["d"])) for r in rows}

    def range_totals(self, start: dt.date, end: dt.date) -> tuple[int, int]:
        s, e = day_str(start), day_str(end)
        with self._lock:
            r = self._conn.execute(
                "SELECT COALESCE(SUM(upload_bytes),0) AS u, COALESCE(SUM(download_bytes),0) AS d"
                "  FROM traffic_daily WHERE day BETWEEN ? AND ?",
                (s, e),
            ).fetchone()
        return int(r["u"]), int(r["d"])

    def app_daily(self, app_id: int, start: dt.date, end: dt.date) -> dict[str, tuple[int, int]]:
        s, e = day_str(start), day_str(end)
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, upload_bytes AS u, download_bytes AS d FROM traffic_daily"
                " WHERE app_id=? AND day BETWEEN ? AND ?",
                (app_id, s, e),
            ).fetchall()
        return {r["day"]: (int(r["u"]), int(r["d"])) for r in rows}

    def active_app_count(self, start: dt.date, end: dt.date) -> int:
        s, e = day_str(start), day_str(end)
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(DISTINCT app_id) AS c FROM traffic_daily"
                " WHERE day BETWEEN ? AND ? AND (upload_bytes+download_bytes) > 0",
                (s, e),
            ).fetchone()
        return int(r["c"])

    def unclassified_total(self, start: dt.date, end: dt.date) -> int:
        s, e = day_str(start), day_str(end)
        with self._lock:
            r = self._conn.execute(
                "SELECT COALESCE(SUM(t.upload_bytes+t.download_bytes),0) AS c"
                "  FROM traffic_daily t JOIN app a ON a.id=t.app_id"
                " WHERE a.kind='unclassified' AND t.day BETWEEN ? AND ?",
                (s, e),
            ).fetchone()
        return int(r["c"])

    def system_daily(self, start: dt.date, end: dt.date) -> dict[str, tuple[int, int]]:
        s, e = day_str(start), day_str(end)
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, upload_bytes AS u, download_bytes AS d FROM system_daily"
                " WHERE day BETWEEN ? AND ?",
                (s, e),
            ).fetchall()
        return {r["day"]: (int(r["u"]), int(r["d"])) for r in rows}

    def stats(self) -> dict[str, object]:
        with self._lock:
            apps = self._conn.execute("SELECT COUNT(*) AS c FROM app").fetchone()["c"]
            rows = self._conn.execute("SELECT COUNT(*) AS c FROM traffic_daily").fetchone()["c"]
            tot = self._conn.execute(
                "SELECT COALESCE(SUM(upload_bytes),0) AS u, COALESCE(SUM(download_bytes),0) AS d"
                "  FROM traffic_daily"
            ).fetchone()
        return {"apps": int(apps), "days_rows": int(rows),
                "upload": int(tot["u"]), "download": int(tot["d"])}
