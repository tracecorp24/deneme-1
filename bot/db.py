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
    proxy_id INTEGER, yedek_email TEXT,
    submitted_at TEXT
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
CREATE TABLE IF NOT EXISTS notified (
    applicant_id INTEGER, hash TEXT, ts TEXT,
    PRIMARY KEY (applicant_id, hash)
);
CREATE TABLE IF NOT EXISTS booking_lock (
    applicant_id INTEGER PRIMARY KEY,
    owner TEXT,
    since REAL
);
"""

INPUT_COLS = [
    "id", "ad", "soyad", "pasaport_no", "dogum_tarihi", "uyruk", "telefon",
    "vfs_email", "vfs_sifre", "imap_app_sifre", "imap_sunucu",
    "merkez_tercih", "kategori", "tarih_baslangic", "tarih_bitis", "yedek_email",
]
OUTPUT_COLS = [
    "durum", "randevu_tarihi", "randevu_saati", "merkez", "referans_no",
    "deneme_sayisi", "son_hata", "guncelleme_zamani", "submitted_at",
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
            # Kolon göçü (E1: submitted_at)
            try:
                self._conn.execute("ALTER TABLE applicants ADD COLUMN submitted_at TEXT")
            except sqlite3.OperationalError:
                pass
            # Tablo göçü (F3: booking_lock)
            try:
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS booking_lock (applicant_id INTEGER PRIMARY KEY, owner TEXT, since REAL)"
                )
            except sqlite3.OperationalError:
                pass
            self._conn.commit()

    def acquire_booking_lock(self, applicant_id: int, owner: str = "booker", timeout_s: float = 300.0) -> bool:
        """F2/F3: Aynı başvuran için eşzamanlı rezervasyonları engellemek için kilit alır."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT owner, since FROM booking_lock WHERE applicant_id=?", (applicant_id,))
            row = cur.fetchone()
            now = time.time()
            if row:
                since = row["since"]
                if (now - since) < timeout_s:
                    return False  # Hâlâ geçerli bir kilit var
                # Zaman aşımına uğramış eski kilit, devral
                cur.execute("UPDATE booking_lock SET owner=?, since=? WHERE applicant_id=?", (owner, now, applicant_id))
            else:
                cur.execute("INSERT INTO booking_lock (applicant_id, owner, since) VALUES (?, ?, ?)", (applicant_id, owner, now))
            self._conn.commit()
            return True

    def release_booking_lock(self, applicant_id: int) -> None:
        """F2/F3: Rezervasyon kilidini kaldırır."""
        with self._lock:
            self._conn.execute("DELETE FROM booking_lock WHERE applicant_id=?", (applicant_id,))
            self._conn.commit()

    def is_booking_locked(self, applicant_id: int, timeout_s: float = 300.0) -> bool:
        with self._lock:
            rows = list(self._conn.execute("SELECT since FROM booking_lock WHERE applicant_id=?", (applicant_id,)))
            if not rows:
                return False
            return (time.time() - rows[0]["since"]) < timeout_s

    def budget_is_locked(self, key: str) -> bool:
        """E3: Login bütçesi meta tablosundan kontrol edilir."""
        until = self.meta_get(f"cooldown:{key}")
        return bool(until and float(until) > time.time())

    def budget_lock(self, key: str, seconds: float) -> None:
        """E3: Login bütçesi cooldown süresi meta tablosuna yazılır."""
        self.meta_set(f"cooldown:{key}", str(time.time() + seconds))

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

    def applicant_notified(self, applicant_id: int, slot_hash: str) -> bool:
        """D1: Başvuran bazlı dedupe. Aynı slot daha önce bu başvurana bildirildiyse True döner."""
        rows = self.q("SELECT 1 FROM notified WHERE applicant_id=? AND hash=?", (applicant_id, slot_hash))
        if rows:
            return True
        self.x(
            "INSERT OR IGNORE INTO notified (applicant_id, hash, ts) VALUES (?,?,?)",
            (applicant_id, slot_hash, self.now()),
        )
        return False

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
