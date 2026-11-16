"""数据存储模块 —— SQLite 持久化。

设计要点：
  * 单文件数据库（data/traffic.db），WAL 模式，读写互不阻塞；
  * 以「应用 × 自然日」为最小统计粒度，累加写入，重启后数据自然保留；
  * 所有写操作使用 UPSERT 累加，避免重复统计与丢失；
  * 连接跨线程共享（collector 线程写、UI 线程读），用 RLock 串行化。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS app (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT    NOT NULL UNIQUE,
    display_name TEXT    NOT NULL,
    exe_path     TEXT,
    kind         TEXT    NOT NULL DEFAULT 'app',
    first_seen   TEXT    NOT NULL,
    last_seen    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS traffic_daily (
    app_id         INTEGER NOT NULL REFERENCES app(id) ON DELETE CASCADE,
    day            TEXT    NOT NULL,
    upload_bytes   INTEGER NOT NULL DEFAULT 0,
    download_bytes INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT    NOT NULL,
    PRIMARY KEY (app_id, day)
);
CREATE INDEX IF NOT EXISTS idx_traffic_day ON traffic_daily(day);

CREATE TABLE IF NOT EXISTS system_daily (
    day            TEXT PRIMARY KEY,
    upload_bytes   INTEGER NOT NULL DEFAULT 0,
    download_bytes INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """轻量 DAO：负责连接、建表、写入与基础维护。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(DDL)
            self._conn.commit()
        self._app_cache: dict[str, tuple[int, str]] = {}
        self._bootstrap_meta()

    # ------------------------------------------------------------------ 元信息
    def _bootstrap_meta(self) -> None:
        with self._lock:
            cur = self._conn.execute("SELECT v FROM meta WHERE k='schema_version'")
            row = cur.fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO meta(k, v) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
                )
                self._conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(k, v) VALUES(?, ?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (key, str(value)),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ 应用
    def app_id(self, key: str, display_name: str, kind: str = "app",
               exe_path: str | None = None) -> int:
        """按 key 取应用 id，不存在则创建。带内存缓存，热点路径无查询开销。"""
        cached = self._app_cache.get(key)
        if cached:
            return cached[0]
        ts = _now()
        with self._lock:
            row = self._conn.execute("SELECT id, display_name FROM app WHERE key=?", (key,)).fetchone()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO app(key, display_name, exe_path, kind, first_seen, last_seen) "
                    "VALUES(?,?,?,?,?,?)",
                    (key, display_name, exe_path, kind, ts, ts),
                )
                self._conn.commit()
                app_id, name = int(cur.lastrowid), display_name
            else:
                app_id, name = int(row["id"]), row["display_name"]
                self._conn.execute(
                    "UPDATE app SET last_seen=?, "
                    "exe_path=COALESCE(NULLIF(?, ''), exe_path) WHERE id=?",
                    (ts, exe_path or "", app_id),
                )
                self._conn.commit()
        self._app_cache[key] = (app_id, name)
        return app_id

    def app_map(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT key, id FROM app").fetchall()
        return {r["key"]: int(r["id"]) for r in rows}

    def app_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM app").fetchone()
        return int(row["c"])

    # ------------------------------------------------------------------ 写入
    def add_traffic(self, app_id: int, day: str, upload: int = 0, download: int = 0) -> None:
        if upload <= 0 and download <= 0:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO traffic_daily(app_id, day, upload_bytes, download_bytes, updated_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(app_id, day) DO UPDATE SET "
                "  upload_bytes   = upload_bytes + excluded.upload_bytes, "
                "  download_bytes = download_bytes + excluded.download_bytes, "
                "  updated_at     = excluded.updated_at",
                (app_id, day, int(upload), int(download), _now()),
            )

    def add_traffic_batch(self, rows: list[tuple[int, str, int, int]]) -> None:
        """批量累加写入：rows = [(app_id, 'YYYY-MM-DD', upload, download), ...]"""
        rows = [r for r in rows if (r[2] or 0) + (r[3] or 0) > 0]
        if not rows:
            return
        ts = _now()
        payload = [(int(a), d, int(u), int(dn), ts) for a, d, u, dn in rows]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO traffic_daily(app_id, day, upload_bytes, download_bytes, updated_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(app_id, day) DO UPDATE SET "
                "  upload_bytes   = upload_bytes + excluded.upload_bytes, "
                "  download_bytes = download_bytes + excluded.download_bytes, "
                "  updated_at     = excluded.updated_at",
                payload,
            )
            self._conn.commit()

    def set_system_day(self, day: str, upload: int, download: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO system_daily(day, upload_bytes, download_bytes, updated_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET upload_bytes=excluded.upload_bytes, "
                "download_bytes=excluded.download_bytes, updated_at=excluded.updated_at",
                (day, int(upload), int(download), _now()),
            )
            self._conn.commit()

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    # ------------------------------------------------------------------ 维护
    def prune(self, before_day: str) -> int:
        """清理早于保留期的明细，并回收不再有数据的应用记录。"""
        with self._lock:
            cur = self._conn.execute("DELETE FROM traffic_daily WHERE day < ?", (before_day,))
            removed = cur.rowcount or 0
            self._conn.execute("DELETE FROM system_daily WHERE day < ?", (before_day,))
            self._conn.execute(
                "DELETE FROM app WHERE kind != 'unclassified' AND id NOT IN "
                "(SELECT DISTINCT app_id FROM traffic_daily)"
            )
            self._conn.commit()
            if removed:
                self._app_cache.clear()
        return removed

    def clear_all(self) -> None:
        with self._lock:
            self._conn.executescript(
                "DELETE FROM traffic_daily; DELETE FROM system_daily; DELETE FROM app;"
            )
            self._conn.commit()
            self._app_cache.clear()

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")
            self._conn.commit()

    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def day_bounds(self) -> tuple[str | None, str | None]:
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(day) AS a, MAX(day) AS b FROM traffic_daily"
            ).fetchone()
        return (row["a"], row["b"]) if row else (None, None)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            except sqlite3.Error:
                pass
            self._conn.close()
