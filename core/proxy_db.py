"""Proxy kullanim takibi icin SQLite deposu.

Tek dosya (proxy_state.db) tum kullanim verisini tutar:

    proxies : ip, last_used, use_count, bad, updated_at
    state   : kucuk ayar degerleri (or. last_ip)

Onemli ozellikler:
  * ``pick()`` secim + isaretlemeyi TEK bir ``BEGIN IMMEDIATE`` islemi icinde
    yapar. Boylece ayni anda birden fazla sekme (surec) calistiginda ayni
    proxy iki kez secilmez.
  * Isaretleme proxy secildigi ANDA yapilir; uretimin bitmesi beklenmez.
  * WAL modu: okuma ve yazma birbirini bloklamaz.
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE


import os
import sqlite3
import threading
import time
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS proxies (
    ip         TEXT PRIMARY KEY,
    last_used  REAL    NOT NULL DEFAULT 0,
    use_count  INTEGER NOT NULL DEFAULT 0,
    bad        INTEGER NOT NULL DEFAULT 0,
    updated_at REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_proxies_pick ON proxies(bad, last_used);
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class ProxyDB:
    """Thread-safe ve surec-safe proxy kullanim deposu."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()
        self._init_lock = threading.Lock()
        with self._init_lock:
            self._conn().executescript(SCHEMA)

    # -- baglanti ---------------------------------------------------------- #

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.path,
                timeout=30.0,
                isolation_level=None,  # otomatik transaction yok, elle yonetiyoruz
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None

    # -- tohumlama --------------------------------------------------------- #

    def seed(self, ips: Iterable[str]) -> None:
        """Proxy listesini tabloya yazar (var olanlarin ustune yazmaz)."""
        rows = [(ip,) for ip in ips]
        if not rows:
            return
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany("INSERT OR IGNORE INTO proxies(ip) VALUES(?)", rows)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise

    def count(self) -> int:
        row = self._conn().execute("SELECT COUNT(*) FROM proxies").fetchone()
        return int(row[0]) if row else 0

    def never_used_count(self) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) FROM proxies WHERE last_used = 0 AND bad = 0"
        ).fetchone()
        return int(row[0]) if row else 0

    # -- secim ------------------------------------------------------------- #

    def pick(self, exclude_ip: Optional[str], now: float) -> Optional[str]:
        """En eski kullanilan proxy'yi secer ve ANDA isaretler.

        Adaylar: ``bad=0`` ve ``exclude_ip`` disinda, sirasi ``last_used``
        (artan) + kayit sirasi. Isaretleme ayni transaction icinde yapilir.
        """
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT ip FROM proxies "
                " WHERE bad = 0 AND (? IS NULL OR ip <> ?) "
                " ORDER BY last_used ASC, rowid ASC LIMIT 1",
                (exclude_ip, exclude_ip),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT ip FROM proxies WHERE bad = 0 ORDER BY last_used ASC, rowid ASC LIMIT 1"
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT ip FROM proxies ORDER BY last_used ASC, rowid ASC LIMIT 1"
                ).fetchone()

            ip = row[0] if row else None
            if ip is not None:
                conn.execute(
                    "UPDATE proxies SET last_used = ?, use_count = use_count + 1, updated_at = ? "
                    "WHERE ip = ?",
                    (now, now, ip),
                )
                conn.execute(
                    "INSERT INTO state(key, value) VALUES('last_ip', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (ip,),
                )
            conn.execute("COMMIT")
            return ip
        except sqlite3.Error:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    def position_of(self, ip: str) -> int:
        """Proxy'nin secim sirasindaki 1 tabanli konumu (en eski = 1)."""
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM proxies p2 JOIN proxies p1 ON p1.ip = ? "
            " WHERE (p2.last_used < p1.last_used) "
            "    OR (p2.last_used = p1.last_used AND p2.rowid < p1.rowid)",
            (ip,),
        ).fetchone()
        return (int(row[0]) if row else 0) + 1

    # -- isaretleme -------------------------------------------------------- #

    def mark_bad(self, ip: str) -> None:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE proxies SET bad = 1, updated_at = ? WHERE ip = ?",
                (time.time(), ip),
            )
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise

    def unmark_bad(self, ip: str) -> None:
        conn = self._conn()
        conn.execute("UPDATE proxies SET bad = 0 WHERE ip = ?", (ip,))

    # -- state ------------------------------------------------------------- #

    def get_state(self, key: str) -> Optional[str]:
        row = self._conn().execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, key: str, value: Optional[str]) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # -- legacy aktarim ---------------------------------------------------- #

    def import_state(
        self,
        bad: Iterable[str] = (),
        used: Optional[dict] = None,
        last_ip: Optional[str] = None,
    ) -> None:
        """Eski JSON state dosyasindaki veriyi tabloya aktarir."""
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            now = time.time()
            for ip in bad:
                conn.execute(
                    "UPDATE proxies SET bad = 1, updated_at = ? WHERE ip = ?", (now, ip)
                )
            for ip, ts in (used or {}).items():
                conn.execute(
                    "UPDATE proxies SET last_used = ?, updated_at = ? WHERE ip = ?",
                    (float(ts), now, ip),
                )
            if last_ip:
                conn.execute(
                    "INSERT INTO state(key, value) VALUES('last_ip', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (last_ip,),
                )
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise

    # -- bilgi ------------------------------------------------------------- #

    def stats(self) -> dict:
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*), SUM(bad), SUM(CASE WHEN last_used = 0 THEN 1 ELSE 0 END), "
            "       SUM(use_count), MAX(last_used) FROM proxies"
        ).fetchone()
        total, bad, unused, uses, last = row if row else (0, 0, 0, 0, 0)
        return {
            "total": int(total or 0),
            "bad": int(bad or 0),
            "unused": int(unused or 0),
            "uses": int(uses or 0),
            "last_used": float(last or 0),
            "last_ip": self.get_state("last_ip"),
        }
