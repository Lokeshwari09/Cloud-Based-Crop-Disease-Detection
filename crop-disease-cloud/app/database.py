"""SQLite persistence for scan history (swap for Amazon RDS / DynamoDB in production)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id           TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
    filename     TEXT,
    image_key    TEXT,
    label        TEXT NOT NULL,
    confidence   REAL NOT NULL,
    severity     REAL,
    latency_ms   REAL,
    served_by    TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_scan(self, **r) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO scans (id, filename, image_key, label, confidence, severity, latency_ms, served_by) "
                "VALUES (:id, :filename, :image_key, :label, :confidence, :severity, :latency_ms, :served_by)",
                r,
            )

    def history(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM scans ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._conn() as c:
            total, avg_lat, avg_conf = c.execute(
                "SELECT COUNT(*), COALESCE(AVG(latency_ms),0), COALESCE(AVG(confidence),0) FROM scans"
            ).fetchone()
            by_label = {r["label"]: r["n"] for r in c.execute("SELECT label, COUNT(*) n FROM scans GROUP BY label")}
            by_node = {r["served_by"]: r["n"] for r in c.execute("SELECT served_by, COUNT(*) n FROM scans GROUP BY served_by")}
        return {
            "total_scans": total,
            "avg_latency_ms": round(avg_lat, 1),
            "avg_confidence": round(avg_conf, 3),
            "by_label": by_label,
            "by_node": by_node,
        }
