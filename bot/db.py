"""
bot/db.py - SQLite = tek doğruluk kaynağı. Excel sadece onun görünümü.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from typing import Any, Iterable

from .config import CFG

SCHEMA = """
CREATE TABLE IF NOT EXISTS applicants (
    id INTEGER PRIMARY KEY,
    ad TEXT, soyad TEXT, pasaport_no TEXT, dogum_tarihi TEXT,
    uyruk TEXT, telefon TEXT,
    vfs_email TEXT UNIQUE, vfs_sifre TEXT,
    imap_app_sifre TEXT, imap_sunucu TEXT,
    merkez_tercih TEXT, kategori TEXT,
    tarih_baslangic TEXT, tarih_bitis TEXT,
    durum TEXT DEFAULT 'PENDING',
    randevu_tarihi TEXT, randevu_saati TEXT, merkez TEXT, referans_no TEXT,
    deneme_sayisi INTEGER DEFAULT 0,
    son_hata TEXT, guncelleme_zamani TEXT,
    proxy_id INTEGER, yedek_email TEXT
);
CREATE TABLE IF NOT EXISTS slots_seen (
    hash TEXT PRIMARY KEY, merkez TEXT, kategori TEXT, tarih TEXT, ilk_gorulme TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    account_id TEXT PRIMARY KEY, proxy_id INTEGER, user_agent TEXT,
    cf_clearance TEXT, cookies TEXT, authorize TEXT, x_auth_token TEXT,
    updated_at REAL, cf_expires_at REAL
);
CREATE TABLE IF NOT EXISTS proxy_health (
    proxy TEXT PRIMARY KEY, fail_count INTEGER DEFAULT 0,
    cooldown_until REAL DEFAULT 0, last_ok REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT,
    applicant_id INTEGER, mesaj TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

INPUT_COLS = [
    "id", "ad", "soyad", "pasaport_no", "dogum_tarihi", "uyruk", "telefon",
    "vfs_email", "vfs_sifre", "imap_app_sifre", "imap_sunucu",
    "merkez_tercih", "kategori", "tarih_baslangic", "tarih_bitis", "yedek_email",
]
OUTPUT_COLS = [
    "durum", "randevu_tarihi", "randevu_saati", "merkez", "referans_no",
    "deneme_sayisi", "son_hata", "guncelleme_zamani",
]


class DB:
    def __init__(self, path: str | None = None):
        self.path = path or f"{CFG['paths']['data_dir']}/state.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- düşük seviye ----
    def q(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)))

    def x(self, sql: str, params: Iterable = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

    def now(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # ---- başvuran ----
    def upsert_applicant(self, row: dict[str, Any]) -> None:
        cols = [c for c in INPUT_COLS if c in row and row[c] not in (None, "")]
        if not cols:
            return
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        self.x(
            f"INSERT INTO applicants ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [row[c] for c in cols],
        )

    def applicants(self, durum: Iterable[str] | None = None) -> list[sqlite3.Row]:
        if durum:
            marks = ", ".join("?" for _ in durum)
            return self.q(f"SELECT * FROM applicants WHERE durum IN ({marks})", list(durum))
        return self.q("SELECT * FROM applicants ORDER BY id")

    def set_status(self, applicant_id: int, durum: str | None = None, **fields: Any) -> None:
        sets, params = [], []
        if durum:
            sets.append("durum=?")
            params.append(durum)
        for k, v in fields.items():
            if k in OUTPUT_COLS:
                sets.append(f"{k}=?")
                params.append(v)
        sets.append("guncelleme_zamani=?")
        params.append(self.now())
        params.append(applicant_id)
        self.x(f"UPDATE applicants SET {', '.join(sets)} WHERE id=?", params)

    def bump_attempt(self, applicant_id: int, hata: str = "") -> None:
        self.x(
            "UPDATE applicants SET deneme_sayisi=deneme_sayisi+1, son_hata=?, guncelleme_zamani=? WHERE id=?",
            (hata[:500], self.now(), applicant_id),
        )

    # ---- slot dedupe ----
    def slot_is_new(self, slot_hash: str, merkez: str, kategori: str, tarih: str) -> bool:
        rows = self.q("SELECT 1 FROM slots_seen WHERE hash=?", (slot_hash,))
        if rows:
            return False
        self.x(
            "INSERT OR IGNORE INTO slots_seen (hash, merkez, kategori, tarih, ilk_gorulme) VALUES (?,?,?,?,?)",
            (slot_hash, merkez, kategori, tarih, self.now()),
        )
        return True

    # ---- oturum ----
    def session_load(self, account_id: str) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM sessions WHERE account_id=?", (account_id,))
        if not rows:
            return None
        s = dict(rows[0])
        s["cookies"] = json.loads(s["cookies"] or "[]")
        return s

    def session_save(self, account_id: str, **fields: Any) -> None:
        fields["account_id"] = account_id
        fields["updated_at"] = time.time()
        if "cookies" in fields and not isinstance(fields["cookies"], str):
            fields["cookies"] = json.dumps(fields["cookies"])
        cols = list(fields)
        self.x(
            f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(account_id) DO UPDATE SET "
            f"{', '.join(f'{c}=excluded.{c}' for c in cols if c != 'account_id')}",
            [fields[c] for c in cols],
        )

    def session_clear(self, account_id: str) -> None:
        self.x("DELETE FROM sessions WHERE account_id=?", (account_id,))

    # ---- proxy sağlığı ----
    def proxy_penalize(self, proxy: str, seconds: float) -> None:
        self.x(
            "INSERT INTO proxy_health (proxy, fail_count, cooldown_until) VALUES (?,1,?) "
            "ON CONFLICT(proxy) DO UPDATE SET fail_count=fail_count+1, cooldown_until=?",
            (proxy, time.time() + seconds, time.time() + seconds),
        )

    def proxy_ok(self, proxy: str) -> None:
        self.x(
            "INSERT INTO proxy_health (proxy, fail_count, cooldown_until, last_ok) VALUES (?,0,0,?) "
            "ON CONFLICT(proxy) DO UPDATE SET fail_count=0, cooldown_until=0, last_ok=?",
            (proxy, time.time(), time.time()),
        )

    def proxy_cooling(self, proxy: str) -> bool:
        rows = self.q("SELECT cooldown_until FROM proxy_health WHERE proxy=?", (proxy,))
        return bool(rows and rows[0]["cooldown_until"] > time.time())

    # ---- log / meta ----
    def log(self, level: str, mesaj: str, applicant_id: int | None = None) -> None:
        self.x(
            "INSERT INTO events (ts, level, applicant_id, mesaj) VALUES (?,?,?,?)",
            (self.now(), level, applicant_id, mesaj[:2000]),
        )

    def meta_set(self, k: str, v: str) -> None:
        self.x("INSERT INTO meta (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def meta_get(self, k: str, default: str | None = None) -> str | None:
        rows = self.q("SELECT v FROM meta WHERE k=?", (k,))
        return rows[0]["v"] if rows else default


DB = DB()
